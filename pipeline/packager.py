"""
Step 6 – Package results for AT Art Review (MATUA ZIP format).

ZIP structure:
  <asset_id>/
    original.<ext>
    localized.<ext>
    text_mapping.json      source + translated text pairs with QE scores
    metadata.json          language, pipeline info, QE summary
"""

import json
import zipfile
from pathlib import Path
from typing import List, Optional

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
    qe_results=None,  # optional List[QEResult]
) -> str:
    """
    Creates the MATUA review ZIP and returns the ZIP file path.
    If qe_results is provided, QE scores and flagged status are included
    in text_mapping.json and summarised in metadata.json.
    """
    original = Path(original_path)
    localized = Path(localized_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    zip_path = out_dir / f"{asset_id}_{target_language}.zip"

    # Build a score lookup keyed by (source_text, translated_text) position
    qe_by_index = {}
    if qe_results:
        for i, r in enumerate(qe_results):
            qe_by_index[i] = r

    text_mapping = []
    for i, (src, tgt) in enumerate(zip(source_blocks, translated_blocks)):
        entry = {
            "source": src.text,
            "translated": tgt.text,
            "page": src.page,
        }
        if i in qe_by_index:
            r = qe_by_index[i]
            entry["qe_score"] = round(r.score, 2) if r.score is not None else None
            entry["flagged"] = r.flagged
        text_mapping.append(entry)

    # QE summary for metadata
    qe_summary = None
    if qe_results:
        scored = [r for r in qe_results if r.score is not None]
        flagged = [r for r in qe_results if r.flagged]
        qe_summary = {
            "scored": len(scored),
            "flagged": len(flagged),
            "not_scored": len(qe_results) - len(scored),
            "flagged_strings": [
                {"source": r.source, "translated": r.translated, "qe_score": round(r.score, 2)}
                for r in flagged
            ],
        }

    metadata = {
        "asset_id": asset_id,
        "source_language": source_language,
        "target_language": target_language,
        "pipeline": "LLM-MATUA",
        "original_file": original.name,
        "localized_file": localized.name,
        "total_strings": len(source_blocks),
        "qe": qe_summary,
    }

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(original_path, arcname=f"{asset_id}/original{original.suffix}")
        zf.write(localized_path, arcname=f"{asset_id}/localized{localized.suffix}")
        zf.writestr(f"{asset_id}/text_mapping.json", json.dumps(text_mapping, ensure_ascii=False, indent=2))
        zf.writestr(f"{asset_id}/metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))

    return str(zip_path)
