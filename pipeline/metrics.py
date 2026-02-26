"""
Step 10 – Track pipeline metrics aligned with MATUA.
Logs per-asset results to a JSONL file for later analysis.
"""

import json
from datetime import datetime, timezone
from pathlib import Path


METRICS_FILE = Path("output/metrics.jsonl")


def log_result(
    asset_id: str,
    source_language: str,
    target_language: str,
    total_strings: int,
    review_outcome: str,   # "pass", "fail", "escalated", "noloc"
    escalation_reason: str = "",
    notes: str = "",
):
    METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "asset_id": asset_id,
        "source_language": source_language,
        "target_language": target_language,
        "total_strings": total_strings,
        "review_outcome": review_outcome,
        "escalation_reason": escalation_reason,
        "notes": notes,
    }
    with open(METRICS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
