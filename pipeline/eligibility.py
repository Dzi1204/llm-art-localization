"""
Step 1 – Confirm content eligibility.
Checks whether an asset is art-type and suitable for the LLM localization pipeline.
"""

import os
from pathlib import Path
from config import SUPPORTED_EXTENSIONS


def check_eligibility(file_path: str) -> dict:
    """
    Returns a dict with:
      - eligible (bool)
      - reason (str)
      - asset_type (str): 'raster', 'svg', 'pdf', or 'unknown'
    """
    path = Path(file_path)

    if not path.exists():
        return {"eligible": False, "reason": "File not found", "asset_type": "unknown"}

    ext = path.suffix.lower()

    if ext in SUPPORTED_EXTENSIONS:
        return {"eligible": True, "reason": f"Supported raster/PDF type: {ext}", "asset_type": "raster" if ext != ".pdf" else "pdf"}

    return {
        "eligible": False,
        "reason": f"Unsupported file type: {ext}",
        "asset_type": "unknown",
    }
