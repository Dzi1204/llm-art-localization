"""
Step 6 – Package results for AT Art Review (MATUA ZIP format).

ZIP structure:
  <asset_id>/
    original.<ext>
    localized.<ext>
    text_mapping.json      source + translated text pairs
    metadata.json          language, pipeline info
"""

import json
import zipfile
from pathlib import Path
from typing import List
from dataclasses import asdict

from pipeline.extractor import TextBlock


def create_review_package(
    asset_id: str,
    original_path: str,
    localized_path: str,
    source_blocks: List[TextBlock],
    translated_blocks: List[TextBlock],
    source_language: str,
    target_language: str,
    output_dir: str,
) -> str:
    """
    Creates the MATUA review ZIP and returns the ZIP file path.
    """
    original = Path(original_path)
    localized = Path(localized_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    zip_path = out_dir / f"{asset_id}_{target_language}.zip"

    text_mapping = [
        {"source": src.text, "translated": tgt.text, "page": src.page}
        for src, tgt in zip(source_blocks, translated_blocks)
    ]

    metadata = {
        "asset_id": asset_id,
        "source_language": source_language,
        "target_language": target_language,
        "pipeline": "LLM-MATUA",
        "original_file": original.name,
        "localized_file": localized.name,
        "total_strings": len(source_blocks),
    }

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(original_path, arcname=f"{asset_id}/original{original.suffix}")
        zf.write(localized_path, arcname=f"{asset_id}/localized{localized.suffix}")
        zf.writestr(f"{asset_id}/text_mapping.json", json.dumps(text_mapping, ensure_ascii=False, indent=2))
        zf.writestr(f"{asset_id}/metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))

    return str(zip_path)
