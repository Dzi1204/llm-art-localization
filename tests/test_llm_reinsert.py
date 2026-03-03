"""
Mock test: LLM-guided reinsertion

For each text region the LLM receives a cropped image + source/translated text
and returns exact layout instructions (line breaks, font size, abbreviation).
Pillow executes those instructions.

Run:
    python -m tests.test_llm_reinsert --file select-everyone.png --target sk-SK
"""

import sys
import os
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path
from config import AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT, SOURCE_LANGUAGE, TARGET_LANGUAGES
from pipeline.extractor import extract_text, has_localizable_text
from pipeline.translator import translate_blocks
from pipeline.llm_reinsert import reinsert_llm_guided

SOURCE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "source-art")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "output", "test_llm_reinsert")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="select-everyone.png")
    parser.add_argument("--target", default=None)
    args = parser.parse_args()

    targets = [args.target] if args.target else TARGET_LANGUAGES

    if not AZURE_OPENAI_ENDPOINT:
        print("ERROR: AZURE_OPENAI_ENDPOINT not set in .env")
        sys.exit(1)

    image_path = os.path.join(SOURCE_DIR, args.file)
    if not os.path.exists(image_path):
        print(f"ERROR: file not found: {image_path}")
        sys.exit(1)

    name = Path(args.file).stem
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"Image   : {args.file}")
    print(f"Targets : {targets}")
    print(f"Model   : {AZURE_OPENAI_DEPLOYMENT}\n")

    print("Extracting...")
    blocks = extract_text(image_path)
    print(f"  {len(blocks)} blocks extracted\n")
    for b in blocks:
        print(f"  [{b.confidence:.2f}] {b.text!r}")

    for target_lang in targets:
        print(f"\n[{target_lang}]")

        print("  Translating...")
        translated = translate_blocks(blocks, SOURCE_LANGUAGE, target_lang)

        print(f"  Reinserting with LLM layout decisions ({len(blocks)} regions)...")
        out_path = os.path.join(OUTPUT_DIR, f"{name}_{target_lang}.png")
        reinsert_llm_guided(
            original_path=image_path,
            source_blocks=blocks,
            translated_blocks=translated,
            target_language=target_lang,
            output_path=out_path,
            status_callback=print,
        )
        print(f"  → {out_path}")

    print(f"\nDone.")
    print(f"Compare:")
    print(f"  output/test_reinsert/       ← current Pillow algorithm")
    print(f"  output/test_llm_reinsert/   ← LLM-guided layout")


if __name__ == "__main__":
    main()
