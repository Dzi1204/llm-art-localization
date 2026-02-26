"""
End-to-end test: Extract -> translate -> QE score -> reinsert -> save output image.

Requires in .env:
  AZURE_FOUNDRY_ENDPOINT   -> real LLM translation (falls back to stub if not set)
  QE_ENDPOINT              -> QE scoring (skipped if not set)
  QE_BEARER_TOKEN          -> manually obtained Bearer token for QE dev endpoint

Run with:
    python -m tests.test_extract_reinsert
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline.extractor import _extract_via_easyocr, has_localizable_text, TextBlock
from pipeline.reinsert import reinsert_raster
from pipeline.packager import create_review_package
from config import (
    EASYOCR_LANGUAGES, SOURCE_LANGUAGE, TARGET_LANGUAGE,
    AZURE_FOUNDRY_ENDPOINT, OPENAI_API_KEY, QE_ENDPOINT, QE_BEARER_TOKEN
)

SOURCE_DIR  = os.path.join(os.path.dirname(__file__), "..", "data", "source-art")
OUTPUT_DIR  = os.path.join(os.path.dirname(__file__), "..", "output", "test_reinsert")
PACKAGE_DIR = os.path.join(os.path.dirname(__file__), "..", "output", "packages")

SOURCE_FILES = [
    "select-everyone.png",
    "view-report-for-compliance-policy.png",
    "8680235-limited-query-preview.png",
    "configuration-properties.png",
]


def _stub_translate(blocks: list, target_lang: str) -> list:
    prefix = target_lang.split("-")[0].upper()
    return [
        TextBlock(
            text=f"[{prefix}: {b.text}]",
            bounding_box=b.bounding_box,
            page=b.page,
            confidence=b.confidence,
            element_id=b.element_id,
        )
        for b in blocks
    ]


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    if AZURE_FOUNDRY_ENDPOINT:
        translator_label = "Azure AI Foundry"
        use_llm = True
    elif OPENAI_API_KEY:
        translator_label = "OpenAI"
        use_llm = True
    else:
        translator_label = "stub [IT: ...] — set AZURE_FOUNDRY_ENDPOINT or OPENAI_API_KEY for real translation"
        use_llm = False

    if QE_ENDPOINT and QE_BEARER_TOKEN:
        use_qe = True
        qe_label = "enabled (dev)"
    elif not QE_ENDPOINT:
        use_qe = False
        qe_label = "skipped — QE_ENDPOINT not set in .env"
    else:
        use_qe = False
        qe_label = "skipped — QE_BEARER_TOKEN not set (get one via: az account get-access-token --resource api://0da43d3e-94e5-42fe-a9f4-09600ef73478)"

    os.makedirs(PACKAGE_DIR, exist_ok=True)

    print(f"Source      : {SOURCE_LANGUAGE}")
    print(f"Target      : {TARGET_LANGUAGE}")
    print(f"Translator  : {translator_label}")
    print(f"QE scoring  : {qe_label}")
    print(f"Images      : {OUTPUT_DIR}")
    print(f"Packages    : {PACKAGE_DIR}\n")

    if use_llm:
        from pipeline.translator import translate_blocks
    if use_qe:
        from pipeline.qe_client import score_translations, print_qe_report

    for filename in SOURCE_FILES:
        path = os.path.join(SOURCE_DIR, filename)
        name = os.path.splitext(filename)[0]

        print(f"{'='*60}")
        print(f"  {filename}")
        print(f"{'='*60}")

        if not os.path.exists(path):
            print("  FILE NOT FOUND\n")
            continue

        # Step 3 – Extract
        blocks = _extract_via_easyocr(path, languages=EASYOCR_LANGUAGES)
        localizable = has_localizable_text(blocks)
        print(f"  Blocks extracted : {len(blocks)}  |  Localizable : {localizable}\n")

        for b in blocks:
            print(f"    [{b.confidence:.2f}] {b.text!r}")

        if not localizable:
            print("  -> Skipped (NoLoc)\n")
            continue

        # Step 4 – Translate
        if use_llm:
            print(f"\n  Translating via {translator_label} ({TARGET_LANGUAGE})...")
            translated = translate_blocks(blocks, SOURCE_LANGUAGE, TARGET_LANGUAGE)
        else:
            translated = _stub_translate(blocks, TARGET_LANGUAGE)

        # Step 4b – QE scoring
        if use_qe:
            try:
                print(f"\n  Scoring translations via QE (dev)...")
                qe_results = score_translations(blocks, translated, TARGET_LANGUAGE)
                print_qe_report(qe_results)
            except Exception as e:
                msg = str(e)
                if "401" in msg:
                    print(f"\n  QE scoring skipped: token expired or invalid.")
                    print(f"  Refresh with: az account get-access-token --resource api://0da43d3e-94e5-42fe-a9f4-09600ef73478")
                elif "403" in msg:
                    print(f"\n  QE scoring skipped: access denied (check token permissions).")
                elif "404" in msg:
                    print(f"\n  QE scoring skipped: endpoint not found — check QE_ENDPOINT in .env.")
                else:
                    print(f"\n  QE scoring skipped: {e}")
                print(f"  Continuing without QE scores...\n")

        # Step 5 – Reinsert
        out_path = os.path.join(OUTPUT_DIR, f"{name}_{TARGET_LANGUAGE}.png")
        reinsert_raster(path, blocks, translated, out_path)
        print(f"\n  -> Localized image : {os.path.basename(out_path)}")

        # Step 6 – Package for MATUA review
        zip_path = create_review_package(
            asset_id=name,
            original_path=path,
            localized_path=out_path,
            source_blocks=blocks,
            translated_blocks=translated,
            source_language=SOURCE_LANGUAGE,
            target_language=TARGET_LANGUAGE,
            output_dir=PACKAGE_DIR,
        )
        print(f"  -> Review package  : {os.path.basename(zip_path)}\n")


if __name__ == "__main__":
    main()
