"""
End-to-end test: Extract text → translate → reinsert → save output image.

Requires:
  - AZURE_FOUNDRY_ENDPOINT set in .env  (for real translation)
  - az login                             (for auth)

Falls back to stub translation [IT: ...] if Foundry endpoint is not configured.

Run with:
    python -m tests.test_extract_reinsert
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline.extractor import _extract_via_easyocr, has_localizable_text, TextBlock
from pipeline.reinsert import reinsert_raster
from config import EASYOCR_LANGUAGES, SOURCE_LANGUAGE, TARGET_LANGUAGE, AZURE_FOUNDRY_ENDPOINT

SOURCE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "source-art")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "output", "test_reinsert")

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

    use_llm = bool(AZURE_FOUNDRY_ENDPOINT)
    mode = "Azure AI Foundry (Claude)" if use_llm else "stub [IT: ...]  — set AZURE_FOUNDRY_ENDPOINT in .env for real translation"

    print(f"Source   : {SOURCE_LANGUAGE}")
    print(f"Target   : {TARGET_LANGUAGE}")
    print(f"Translator: {mode}")
    print(f"Output   : {OUTPUT_DIR}\n")

    if use_llm:
        from pipeline.translator import translate_blocks

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
            print("  → Skipped (NoLoc)\n")
            continue

        # Step 4 – Translate
        if use_llm:
            print(f"\n  Translating via Foundry ({TARGET_LANGUAGE})...")
            translated = translate_blocks(blocks, SOURCE_LANGUAGE, TARGET_LANGUAGE)
        else:
            translated = _stub_translate(blocks, TARGET_LANGUAGE)

        # Step 5 – Reinsert
        out_path = os.path.join(OUTPUT_DIR, f"{name}_{TARGET_LANGUAGE}.png")
        reinsert_raster(path, blocks, translated, out_path)
        print(f"\n  → Saved: {os.path.basename(out_path)}\n")


if __name__ == "__main__":
    main()
