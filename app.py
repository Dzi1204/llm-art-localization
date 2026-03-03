"""
LLMage — Localization UI
Run with: streamlit run app.py
"""

import os
import base64
import shutil
import tempfile
from pathlib import Path
import streamlit as st

NO_LOC_DIR = Path(__file__).parent / "output" / "no-loc"

from config import SOURCE_LANGUAGE, AZURE_OPENAI_ENDPOINT, AZURE_ENDPOINT, QE_ENDPOINT, QE_BEARER_TOKEN
from pipeline.extractor import extract_text, has_localizable_text
from pipeline.reinsert import reinsert_raster, reinsert_svg
from pipeline.packager import create_review_package

# ── Page config ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="LLMArtLocalization",
    page_icon="🌍",
    layout="wide",
)

st.title("🌍 LLM - Art Localization")

# ── Language selector ─────────────────────────────────────────────────────────

LANGUAGES = {
    "it-IT": "🇮🇹 Italian (it-IT)",
    "de-DE": "🔒 German (de-DE)",
    "es-ES": "🔒 Spanish (es-ES)",
    "fr-FR": "🔒 French (fr-FR)",
    "pt-BR": "🔒 Portuguese Brazil (pt-BR)",
    "ja-JP": "🔒 Japanese (ja-JP)",
    "ko-KR": "🔒 Korean (ko-KR)",
    "zh-CN": "🔒 Chinese Simplified (zh-CN)",
    "zh-TW": "🔒 Chinese Traditional (zh-TW)",
    "sk-SK": "🇸🇰 Slovak (sk-SK)",
    "cs-CZ": "🔒 Czech (cs-CZ)",
    "pl-PL": "🔒 Polish (pl-PL)",
    "ro-RO": "🔒 Romanian (ro-RO)",
    "nl-NL": "🔒 Dutch (nl-NL)",
    "da-DK": "🔒 Danish (da-DK)",
    "lv-LV": "🔒 Latvian (lv-LV)",
}
ACTIVE_LANGUAGES = {"it-IT", "sk-SK"}

selected_labels = st.multiselect(
    "Target language(s)",
    options=[v for k, v in LANGUAGES.items() if k in ACTIVE_LANGUAGES],
    default=[list(LANGUAGES.values())[0]],
    help="Select one or more target languages.",
)

if not selected_labels:
    st.info("Select at least one target language to get started.")
    st.stop()

_label_to_key = {v: k for k, v in LANGUAGES.items()}
active_selected = [_label_to_key[v] for v in selected_labels if v in _label_to_key]
st.caption(f"Source: **{SOURCE_LANGUAGE}** → Target: **{', '.join(active_selected)}**")

# ── Sidebar — backend status ──────────────────────────────────────────────────

with st.sidebar:
    st.header("Pipeline Status")

    if AZURE_OPENAI_ENDPOINT:
        st.success("🔵 Translator: Azure OpenAI")
    else:
        st.warning("🟡 Translator: Stub (set AZURE_OPENAI_ENDPOINT in .env)")

    if AZURE_ENDPOINT:
        st.success("🔵 OCR: Azure Document Intelligence")
    else:
        st.info("⚪ OCR: EasyOCR (local)")

    if QE_ENDPOINT:
        st.success("🟢 QE Scoring: Enabled")
    elif QE_ENDPOINT:
        st.warning("🟡 QE Scoring: Token missing")
    else:
        st.info("⚪ QE Scoring: Disabled")

    st.divider()
    st.subheader("Reinsertion Mode")
    reinsert_mode = st.radio(
        "reinsert_mode",
        options=["Standard (Pillow)", "LLM-guided", "Both (compare)"],
        index=0,
        label_visibility="collapsed",
        help=(
            "**Standard**: fast, deterministic Pillow algorithm.\n\n"
            "**LLM-guided**: GPT-4o looks at each region and decides font size + line breaks.\n\n"
            "**Both**: runs both and shows them side by side."
        ),
    )
    if reinsert_mode != "Standard (Pillow)" and not AZURE_OPENAI_ENDPOINT:
        st.warning("LLM reinsertion requires AZURE_OPENAI_ENDPOINT in .env")
        reinsert_mode = "Standard (Pillow)"
    if reinsert_mode in ("LLM-guided", "Both (compare)"):
        st.caption("⚠️ Slow — 1 API call per text region")

    st.divider()
    st.caption("Configure backends in `.env`")

# ── Upload ────────────────────────────────────────────────────────────────────

uploaded_files = st.file_uploader(
    "Upload source image(s)",
    type=["png", "jpg", "jpeg", "bmp", "tiff", "svg"],
    accept_multiple_files=True,
    help="English (en-US) UI screenshots or art assets",
)

if not uploaded_files:
    st.session_state.pop("results", None)
    st.info("Upload one or more images to get started.")
    st.stop()

# Clear old results when the set of uploaded files changes
current_names = sorted(f.name for f in uploaded_files)
if st.session_state.get("last_files") != current_names:
    st.session_state.pop("results", None)
    st.session_state["last_files"] = current_names

# ── Preview uploaded images ───────────────────────────────────────────────────

cols_per_row = min(len(uploaded_files), 4)
preview_cols = st.columns(cols_per_row)
for col, uf in zip(preview_cols, uploaded_files):
    with col:
        if os.path.splitext(uf.name)[1].lower() == ".svg":
            svg_b64 = base64.b64encode(uf.getvalue()).decode()
            st.markdown(
                f'<img src="data:image/svg+xml;base64,{svg_b64}" style="width:100%" alt="{uf.name}">',
                unsafe_allow_html=True,
            )
            st.caption(uf.name)
        else:
            st.image(uf.getvalue(), caption=uf.name, use_container_width=True)

# ── Run ───────────────────────────────────────────────────────────────────────

if st.button("▶ Run Localization", type="primary", use_container_width=True):

    all_image_results = {}

    for uf in uploaded_files:
        ext  = os.path.splitext(uf.name)[1].lower()
        mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".bmp": "image/bmp", ".tiff": "image/tiff",
                ".svg": "image/svg+xml"}.get(ext, "image/png")

        lang_results = {}

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, f"source{ext}")
            with open(input_path, "wb") as f:
                f.write(uf.getvalue())

            # Step 1 — Extract
            with st.spinner(f"Extracting text from {uf.name}..."):
                blocks = extract_text(input_path)
                if not has_localizable_text(blocks):
                    NO_LOC_DIR.mkdir(parents=True, exist_ok=True)
                    dest = NO_LOC_DIR / uf.name
                    if not dest.exists():
                        shutil.copy2(input_path, dest)
                    st.warning(f"{uf.name}: No localizable text found (NoLoc) — saved to `output/no-loc/` and skipped.")
                    continue

            # Step 2-5 — Per language
            for selected_lang in active_selected:
                with st.status(f"{uf.name} → {selected_lang}", expanded=False):

                    # Translate
                    if AZURE_OPENAI_ENDPOINT:
                        from pipeline.translator import translate_blocks
                        st.write(f"Translating → {selected_lang}")
                        translated = translate_blocks(blocks, SOURCE_LANGUAGE, selected_lang)
                    else:
                        prefix = selected_lang.split("-")[0].upper()
                        from pipeline.extractor import TextBlock
                        translated = [
                            TextBlock(text=f"[{prefix}: {b.text}]", bounding_box=b.bounding_box,
                                      page=b.page, confidence=b.confidence, element_id=b.element_id)
                            for b in blocks
                        ]

                    # QE scoring
                    qe_results = None
                    if QE_ENDPOINT and QE_BEARER_TOKEN:
                        from pipeline.qe_client import score_translations
                        st.write(f"Scoring quality → {selected_lang}")
                        try:
                            qe_results = score_translations(blocks, translated, selected_lang)
                        except Exception as e:
                            err = str(e)
                            if "DefaultAzureCredential" in err or "CredentialUnavailable" in err or "ClientAuthenticationError" in err:
                                st.warning("QE scoring skipped: no Azure credentials. Set `QE_TOKEN` in `.env` or run `az login`.")
                            else:
                                st.warning(f"QE scoring skipped: {e}")

                    # Reinsert
                    output_path = os.path.join(tmpdir, f"localized_{selected_lang}{ext}")
                    llm_output_path = os.path.join(tmpdir, f"localized_{selected_lang}_llm{ext}")

                    if ext == ".svg":
                        st.write(f"Reinserting text → {selected_lang}")
                        reinsert_svg(input_path, blocks, translated, output_path)
                        llm_localized_bytes = None
                    elif reinsert_mode == "Standard (Pillow)":
                        st.write(f"Reinserting text → {selected_lang} (Pillow)")
                        reinsert_raster(input_path, blocks, translated, output_path)
                        llm_localized_bytes = None
                    elif reinsert_mode == "LLM-guided":
                        st.write(f"Reinserting text → {selected_lang} (LLM-guided, 1 call/region...)")
                        from pipeline.llm_reinsert import reinsert_llm_guided
                        reinsert_llm_guided(
                            input_path, blocks, translated, selected_lang, output_path,
                            status_callback=st.write,
                        )
                        llm_localized_bytes = None
                    else:  # Both
                        st.write(f"Reinserting text → {selected_lang} (Pillow)...")
                        reinsert_raster(input_path, blocks, translated, output_path)
                        st.write(f"Reinserting text → {selected_lang} (LLM-guided, 1 call/region...)")
                        from pipeline.llm_reinsert import reinsert_llm_guided
                        reinsert_llm_guided(
                            input_path, blocks, translated, selected_lang, llm_output_path,
                            status_callback=st.write,
                        )
                        with open(llm_output_path, "rb") as f:
                            llm_localized_bytes = f.read()

                    # Package — only if QE flagged something or QE was not run
                    needs_review = not qe_results or any(r.flagged for r in qe_results)
                    zip_bytes = None
                    zip_name = None
                    if needs_review:
                        package_dir = os.path.join(tmpdir, "packages")
                        asset_id = os.path.splitext(uf.name)[0]
                        zip_path = create_review_package(
                            asset_id=asset_id,
                            original_path=input_path,
                            localized_path=output_path,
                            source_blocks=blocks,
                            translated_blocks=translated,
                            source_language=SOURCE_LANGUAGE,
                            target_language=selected_lang,
                            output_dir=package_dir,
                            qe_results=qe_results,
                        )
                        with open(zip_path, "rb") as fzip:
                            zip_bytes = fzip.read()
                        zip_name = os.path.basename(zip_path)
                        st.write("Review package created (QE flagged strings)")
                    else:
                        asset_id = os.path.splitext(uf.name)[0]
                        st.write("QE passed — no review package needed")

                    with open(output_path, "rb") as fimg:
                        localized_bytes = fimg.read()

                lang_results[selected_lang] = {
                    "translated": translated,
                    "qe_results": qe_results,
                    "localized_bytes": localized_bytes,
                    "llm_localized_bytes": llm_localized_bytes,
                    "zip_bytes": zip_bytes,
                    "zip_name": zip_name,
                    "asset_id": asset_id,
                }

        all_image_results[uf.name] = {
            "lang_results": lang_results,
            "blocks": blocks,
            "orig_bytes": uf.getvalue(),
            "ext": ext,
            "mime": mime,
        }

    st.session_state.results = {
        "images": all_image_results,
        "active_selected": active_selected,
    }

# ── Results ───────────────────────────────────────────────────────────────────

if "results" not in st.session_state:
    st.stop()

pr              = st.session_state.results
active_selected = pr["active_selected"]

CARD_STYLE  = "flex:1 1 0;min-width:260px;text-align:center;"
ROW_STYLE   = "display:flex;gap:16px;padding:6px 0;"
WRAP_STYLE  = "max-height:900px;overflow-y:auto;padding:4px 0 12px 0;"
IMG_STYLE   = "width:100%;height:360px;object-fit:contain;border-radius:6px;border:1px solid #ddd;background:#f8f8f8;display:block;"

for fname, img_data in pr["images"].items():
    lang_results = img_data["lang_results"]
    blocks       = img_data["blocks"]
    orig_bytes   = img_data["orig_bytes"]
    mime         = img_data["mime"]
    ext          = img_data["ext"]

    with st.expander(f"📄 {fname}", expanded=True):

        # ── Language selector (drives both comparison strip and details) ───────
        view_lang = st.radio(
            "View details:",
            options=active_selected,
            index=0,
            horizontal=True,
            label_visibility="collapsed",
            key=f"radio_{fname}",
        )

        r = lang_results[view_lang]

        # ── Comparison strip ──────────────────────────────────────────────────
        orig_b64 = base64.b64encode(orig_bytes).decode()
        loc_b64  = base64.b64encode(r["localized_bytes"]).decode()
        qe = r["qe_results"]
        if qe:
            flagged_count = sum(1 for res in qe if res.flagged)
            badge = f"&nbsp;🚩 {flagged_count} flagged" if flagged_count else "&nbsp;✅ QE OK"
        else:
            badge = ""

        def _card(label, b64):
            return (
                f'<div style="{CARD_STYLE}">'
                f'<p style="margin:0 0 6px 0;font-weight:600;font-size:14px;">{label}</p>'
                f'<img src="data:{mime};base64,{b64}" style="{IMG_STYLE}"></div>'
            )

        orig_card  = _card("Original (en-US)", orig_b64)
        rows = f'<div style="{ROW_STYLE}">{orig_card}{_card(f"Standard (Pillow){badge}", loc_b64)}</div>'

        if r.get("llm_localized_bytes"):
            llm_b64 = base64.b64encode(r["llm_localized_bytes"]).decode()
            rows += f'<div style="{ROW_STYLE}">{orig_card}{_card(f"LLM-guided{badge}", llm_b64)}</div>'

        st.markdown(f'<div style="{WRAP_STYLE}">{rows}</div>', unsafe_allow_html=True)

        # QE banner
        if r["qe_results"]:
            flagged = [res for res in r["qe_results"] if res.flagged]
            scored  = [res for res in r["qe_results"] if res.score is not None]
            if flagged:
                st.error(f"⚠️ {len(flagged)} string(s) flagged by QE — review before publishing")
            else:
                st.success(f"✅ All {len(scored)} scored strings passed QE (threshold 0.7)")

        # Translations table
        rows = []
        for i, (src, tgt) in enumerate(zip(blocks, r["translated"])):
            row = {"Source (EN)": src.text, f"Translated ({view_lang})": tgt.text}
            if r["qe_results"] and i < len(r["qe_results"]):
                res = r["qe_results"][i]
                row["QE Score"] = f"{res.score:.2f}" if res.score is not None else "N/A"
                row["Status"] = "🚩 Flagged" if res.flagged else ("✅ OK" if res.score is not None else "—")
            rows.append(row)
        st.dataframe(rows, use_container_width=True, hide_index=True)

        # Downloads
        dl_col1, dl_col2 = st.columns(2)
        with dl_col1:
            st.download_button(
                "⬇ Localized Image",
                data=r["localized_bytes"],
                file_name=f"{r['asset_id']}_{view_lang}{ext}",
                mime=mime,
                use_container_width=True,
                key=f"dl_img_{fname}_{view_lang}",
            )
        with dl_col2:
            if r["zip_bytes"]:
                st.download_button(
                    "⬇ Review Package (ZIP)",
                    data=r["zip_bytes"],
                    file_name=r["zip_name"],
                    mime="application/zip",
                    use_container_width=True,
                    key=f"dl_zip_{fname}_{view_lang}",
                )
            else:
                st.success("✅ QE passed — no review needed", icon=None)
