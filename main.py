"""
LLM-MATUA Pipeline – main entry point.

Usage:
    python main.py --input <image_or_folder> --source en-US --target fr-FR
    python main.py --input image.png --source en-US --target ar-SA
"""

import argparse
import os
import shutil
from pathlib import Path

NO_LOC_DIR = Path(__file__).parent / "output" / "no-loc"

from pipeline.eligibility import check_eligibility
from pipeline.extractor import extract_text, has_localizable_text
from pipeline.translator import translate_blocks
from pipeline.reinsert import reinsert_raster, reinsert_svg
from pipeline.packager import create_review_package
from pipeline.metrics import log_result
from config import TARGET_LANGUAGES


def _save_noloc(file_path: str) -> None:
    """Copy a NoLoc asset into data/no-loc/ for reference."""
    NO_LOC_DIR.mkdir(parents=True, exist_ok=True)
    dest = NO_LOC_DIR / Path(file_path).name
    if not dest.exists():
        shutil.copy2(file_path, dest)
        print(f"  Saved to no-loc: {dest}")


def process_asset(
    file_path: str,
    source_language: str,
    target_language: str,
    output_dir: str = "output",
    glossary: dict = None,
) -> dict:
    asset_id = Path(file_path).stem
    print(f"\n[{asset_id}]")

    # Step 1 – Eligibility
    eligibility = check_eligibility(file_path)
    if not eligibility["eligible"]:
        print(f"  SKIP – {eligibility['reason']}")
        _save_noloc(file_path)
        log_result(asset_id, source_language, target_language, 0, "noloc", eligibility["reason"])
        return {"asset_id": asset_id, "status": "noloc"}

    # Step 3 – Extract text
    print(f"  Extracting text...")
    blocks = extract_text(file_path)
    print(f"  Extracted {len(blocks)} word(s)")

    if not has_localizable_text(blocks):
        print(f"  SKIP – insufficient text for localization (NoLoc)")
        _save_noloc(file_path)
        log_result(asset_id, source_language, target_language, len(blocks), "noloc", "insufficient text")
        return {"asset_id": asset_id, "status": "noloc", "word_count": len(blocks)}

    # Step 4 – Translate
    print(f"  Translating {len(blocks)} strings ({source_language} → {target_language})...")
    translated = translate_blocks(blocks, source_language, target_language, glossary)

    # Step 5 – Reinsert
    print(f"  Reinserting translated text...")
    localized_dir = Path(output_dir) / "localized"
    localized_dir.mkdir(parents=True, exist_ok=True)
    localized_path = str(localized_dir / Path(file_path).name)

    asset_type = eligibility["asset_type"]
    if asset_type == "svg":
        reinsert_svg(file_path, blocks, translated, localized_path.replace(".png", ".svg"))
    else:
        reinsert_raster(file_path, blocks, translated, localized_path)

    # Step 6 – Package for MATUA review
    print(f"  Creating review package...")
    zip_path = create_review_package(
        asset_id=asset_id,
        original_path=file_path,
        localized_path=localized_path,
        source_blocks=blocks,
        translated_blocks=translated,
        source_language=source_language,
        target_language=target_language,
        output_dir=str(Path(output_dir) / "packages"),
    )
    print(f"  Package ready: {zip_path}")

    log_result(asset_id, source_language, target_language, len(blocks), "pending_review")

    return {
        "asset_id": asset_id,
        "status": "packaged",
        "word_count": len(blocks),
        "zip_path": zip_path,
    }


def run(input_path: str, source_language: str, target_language: str, output_dir: str):
    path = Path(input_path)
    files = []

    if path.is_dir():
        for ext in ("*.png", "*.jpg", "*.jpeg", "*.pdf", "*.svg"):
            files.extend(path.glob(ext))
    elif path.is_file():
        files = [path]
    else:
        print(f"ERROR: {input_path} not found")
        return

    print(f"Processing {len(files)} asset(s) → {target_language}")
    results = []
    for f in files:
        result = process_asset(str(f), source_language, target_language, output_dir)
        results.append(result)

    packaged = sum(1 for r in results if r["status"] == "packaged")
    skipped = sum(1 for r in results if r["status"] == "noloc")
    print(f"\nDone. {packaged} packaged, {skipped} skipped (NoLoc).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LLM-MATUA Art Localization Pipeline")
    parser.add_argument("--input", required=True, help="Image file or folder path")
    parser.add_argument("--source", default="en-US", help="Source language code")
    parser.add_argument("--target", nargs="+", default=TARGET_LANGUAGES, help="Target language code(s), e.g. it-IT de-DE")
    parser.add_argument("--output", default="output", help="Output directory")
    args = parser.parse_args()

    run(args.input, args.source, args.target, args.output)
