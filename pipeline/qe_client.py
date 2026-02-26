"""
QE Service client — scores translation quality per string.

Calls the LLMQualityEstimation service (dev) sync endpoint:
  POST {QE_ENDPOINT}/api/{culture}/calculate-llm-qe/sync

Auth: Bearer token set in QE_BEARER_TOKEN in .env (manually obtained).

Returns a list of QEResult: { id, source, translated, score, flagged }
"""

import json
import uuid
import requests
from dataclasses import dataclass
from typing import List, Optional

from config import QE_ENDPOINT, QE_BEARER_TOKEN, QE_SCORE_THRESHOLD
from pipeline.extractor import TextBlock


# Maps our BCP-47 culture tags to the codes the QE service recognises.
# QE uses lowercase short codes for single-language cultures (it, de, …)
# and lowercase full codes for region-specific ones (pt-br, zh-cn, …).
_QE_CULTURE_MAP = {
    "it-IT": "it",
    "de-DE": "de",
    "es-ES": "es",
    "fr-FR": "fr",
    "ja-JP": "ja",
    "ko-KR": "ko",
    "sk-SK": "sk",
    "cs-CZ": "cs",
    "pl-PL": "pl",
    "ro-RO": "ro",
    "lv-LV": "lv",
    "nl-NL": "nl",
    "da-DK": "da",
    "pt-BR": "pt-br",
    "zh-CN": "zh-cn",
    "zh-TW": "zh-tw",
}


@dataclass
class QEResult:
    id: str
    source: str
    translated: str
    score: Optional[float]
    flagged: bool


def score_translations(
    source_blocks: List[TextBlock],
    translated_blocks: List[TextBlock],
    target_language: str,
    timeout: int = 30,
) -> List[QEResult]:
    """
    Sends source + translated string pairs to the QE service.
    Returns a QEResult per string with score and flagged status.
    """
    if not QE_ENDPOINT or not QE_BEARER_TOKEN:
        raise EnvironmentError(
            "QE_ENDPOINT and QE_BEARER_TOKEN must be set in .env to use QE scoring."
        )

    # Map our culture tag (e.g. it-IT) to the QE service's code (e.g. it)
    culture = _QE_CULTURE_MAP.get(target_language, target_language.lower())

    url = f"{QE_ENDPOINT.rstrip('/')}/api/{culture}/calculate-llm-qe/sync"

    # IDs must be valid GUIDs — the service rejects plain integers
    item_ids = [str(uuid.uuid4()) for _ in source_blocks]

    items = [
        {
            "Id": item_id,
            "SourceString": src.text,
            "TargetString": tgt.text,
            "Comments": "",
            "AdditionalInformation": "",
        }
        for item_id, src, tgt in zip(item_ids, source_blocks, translated_blocks)
    ]

    payload = {
        "Items": items,
        "TimeoutInSeconds": timeout,
    }

    headers = {
        "Authorization": f"Bearer {QE_BEARER_TOKEN}",
        "Content-Type": "application/json",
    }

    response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=timeout)
    response.raise_for_status()

    # Service returns LLMQEScore as 0-100; normalise to 0.0-1.0
    response_items = {
        item["Id"]: item["LLMQEScore"] / 100.0
        for item in response.json().get("Items", [])
        if item.get("LLMQEScore") is not None
    }

    results = []
    for item_id, src, tgt in zip(item_ids, source_blocks, translated_blocks):
        score = response_items.get(item_id)
        results.append(
            QEResult(
                id=item_id,
                source=src.text,
                translated=tgt.text,
                score=score,
                flagged=score is not None and score < QE_SCORE_THRESHOLD,
            )
        )

    return results


def print_qe_report(results: List[QEResult]):
    """Prints a summary of QE scores to the console."""
    flagged = [r for r in results if r.flagged]
    ok = [r for r in results if not r.flagged]

    print(f"\n  QE Results -- {len(results)} strings scored")
    print(f"  Threshold : {QE_SCORE_THRESHOLD}")
    print(f"  OK        : {len(ok)}")
    print(f"  Flagged   : {len(flagged)}\n")

    for r in results:
        flag = "  FLAG" if r.flagged else ""
        score_str = f"{r.score:.2f}" if r.score is not None else "N/A"
        print(f"  [{score_str}]{flag}")
        print(f"    EN: {r.source!r}")
        print(f"    IT: {r.translated!r}")
