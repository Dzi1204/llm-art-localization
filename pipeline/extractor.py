"""
Step 3 – Extract visible text from art assets.

Backends (auto-selected):
  - Azure AI Document Intelligence  →  when AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT + KEY are set in .env
  - EasyOCR (local, no cloud)       →  fallback when Azure creds are missing

Returns a list of TextBlock: { text, bounding_box, page, confidence }
"""

from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional

from config import AZURE_ENDPOINT, AZURE_KEY, MIN_WORD_COUNT, EASYOCR_LANGUAGES


@dataclass
class TextBlock:
    text: str
    bounding_box: List[float]   # [x0,y0, x1,y1, x2,y2, x3,y3] in pixels
    page: int = 1
    confidence: float = 1.0
    element_id: Optional[str] = None


def extract_text(file_path: str) -> List[TextBlock]:
    """Routes to the correct extractor based on available credentials."""
    if AZURE_ENDPOINT and AZURE_KEY:
        print("  [OCR backend: Azure AI Document Intelligence]")
        return _extract_via_azure(file_path)

    print("  [OCR backend: EasyOCR (local)]")
    return _extract_via_easyocr(file_path, languages=EASYOCR_LANGUAGES)


# ---------------------------------------------------------------------------
# EasyOCR – local, no cloud credentials required
# ---------------------------------------------------------------------------

_easyocr_reader = None

def _get_easyocr_reader(languages: List[str]):
    import easyocr
    global _easyocr_reader
    if _easyocr_reader is None:
        print(f"  [EasyOCR loading models for: {languages}] (first run may take a minute...)")
        _easyocr_reader = easyocr.Reader(languages, gpu=False)
    return _easyocr_reader


def _extract_via_easyocr(file_path: str, languages: List[str] = None) -> List[TextBlock]:
    if languages is None:
        languages = ["en"]

    reader = _get_easyocr_reader(languages)
    results = reader.readtext(file_path)

    blocks: List[TextBlock] = []
    for (bbox_points, text, confidence) in results:
        if not text.strip() or confidence < 0.2:
            continue
        flat = [coord for point in bbox_points for coord in point]
        blocks.append(
            TextBlock(
                text=text.strip(),
                bounding_box=flat,
                page=1,
                confidence=confidence,
            )
        )
    return blocks


# ---------------------------------------------------------------------------
# Azure AI Document Intelligence (raster images + PDFs)
# ---------------------------------------------------------------------------

def _extract_via_azure(file_path: str) -> List[TextBlock]:
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.core.credentials import AzureKeyCredential

    client = DocumentIntelligenceClient(
        endpoint=AZURE_ENDPOINT,
        credential=AzureKeyCredential(AZURE_KEY),
    )

    with open(file_path, "rb") as f:
        poller = client.begin_analyze_document(
            "prebuilt-read",
            analyze_request=f,
            content_type="application/octet-stream",
        )

    result = poller.result()
    blocks: List[TextBlock] = []

    for page in result.pages:
        page_num = page.page_number
        for word in page.words:
            if word.confidence < 0.3:
                continue
            polygon = word.polygon or []
            blocks.append(
                TextBlock(
                    text=word.content,
                    bounding_box=list(polygon),
                    page=page_num,
                    confidence=word.confidence,
                )
            )
    return blocks


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def has_localizable_text(blocks: List[TextBlock]) -> bool:
    total_words = sum(len(b.text.split()) for b in blocks)
    return total_words >= MIN_WORD_COUNT
