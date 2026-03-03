"""
LLM-guided reinsertion test.

Sends the full source image + all text regions in ONE API call.
GPT-4o sees the complete image and returns layout decisions for every region.

Run:
    python -m tests.test_llm_reinsert
    python -m tests.test_llm_reinsert --file select-everyone.png
    python -m tests.test_llm_reinsert --file select-everyone.png --target sk-SK
"""

import sys
import os
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path
from config import AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT, SOURCE_LANGUAGE, TARGET_LANGUAGES, AZURE_ENDPOINT
from pipeline.extractor import extract_text, has_localizable_text
from pipeline.translator import translate_blocks
from pipeline.llm_reinsert import reinsert_llm_guided

SOURCE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "source-art")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "output", "test_llm_reinsert")

SOURCE_FILES = sorted(
    f for f in os.listdir(SOURCE_DIR)
    if os.path.splitext(f)[1].lower() in {".png", ".jpg", ".jpeg", ".bmp", ".tiff"}
) if os.path.isdir(SOURCE_DIR) else []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default=None, help="Run on a single file only (e.g. select-everyone.png)")
    parser.add_argument("--target", default=None, help="Single target language (e.g. sk-SK)")
    args = parser.parse_args()

    files_to_run = [args.file] if args.file else SOURCE_FILES
    targets = [args.target] if args.target else TARGET_LANGUAGES

    if not AZURE_OPENAI_ENDPOINT:
        print("ERROR: AZURE_OPENAI_ENDPOINT not set in .env")
        sys.exit(1)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    ocr_label = "Azure Document Intelligence" if AZURE_ENDPOINT else "EasyOCR (local)"
    print(f"Source  : {SOURCE_LANGUAGE}")
    print(f"Targets : {targets}")
    print(f"Model   : {AZURE_OPENAI_DEPLOYMENT}")
    print(f"OCR     : {ocr_label}")
    print(f"Images  : {OUTPUT_DIR}\n")

    for filename in files_to_run:
        image_path = os.path.join(SOURCE_DIR, filename)
        if not os.path.exists(image_path):
            print(f"ERROR: file not found: {image_path}")
            continue

        name = Path(filename).stem
        print(f"{'='*60}")
        print(f"  {filename}")
        print(f"{'='*60}")

        print("  Extracting...")
        blocks = extract_text(image_path)
        print(f"  {len(blocks)} blocks extracted")

        if not has_localizable_text(blocks):
            print("  -> Skipped (no localizable text)\n")
            continue

        for b in blocks:
            print(f"    [{b.confidence:.2f}] {b.text!r}")

        for target_lang in targets:
            print(f"\n  [{target_lang}]")

            print("    Translating...")
            translated = translate_blocks(blocks, SOURCE_LANGUAGE, target_lang)

            print(f"    Reinserting with LLM layout decisions ({len(blocks)} regions)...")
            out_path = os.path.join(OUTPUT_DIR, f"{name}_{target_lang}.png")
            reinsert_llm_guided(
                original_path=image_path,
                source_blocks=blocks,
                translated_blocks=translated,
                target_language=target_lang,
                output_path=out_path,
                status_callback=lambda msg: print(f"    {msg}"),
            )
            print(f"    -> {out_path}")

        print()

    print("Done.")
    print("Compare:")
    print("  output/test_reinsert/       <- Pillow algorithm")
    print("  output/test_llm_reinsert/   <- LLM-guided layout")


if __name__ == "__main__":
    main()
