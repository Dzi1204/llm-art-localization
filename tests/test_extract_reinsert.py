"""
End-to-end test: Extract text → stub translation → reinsert → save output image.

No Azure, no LLM API keys needed.
The stub translation marks each string as [IT: ...] so you can visually
confirm text was extracted and reinserted in the correct positions.

Run with:
    python -m tests.test_extract_reinsert
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline.extractor import _extract_via_easyocr, has_localizable_text, TextBlock
from pipeline.reinsert import reinsert_raster
from config import EASYOCR_LANGUAGES, SOURCE_LANGUAGE

SOURCE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "source-art")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "output", "test_reinsert")

SOURCE_FILES = [
    "select-everyone.png",
    "view-report-for-compliance-policy.png",
    "8680235-limited-query-preview.png",
    "configuration-properties.png",
]

TARGET_LANGUAGES = ["it-IT"]


def stub_translate(blocks: list, target_lang: str) -> list:
    """
    Placeholder — marks each block with the target language prefix.
    The data scientist will replace this with the real LLM translation prompt.
    """
    prefix = target_lang.split("-")[0].upper()  # "it-IT" → "IT"
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
    print(f"Source language : {SOURCE_LANGUAGE}")
    print(f"Target language : {TARGET_LANGUAGES[0]}  (stub only — real translation not wired yet)")
    print(f"Output dir      : {OUTPUT_DIR}\n")

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

        # Step 5 – Reinsert with stub
        for lang in TARGET_LANGUAGES:
            translated = stub_translate(blocks, lang)
            out_path = os.path.join(OUTPUT_DIR, f"{name}_{lang}.png")
            reinsert_raster(path, blocks, translated, out_path)
            print(f"\n  → {lang} saved: {os.path.basename(out_path)}")

        print()


if __name__ == "__main__":
    main()
