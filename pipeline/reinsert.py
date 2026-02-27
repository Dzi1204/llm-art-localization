"""
Step 5 – Reinsert translated text into raster art assets (PNG, JPG, BMP, TIFF).

Uses Pillow to paint translated text over original bounding boxes.
Font size is auto-fitted to the bounding box and text is wrapped to stay within bounds.

# LLM OPPORTUNITY (Phase 2+):
# Before reinsertion, an LLM layout pass could provide per-string rendering hints:
#   - text direction (ltr / rtl) for Arabic, Hebrew, etc.
#   - suggested font size ratio relative to source text
#   - preferred line break points for long translations
#   - cultural flags (e.g. number format, gendered forms)
# Pillow would then execute based on those hints rather than guessing.
# See translator.py for the existing Azure AI Foundry integration pattern.
"""

import re
from pathlib import Path
from typing import List, Tuple
from PIL import Image, ImageDraw, ImageFont

from pipeline.extractor import TextBlock


# Patterns for strings that are never translatable — skip reinsertion for these
# so we don't paint over perfectly good original pixels.
_NON_TRANSLATABLE = re.compile(
    r"""
    ^(
        [0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}  # GUID
        | [\w.+\-]+@[\w.\-]+\.\w+                                                        # email
        | '?[\d]{1,3}\.[\d]{1,3}\.[\d]{1,3}\.[\d]{1,3}"?                               # IP address
        | [\d\s.,\-+%:]+                                                                  # numbers / dates
    )$
    """,
    re.VERBOSE,
)


def _is_non_translatable(text: str) -> bool:
    """Returns True for strings that should never be touched by reinsertion."""
    return bool(_NON_TRANSLATABLE.match(text.strip()))


def reinsert_raster(
    original_path: str,
    source_blocks: List[TextBlock],
    translated_blocks: List[TextBlock],
    output_path: str,
) -> str:
    """
    Covers each source text region with a background fill then draws translated text.
    Font size is auto-scaled to fit the bounding box height.
    Text is wrapped to stay within the bounding box width.
    Returns the output path.
    """
    img = Image.open(original_path).convert("RGBA")
    draw = ImageDraw.Draw(img)

    for src_block, tgt_block in zip(source_blocks, translated_blocks):
        bbox = src_block.bounding_box
        if len(bbox) < 4:
            continue

        # Skip strings that are structurally non-translatable (GUIDs, IPs, emails,
        # numbers). Leave original pixels intact — redrawing them looks worse.
        # We do NOT skip based on source == translated because the LLM can
        # inconsistently return source text unchanged for repetitive batches.
        if _is_non_translatable(src_block.text):
            continue

        rect = _polygon_to_rect(bbox)
        bg_color = _sample_background(img, rect)
        draw.rectangle(rect, fill=bg_color)

        # Auto-fit font and wrap text to bounding box
        # LLM OPPORTUNITY: replace _fit_text with LLM-provided hints for
        # RTL direction, size ratio, and line break suggestions.
        font, lines = _fit_text(draw, tgt_block.text, rect)

        x, y = rect[0], rect[1]
        line_height = draw.textbbox((0, 0), "Ag", font=font)[3] + 1
        for line in lines:
            draw.text((x, y), line, fill=(0, 0, 0, 255), font=font)
            y += line_height

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(str(out))
    return str(out)


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    rect: Tuple[float, float, float, float],
    default_size: int = 13,
    min_size: int = 7,
) -> Tuple[ImageFont.FreeTypeFont, List[str]]:
    """
    Fits text into the bounding box width on a single line where possible.

    Strategy:
      1. Start at default_size (matches typical UI screenshot font size).
      2. Scale DOWN until the text fits on one line within the bbox width.
      3. Only wrap into multiple lines if even min_size doesn't fit on one line.
         Wrapping is a last resort — UI labels are designed for single lines.

    NOTE: We do NOT use bbox HEIGHT to derive font size. EasyOCR bounding boxes
    include generous padding (2-3x actual text height), so height-based sizing
    produces fonts far too large for the context.

    # LLM OPPORTUNITY (Phase 2+):
    # An LLM layout pass could provide a suggested_size_ratio per string
    # (e.g. 0.9 when Italian expansion is minor, 0.7 when much longer) so
    # we skip straight to the right size instead of stepping down from default.
    # It could also flag RTL strings that need direction="rtl" set on the draw call.
    """
    x0, y0, x1, y1 = rect
    max_w = max(1, x1 - x0)
    max_h = max(1, y1 - y0)

    # Step 1: scale down from default until text fits on one line
    for size in range(default_size, min_size - 1, -1):
        font = _load_font(size)
        w = draw.textbbox((0, 0), text, font=font)[2]
        if w <= max_w:
            return font, [text]

    # Step 2: still doesn't fit at min_size — wrap into multiple lines
    font = _load_font(min_size)
    lines = _wrap_text(draw, text, font, max_w)
    return font, lines


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: float,
) -> List[str]:
    """
    Wraps text into lines that fit within max_width at the given font size.
    """
    words = text.split()
    if not words:
        return [text]

    lines = []
    current = ""
    for word in words:
        candidate = (current + " " + word).strip()
        w = draw.textbbox((0, 0), candidate, font=font)[2]
        if w <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)

    return lines if lines else [text]


def _polygon_to_rect(polygon: List[float]) -> Tuple[float, float, float, float]:
    xs = polygon[0::2]
    ys = polygon[1::2]
    return (min(xs), min(ys), max(xs), max(ys))


def _sample_background(img: Image.Image, rect: Tuple) -> Tuple:
    """
    Samples the dominant background colour from the bounding box region.
    Uses the median of a small corner sample to avoid text pixels skewing the result.
    """
    x0, y0, x1, y1 = [int(v) for v in rect]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(img.width, x1), min(img.height, y1)

    if x1 <= x0 or y1 <= y0:
        return (255, 255, 255, 255)

    region = img.crop((x0, y0, x1, y1)).convert("RGBA")

    # Sample a small border strip to get background, not text pixels
    # LLM OPPORTUNITY: an LLM vision call could identify the true background
    # colour more reliably for complex gradients or patterned backgrounds.
    pixels = []
    sample_w = min(region.width, 4)
    sample_h = min(region.height, 4)
    for px in range(sample_w):
        for py in range(sample_h):
            pixels.append(region.getpixel((px, py)))

    # Median per channel
    r = sorted(p[0] for p in pixels)[len(pixels) // 2]
    g = sorted(p[1] for p in pixels)[len(pixels) // 2]
    b = sorted(p[2] for p in pixels)[len(pixels) // 2]
    a = sorted(p[3] for p in pixels)[len(pixels) // 2]
    return (r, g, b, a)


def _load_font(size: int = 14) -> ImageFont.FreeTypeFont:
    for path in ("arial.ttf", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def reinsert_svg(
    original_path: str,
    source_blocks: List[TextBlock],
    translated_blocks: List[TextBlock],
    output_path: str,
) -> str:
    """Placeholder for SVG reinsertion (not yet implemented).

    For now, copies the original SVG unchanged and logs a warning.
    """
    import shutil

    print("  WARNING: SVG reinsertion is not yet implemented — copying original unchanged.")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(original_path, output_path)
    return output_path
