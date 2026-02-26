"""
Quick OCR test — runs without Azure credentials (uses EasyOCR locally).

Run with:
    python -m tests.test_ocr
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pipeline.extractor import _extract_via_easyocr, has_localizable_text

# English-only models — fast to load, good for Latin-script source images
LANGUAGES = ["en"]

SAMPLES = {
    "Office (English UI elements)": r"C:\Users\jdobrovodska\source\repos\MATUA 1\MATUA Pass\Office_10599332_PreHandoff_locFile_9fbf326f-4b3d-43aa-823d-8dbac5672e1f.png",
    "No Loc Art (tab bar)":         r"C:\Users\jdobrovodska\source\repos\No Loc Art\No Loc Art\Xenon_8181674_PreHandoff_locFile_dax-timeline-tab.png",
    "No Loc Art (gear icon)":       r"C:\Users\jdobrovodska\source\repos\No Loc Art\No Loc Art\Xenon_8141739_PreHandoff_locFile_gear-icon.png",
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
            blocks = _extract_via_easyocr(path, languages=LANGUAGES)
            localizable = has_localizable_text(blocks)
            print(f"  Blocks : {len(blocks)}  |  Localizable : {localizable}\n")
            for b in blocks:
                print(f"  [{b.confidence:.2f}]  {b.text!r}")
        except Exception as e:
            print(f"  ERROR: {e}")
        print()


if __name__ == "__main__":
    main()
