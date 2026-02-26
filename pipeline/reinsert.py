"""
Step 5 – Reinsert translated text into art assets.

- Raster images (PNG/JPG): uses Pillow to paint translated text over original bounding boxes
- SVG: replaces text content directly in the XML tree
"""

from pathlib import Path
from typing import List, Tuple
from PIL import Image, ImageDraw, ImageFont

from pipeline.extractor import TextBlock


# ---------------------------------------------------------------------------
# Raster images (PNG, JPG, BMP, TIFF)
# ---------------------------------------------------------------------------

def reinsert_raster(
    original_path: str,
    source_blocks: List[TextBlock],
    translated_blocks: List[TextBlock],
    output_path: str,
) -> str:
    """
    Paints translated text over the original image.
    Covers original text region with a background fill then draws translated text.
    Returns the output path.
    """
    img = Image.open(original_path).convert("RGBA")
    draw = ImageDraw.Draw(img)

    font = _load_font(size=14)

    for src_block, tgt_block in zip(source_blocks, translated_blocks):
        bbox = src_block.bounding_box
        if len(bbox) < 4:
            continue

        rect = _polygon_to_rect(bbox)
        bg_color = _sample_background(img, rect)
        draw.rectangle(rect, fill=bg_color)

        x, y = rect[0], rect[1]
        draw.text((x, y), tgt_block.text, fill=(0, 0, 0, 255), font=font)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    img = img.convert("RGB")
    img.save(str(out))
    return str(out)


def _polygon_to_rect(polygon: List[float]) -> Tuple[float, float, float, float]:
    """Converts a flat polygon list to (x_min, y_min, x_max, y_max)."""
    xs = polygon[0::2]
    ys = polygon[1::2]
    return (min(xs), min(ys), max(xs), max(ys))


def _sample_background(img: Image.Image, rect: Tuple) -> Tuple:
    """Samples the dominant edge color of the bounding region as background fill."""
    x0, y0, x1, y1 = [int(v) for v in rect]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(img.width, x1), min(img.height, y1)

    if x1 <= x0 or y1 <= y0:
        return (255, 255, 255, 255)

    region = img.crop((x0, y0, x1, y1))
    # Use top-left pixel as a simple background estimate
    pixel = region.getpixel((0, 0))
    if isinstance(pixel, int):
        return (pixel, pixel, pixel, 255)
    if len(pixel) == 3:
        return (*pixel, 255)
    return pixel


def _load_font(size: int = 14) -> ImageFont.FreeTypeFont:
    try:
        # Try to load a system font that supports broad Unicode
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        try:
            return ImageFont.truetype("C:/Windows/Fonts/arial.ttf", size)
        except Exception:
            return ImageFont.load_default()


# ---------------------------------------------------------------------------
# SVG
# ---------------------------------------------------------------------------

def reinsert_svg(
    original_path: str,
    source_blocks: List[TextBlock],
    translated_blocks: List[TextBlock],
    output_path: str,
) -> str:
    """
    Replaces text content in SVG XML elements identified by element_id.
    Returns the output path.
    """
    from lxml import etree

    tree = etree.parse(original_path)
    root = tree.getroot()
    SVG_NS = "http://www.w3.org/2000/svg"

    id_to_translation = {
        src.element_id: tgt.text
        for src, tgt in zip(source_blocks, translated_blocks)
        if src.element_id
    }

    for elem in root.iter(f"{{{SVG_NS}}}text", f"{{{SVG_NS}}}tspan"):
        elem_id = elem.get("id")
        if elem_id and elem_id in id_to_translation:
            elem.text = id_to_translation[elem_id]

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tree.write(str(out), xml_declaration=True, encoding="utf-8")
    return str(out)
