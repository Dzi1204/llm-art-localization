"""
Quick OCR test — runs without Azure credentials (uses EasyOCR locally).
Tests on source-art and MATUA Pass/Fail samples included in the repo.

Run with:
    python -m tests.test_ocr
"""

import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

from pipeline.extractor import _extract_via_easyocr, has_localizable_text
from config import EASYOCR_LANGUAGES

DATA_DIR = os.path.join(PROJECT_ROOT, "data")

SAMPLES = {
    "Source (query preview)":   os.path.join(DATA_DIR, "source-art", "8680235-limited-query-preview.png"),
    "Source (select everyone)": os.path.join(DATA_DIR, "source-art", "select-everyone.png"),
    "MATUA Pass (Xenon)":       os.path.join(DATA_DIR, "matua-pass", "Xenon_8157719_PreHandoff_locFile_container-properties.png"),
    "MATUA Fail (Xenon)":       os.path.join(DATA_DIR, "matua-fail", "Xenon_8157723_PreHandoff_locFile_container-properties.png"),
}


def main():
    print("Loading EasyOCR (English only — fast)...\n")

    for label, path in SAMPLES.items():
        print(f"{'='*60}")
        print(f"  {label}")
        print(f"  {os.path.basename(path)}")
        print(f"{'='*60}")

        if not os.path.exists(path):
            print("  FILE NOT FOUND\n")
            continue

        try:
            blocks = _extract_via_easyocr(path, languages=EASYOCR_LANGUAGES)
            localizable = has_localizable_text(blocks)
            print(f"  Blocks : {len(blocks)}  |  Localizable : {localizable}\n")
            for b in blocks:
                print(f"  [{b.confidence:.2f}]  {b.text!r}")
        except Exception as e:
            print(f"  ERROR: {e}")
        print()


if __name__ == "__main__":
    main()
