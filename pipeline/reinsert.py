"""
Step 5 – Reinsert translated text into raster art assets (PNG, JPG, BMP, TIFF).

Visual fidelity rules:
  - Font size   : estimated from source text + bbox; translated text uses the same
                  size if it fits, otherwise shrinks down to the minimum before wrapping.
  - Bold        : title block (largest size) is treated as bold; body text is regular.
  - Colour      : sampled from the *original* image pixels inside the bbox.
  - Underline   : preserved for keyboard-accelerator strings (one char) and hyperlinks
                  (full line), detected from the source text or the '_' OCR marker.
  - Background  : sampled by taking the mode pixel colour in the bbox (text pixels are
                  outnumbered by background pixels).
  - Transparency: JPEG/BMP output composites over white; PNG/TIFF preserves alpha.
"""

import re
from pathlib import Path
from typing import List, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont
from collections import Counter

from pipeline.extractor import TextBlock
from config import AZURE_ENDPOINT as _AZURE_ENDPOINT

# Azure Document Intelligence returns tight bounding boxes (text fills ~85 % of height).
# EasyOCR adds generous vertical padding (text fills ~35 % of height).
_BBOX_HEIGHT_RATIO_AZURE = 0.85
_BBOX_HEIGHT_RATIO_EASYOCR = 0.35


# ---------------------------------------------------------------------------
# Non-translatable text filter
# ---------------------------------------------------------------------------

_NON_TRANSLATABLE = re.compile(
    r"""
    ^(
        [0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}  # GUID
        | [\w.+\-]+@[\w.\-]+\.\w+                                                        # email
        | '?[\d]{1,3}\.[\d]{1,3}\.[\d]{1,3}\.[\d]{1,3}"?                               # IP address
        | [\d\s.,\-+%:]+                                                                  # numbers / dates
        | (CN|DC|OU|O|C|L|ST|G|SN)=.+                                                   # LDAP / AD path
        | =\w.*                                                                           # AD shorthand
        | [\w][\w\-]*\.[\w\-]+(\.[\w\-]+)+                                               # domain paths
    )$
    """,
    re.VERBOSE,
)


def _is_non_translatable(text: str) -> bool:
    return bool(_NON_TRANSLATABLE.match(text.strip()))


# ---------------------------------------------------------------------------
# Public reinsertion entry point
# ---------------------------------------------------------------------------

def reinsert_raster(
    original_path: str,
    source_blocks: List[TextBlock],
    translated_blocks: List[TextBlock],
    output_path: str,
    layout_hints: Optional[list] = None,
    ocr_backend: str = "auto",
) -> str:
    """
    Paints translated text over each source text region.
    Preserves font size, bold, colour, underline, and trailing dots.
    ocr_backend: "azure", "easyocr", or "auto" (detects from config).
    Returns output_path.
    """
    if ocr_backend == "auto":
        bbox_ratio = _BBOX_HEIGHT_RATIO_AZURE if _AZURE_ENDPOINT else _BBOX_HEIGHT_RATIO_EASYOCR
    elif ocr_backend == "azure":
        bbox_ratio = _BBOX_HEIGHT_RATIO_AZURE
    else:
        bbox_ratio = _BBOX_HEIGHT_RATIO_EASYOCR

    _pil_orig = Image.open(original_path)
    _orig_mode = _pil_orig.mode
    img = _pil_orig.convert("RGBA")
    img_orig = img.copy()          # frozen original — used for all colour sampling
    draw = ImageDraw.Draw(img)

    # ------------------------------------------------------------------
    # Pass 1: estimate source font size for every block so we can
    # normalise body text to a consistent size (OCR bbox heights vary).
    # ------------------------------------------------------------------
    n = len(source_blocks)
    rects: list = [None] * n
    raw_sizes: list = [None] * n

    for i, src in enumerate(source_blocks):
        if len(src.bounding_box) < 4 or _is_non_translatable(src.text):
            continue
        rects[i] = _polygon_to_rect(src.bounding_box)
        raw_sizes[i] = _estimate_source_font_size(draw, src.text, rects[i],
                                                   bbox_ratio=bbox_ratio)

    valid = [s for s in raw_sizes if s is not None]
    if len(valid) >= 2:
        title_size = max(valid)
        body_cands = [s for s in valid if s < title_size]
        body_size  = max(set(body_cands), key=body_cands.count) if body_cands else title_size
    elif valid:
        title_size = body_size = valid[0]
    else:
        title_size = body_size = 13

    sizes: list = []
    for s in raw_sizes:
        if s is None:
            sizes.append(None)
        elif s >= title_size and title_size > body_size:
            sizes.append(s)         # title — keep its own size
        else:
            sizes.append(body_size) # body  — normalise to mode size

    # ------------------------------------------------------------------
    # Pass 2: render each block
    # ------------------------------------------------------------------
    for i, (src, tgt) in enumerate(zip(source_blocks, translated_blocks)):
        rect = rects[i]
        if rect is None:
            continue

        source_size = sizes[i] or body_size
        is_bold     = source_size == title_size and title_size > body_size

        # LLM layout hints (optional, from layout_refiner)
        hint = layout_hints[i] if layout_hints and i < len(layout_hints) else None
        if hint:
            is_bold  = getattr(hint, 'bold',      is_bold)
            align    = getattr(hint, 'align',     'left')
            link_text = getattr(hint, 'link_text', None)
        else:
            align     = 'left'
            link_text = None

        # Underline: OCR marks accelerators with '_'; full underline = hyperlink
        has_accel_underline = '_' in src.text
        is_hyperlink        = (hint and getattr(hint, 'underline', False)) and not has_accel_underline

        # Sample colours from the *unmodified* original image
        bg_color = _sample_background(img_orig, rect)
        fg_color = _sample_foreground(img_orig, rect, bg_color)

        # Fill rect — 3 px padding, plus extra rightward extension for blocks
        # whose source text had trailing dots (OCR often clips the "..." just
        # outside its bounding box, leaving stray dots visible).
        has_trailing_dots = src.text.rstrip().endswith(('.', '_', '…'))
        right_ext = int(source_size * 2) if has_trailing_dots else 3
        fill_rect = (
            max(0,          rect[0] - 3),
            max(0,          rect[1] - 3),
            min(img.width,  rect[2] + right_ext),
            min(img.height, rect[3] + 3),
        )
        draw.rectangle(fill_rect, fill=bg_color[:3] + (255,))

        # Fit translated text: try source size first, shrink until it fits
        font, lines = _fit_text(draw, tgt.text, rect,
                                default_size=source_size, bold=is_bold)

        # Draw text
        box_w      = rect[2] - rect[0]
        box_h      = rect[3] - rect[1]
        line_h     = draw.textbbox((0, 0), "Ag", font=font)[3] + 1
        total_h    = line_h * len(lines)
        y          = rect[1] + max(0, (box_h - total_h) / 2)

        for line in lines:
            line_w = draw.textbbox((0, 0), line, font=font)[2]
            if align == 'center':
                x = rect[0] + max(0, (box_w - line_w) / 2)
            elif align == 'right':
                x = rect[0] + max(0, box_w - line_w - 2)
            else:
                x = rect[0] + 2

            if link_text and link_text in line:
                _draw_link_line(draw, line, link_text, x, y, font, fg_color)
            else:
                draw.text((x, y), line, fill=fg_color, font=font)

            # Underline: keyboard accelerator = first char only; hyperlink = full line
            if (has_accel_underline or is_hyperlink) and line:
                ul_w = (draw.textbbox((0, 0), line[0], font=font)[2]
                        if has_accel_underline else line_w)
                ul_y = int(y + draw.textbbox((0, 0), "Ag", font=font)[3]) + 1
                draw.line([(int(x), ul_y), (int(x) + ul_w, ul_y)],
                          fill=fg_color, width=1)

            y += line_h

    _save_image(img, _orig_mode, output_path)
    return output_path


# ---------------------------------------------------------------------------
# SVG reinsertion (unchanged)
# ---------------------------------------------------------------------------

def reinsert_svg(
    original_path: str,
    source_blocks: List[TextBlock],
    translated_blocks: List[TextBlock],
    output_path: str,
) -> str:
    """Replaces text in SVG <text>/<tspan> elements. Preserves all structure."""
    import xml.etree.ElementTree as ET

    _SVG_NS = "http://www.w3.org/2000/svg"
    ET.register_namespace("",         _SVG_NS)
    ET.register_namespace("xlink",    "http://www.w3.org/1999/xlink")
    ET.register_namespace("dc",       "http://purl.org/dc/elements/1.1/")
    ET.register_namespace("cc",       "http://creativecommons.org/ns#")
    ET.register_namespace("rdf",      "http://www.w3.org/1999/02/22-rdf-syntax-ns#")
    ET.register_namespace("svg",      _SVG_NS)
    ET.register_namespace("sodipodi", "http://sodipodi.sourceforge.net/DTD/sodipodi-0.0.dtd")
    ET.register_namespace("inkscape", "http://www.inkscape.org/namespaces/inkscape")

    translation_map: dict = {}
    for src, tgt in zip(source_blocks, translated_blocks):
        s = src.text.strip()
        if s and s not in translation_map:
            translation_map[s] = tgt.text

    tree = ET.parse(original_path)
    for elem in tree.getroot().iter():
        local = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if local in ("text", "tspan"):
            orig = (elem.text or "").strip()
            if orig in translation_map:
                elem.text = translation_map[orig]

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tree.write(str(out), encoding="utf-8", xml_declaration=True)
    return str(out)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_HYPERLINK_COLOR = (0, 102, 204, 255)


def _draw_link_line(
    draw: ImageDraw.ImageDraw,
    line: str,
    link_text: str,
    x: float,
    y: float,
    font: ImageFont.FreeTypeFont,
    fg_color: Tuple,
) -> None:
    """Renders a line with link_text in blue + underlined."""
    idx = line.find(link_text)
    if idx < 0:
        draw.text((x, y), line, fill=fg_color, font=font)
        return

    cx = x
    before = line[:idx]
    link   = line[idx: idx + len(link_text)]
    after  = line[idx + len(link_text):]

    if before:
        draw.text((cx, y), before, fill=fg_color, font=font)
        cx += draw.textbbox((0, 0), before, font=font)[2]

    draw.text((cx, y), link, fill=_HYPERLINK_COLOR, font=font)
    lw   = draw.textbbox((0, 0), link, font=font)[2]
    ul_y = int(y + draw.textbbox((0, 0), link, font=font)[3]) + 1
    draw.line([(int(cx), ul_y), (int(cx) + lw, ul_y)], fill=_HYPERLINK_COLOR, width=1)
    cx += lw

    if after:
        draw.text((cx, y), after, fill=fg_color, font=font)


def _save_image(img: Image.Image, orig_mode: str, path: str) -> None:
    """
    Save processed RGBA image, preserving the source format.
    - JPEG/BMP : composites over white (no alpha support).
    - PNG/TIFF with original alpha: saves as RGBA.
    - Everything else: drops working alpha (source was fully opaque).
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    ext = Path(path).suffix.lower()
    if ext in ('.jpg', '.jpeg'):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        bg.save(path, quality=95)
    elif ext == '.bmp':
        img.convert("RGB").save(path)
    elif orig_mode in ('RGBA', 'LA', 'PA'):
        img.save(path)          # preserve source alpha
    else:
        img.convert("RGB").save(path)


def _load_font(size: int = 14, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Load Segoe UI or Arial at the given size, with optional bold."""
    if bold:
        candidates = (
            "segoeuib.ttf", "C:/Windows/Fonts/segoeuib.ttf",
            "arialbd.ttf",  "C:/Windows/Fonts/arialbd.ttf",
        )
    else:
        candidates = (
            "segoeui.ttf", "C:/Windows/Fonts/segoeui.ttf",
            "arial.ttf",   "C:/Windows/Fonts/arial.ttf",
        )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _estimate_source_font_size(
    draw: ImageDraw.ImageDraw,
    source_text: str,
    rect: Tuple[float, float, float, float],
    min_size: int = 7,
    max_size: int = 36,
    bbox_ratio: float = 0.35,
) -> int:
    """
    Returns the largest font size where source_text fits the bbox width,
    capped by bbox_ratio * bbox_height to avoid overshooting.
    """
    box_w = max(1, rect[2] - rect[0])
    box_h = max(1, rect[3] - rect[1])
    ceil  = max(min_size, int(box_h * bbox_ratio))
    cap   = min(max_size, ceil)

    best = min_size
    for size in range(min_size, cap + 1):
        font = _load_font(size)
        if draw.textbbox((0, 0), source_text, font=font)[2] <= box_w:
            best = size
        else:
            break
    return best


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    rect: Tuple[float, float, float, float],
    default_size: int = 13,
    min_size: int = 7,
    bold: bool = False,
) -> Tuple[ImageFont.FreeTypeFont, List[str]]:
    """
    Tries to fit text on a single line starting at default_size, shrinking
    down to min_size.  Only wraps if even min_size is too wide.
    """
    max_w = max(1, rect[2] - rect[0])
    for size in range(default_size, min_size - 1, -1):
        font = _load_font(size, bold=bold)
        if draw.textbbox((0, 0), text, font=font)[2] <= max_w:
            return font, [text]

    font  = _load_font(min_size, bold=bold)
    lines = _wrap_text(draw, text, font, max_w)
    return font, lines


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: float,
) -> List[str]:
    words = text.split()
    if not words:
        return [text]
    lines, current = [], ""
    for word in words:
        candidate = (current + " " + word).strip()
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [text]


def _polygon_to_rect(polygon: List[float]) -> Tuple[float, float, float, float]:
    xs = polygon[0::2]
    ys = polygon[1::2]
    return (min(xs), min(ys), max(xs), max(ys))


def _sample_background(img: Image.Image, rect: Tuple) -> Tuple:
    """Mode colour inside the bbox (background pixels outnumber text pixels)."""
    x0, y0, x1, y1 = [int(v) for v in rect]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(img.width, x1), min(img.height, y1)
    if x1 <= x0 or y1 <= y0:
        return (255, 255, 255, 255)

    region = img.crop((x0, y0, x1, y1)).convert("RGBA")
    w, h   = region.width, region.height
    step   = max(1, min(w, h) // 40)
    counts: Counter = Counter()
    for px in range(0, w, step):
        for py in range(0, h, step):
            c = region.getpixel((px, py))
            q = (c[0] // 8 * 8, c[1] // 8 * 8, c[2] // 8 * 8)
            counts[q] += 1

    if not counts:
        return (255, 255, 255, 255)
    r, g, b = counts.most_common(1)[0][0]
    return (r, g, b, 255)


def _sample_foreground(img: Image.Image, rect: Tuple, bg_color: Tuple) -> Tuple:
    """
    Detects text colour by averaging pixels that contrast strongly with the
    background.  Near-black and near-white are snapped to pure values to
    remove JPEG/compression tinting; real grays and colours are kept as-is.
    """
    x0, y0, x1, y1 = [int(v) for v in rect]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(img.width, x1), min(img.height, y1)
    bg_lum  = 0.299 * bg_color[0] + 0.587 * bg_color[1] + 0.114 * bg_color[2]
    default = (255, 255, 255, 255) if bg_lum < 128 else (0, 0, 0, 255)

    if x1 <= x0 or y1 <= y0:
        return default

    region   = img.crop((x0, y0, x1, y1)).convert("RGBA")
    w, h     = region.width, region.height
    margin_x = max(1, w // 4)
    margin_y = max(1, h // 4)
    if w - 2 * margin_x < 2 or h - 2 * margin_y < 2:
        return default
    centre = region.crop((margin_x, margin_y, w - margin_x, h - margin_y))

    candidates = []
    for px in range(centre.width):
        for py in range(centre.height):
            c   = centre.getpixel((px, py))
            lum = 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]
            if abs(lum - bg_lum) > 60:
                candidates.append(c[:3])

    if not candidates:
        return default

    n     = len(candidates)
    avg_r = sum(c[0] for c in candidates) // n
    avg_g = sum(c[1] for c in candidates) // n
    avg_b = sum(c[2] for c in candidates) // n

    avg_lum    = 0.299 * avg_r + 0.587 * avg_g + 0.114 * avg_b
    saturation = max(avg_r, avg_g, avg_b) - min(avg_r, avg_g, avg_b)

    if saturation < 40:
        # Neutral grey — snap to pure black/white to remove antialiasing tint.
        # avg_lum < 128: antialiased black text (mixed with light bg) → pure black.
        # avg_lum > 192: antialiased white text (mixed with dark bg) → pure white.
        # 128‥192: genuine mid-gray (disabled/secondary text) → keep as-is.
        if avg_lum < 128:
            return (0, 0, 0, 255)
        if avg_lum > 192:
            return (255, 255, 255, 255)
        return (avg_r, avg_g, avg_b, 255)  # real grey (disabled text, etc.)

    # Genuinely coloured text (hyperlinks, warnings, etc.) — keep the colour
    return (avg_r, avg_g, avg_b, 255)
