"""
Step 3 – Extract visible text from art assets.

Backends (auto-selected by what is set in .env):
  - Azure AI Document Intelligence  →  when AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT is set
      Auth: API key (if AZURE_DOCUMENT_INTELLIGENCE_KEY is set) or DefaultAzureCredential (Managed Identity / az login)
  - EasyOCR (local, no cloud)       →  when no endpoint is set

Returns a list of TextBlock: { text, bounding_box, page, confidence }
"""

from dataclasses import dataclass
from pathlib import Path
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
    """
    Routes to Azure if an endpoint is configured, otherwise falls back to EasyOCR.
    SVG files are always handled by the XML-based SVG extractor regardless of backend.
    Just set AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT in .env to switch backends.
    """
    if Path(file_path).suffix.lower() == ".svg":
        print("  [OCR backend: SVG XML parser]")
        return _extract_via_svg(file_path)

    if AZURE_ENDPOINT:
        print("  [OCR backend: Azure AI Document Intelligence]")
        return _extract_via_azure(file_path)

    print("  [OCR backend: EasyOCR (local)]")
    return _extract_via_easyocr(file_path, languages=EASYOCR_LANGUAGES)


# ---------------------------------------------------------------------------
# SVG – XML-based text extraction (no OCR needed)
# ---------------------------------------------------------------------------

_SVG_NS = "http://www.w3.org/2000/svg"


def _extract_via_svg(file_path: str) -> List[TextBlock]:
    """
    Parses SVG XML and extracts all <text> and <tspan> elements.
    Bounding boxes are approximated from x/y position and font-size.
    Handles SVGs both with and without the SVG namespace declaration.
    """
    import xml.etree.ElementTree as ET

    tree = ET.parse(file_path)
    root = tree.getroot()

    blocks: List[TextBlock] = []

    for elem in root.iter():
        # Match local tag name regardless of namespace prefix
        local = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if local not in ("text", "tspan"):
            continue

        text = (elem.text or "").strip()
        if not text:
            continue

        try:
            x = float(elem.get("x", 0))
            y = float(elem.get("y", 0))
        except (TypeError, ValueError):
            x, y = 0.0, 0.0

        try:
            font_size = float(elem.get("font-size", 16))
        except (TypeError, ValueError):
            font_size = 16.0

        h = font_size
        w = len(text) * font_size * 0.6

        # Bounding box as polygon: [x0,y0, x1,y0, x1,y1, x0,y1]
        bbox = [x, y - h, x + w, y - h, x + w, y, x, y]

        blocks.append(TextBlock(
            text=text,
            bounding_box=bbox,
            page=1,
            confidence=1.0,
        ))

    return blocks


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
    return merge_overlapping_blocks(blocks)


# ---------------------------------------------------------------------------
# Azure AI Document Intelligence
# Auth: API key if set, otherwise DefaultAzureCredential (Managed Identity / az login)
# ---------------------------------------------------------------------------

def _extract_via_azure(file_path: str) -> List[TextBlock]:
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.core.credentials import AzureKeyCredential
    from azure.identity import DefaultAzureCredential

    if AZURE_KEY:
        credential = AzureKeyCredential(AZURE_KEY)
        print("  [Azure auth: API key]")
    else:
        credential = DefaultAzureCredential()
        print("  [Azure auth: Managed Identity / az login]")

    client = DocumentIntelligenceClient(endpoint=AZURE_ENDPOINT, credential=credential)

    with open(file_path, "rb") as f:
        poller = client.begin_analyze_document(
            "prebuilt-read",
            body=f,
            content_type="application/octet-stream",
        )

    result = poller.result()
    blocks: List[TextBlock] = []

    for page in result.pages:
        for word in page.words:
            if word.confidence < 0.3:
                continue
            blocks.append(
                TextBlock(
                    text=word.content,
                    bounding_box=list(word.polygon or []),
                    page=page.page_number,
                    confidence=word.confidence,
                )
            )
    return merge_overlapping_blocks(blocks)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def has_localizable_text(blocks: List[TextBlock]) -> bool:
    total_words = sum(len(b.text.split()) for b in blocks)
    return total_words >= MIN_WORD_COUNT


# ---------------------------------------------------------------------------
# Post-processing: merge overlapping OCR blocks
# ---------------------------------------------------------------------------

def _bbox_to_rect(bbox: List[float]):
    """Convert polygon bbox to (x0, y0, x1, y1)."""
    xs = bbox[0::2]
    ys = bbox[1::2]
    return min(xs), min(ys), max(xs), max(ys)


def _rects_overlap_horizontally(a, b, y_tolerance_ratio=0.5):
    """
    True if two rects overlap or are on the same horizontal line and close
    enough that they likely belong to the same text run.
    """
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    a_h = ay1 - ay0
    b_h = by1 - by0
    avg_h = (a_h + b_h) / 2
    if avg_h == 0:
        return False

    # Vertical overlap: centres must be within tolerance of each other
    a_cy = (ay0 + ay1) / 2
    b_cy = (by0 + by1) / 2
    if abs(a_cy - b_cy) > avg_h * y_tolerance_ratio:
        return False

    # Horizontal: overlapping or gap smaller than average char height
    gap = max(0, max(ax0, bx0) - min(ax1, bx1))
    return gap < avg_h * 1.5


def merge_overlapping_blocks(blocks: List[TextBlock]) -> List[TextBlock]:
    """
    Merges OCR blocks that overlap or sit on the same line into a single
    block.  This prevents translated fragments from painting over each other
    during reinsertion.
    """
    if not blocks:
        return blocks

    # Build adjacency groups via union-find
    parent = list(range(len(blocks)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    rects = [_bbox_to_rect(b.bounding_box) if len(b.bounding_box) >= 4 else None
             for b in blocks]

    for i in range(len(blocks)):
        if rects[i] is None:
            continue
        for j in range(i + 1, len(blocks)):
            if rects[j] is None:
                continue
            if blocks[i].page != blocks[j].page:
                continue
            if _rects_overlap_horizontally(rects[i], rects[j]):
                union(i, j)

    # Group blocks by their root
    from collections import defaultdict
    groups = defaultdict(list)
    for i in range(len(blocks)):
        groups[find(i)].append(i)

    merged: List[TextBlock] = []
    for indices in groups.values():
        if len(indices) == 1:
            merged.append(blocks[indices[0]])
            continue

        # Sort by x-position (left to right) for correct reading order
        indices.sort(key=lambda i: rects[i][0] if rects[i] else 0)

        all_coords_x = []
        all_coords_y = []
        texts = []
        best_conf = 0.0
        page = blocks[indices[0]].page
        for i in indices:
            b = blocks[i]
            texts.append(b.text)
            best_conf = max(best_conf, b.confidence)
            if len(b.bounding_box) >= 4:
                all_coords_x.extend(b.bounding_box[0::2])
                all_coords_y.extend(b.bounding_box[1::2])

        # Merged bounding box = axis-aligned envelope
        x0, x1 = min(all_coords_x), max(all_coords_x)
        y0, y1 = min(all_coords_y), max(all_coords_y)
        merged_bbox = [x0, y0, x1, y0, x1, y1, x0, y1]

        merged.append(TextBlock(
            text=" ".join(texts),
            bounding_box=merged_bbox,
            page=page,
            confidence=best_conf,
        ))

    return merged
