"""
LLM reinsertion.

Sends the FULL source image + all text regions in ONE API call.
GPT-4o sees the complete image and returns layout decisions for every region:
  - lines     : how to split the translated text across render lines
  - font_size : recommended size in pixels (should match the original)
  - reason    : brief explanation (useful for debugging)

Goal: the output should look identical to the source — just with translated text.
Pillow executes the instructions.
"""

import io
import base64
import json
from typing import List, Optional
from pydantic import BaseModel
from pathlib import Path
from PIL import Image, ImageDraw

from config import (
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_DEPLOYMENT,
    AZURE_OPENAI_API_VERSION,
    SOURCE_LANGUAGE,
)
from pipeline.extractor import TextBlock
from pipeline.reinsert import (
    _polygon_to_rect,
    _load_font,
    _fit_text,
    _wrap_text,
    _is_non_translatable,
    _sample_background,
    _sample_foreground,
    _estimate_source_font_size,
)

_BBOX_HEIGHT_RATIO = 0.85  # OCR bbox height ≈ font em-square; visible chars are ~85% of that


def _sample_bg_outside(img: Image.Image, rect) -> tuple:
    """
    Sample background color from a thin strip OUTSIDE the text bbox.
    Avoids mixing in text pixels, which corrupt the mode in dense text regions.
    Falls back to a strip inside the bbox edges if no outside strip is available.
    """
    from collections import Counter
    x0, y0, x1, y1 = int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])
    BORDER = 5
    pixels = []
    # prefer strips above and below where the background is unobstructed
    if y0 - BORDER >= 0:
        strip = img.crop((max(0, x0), y0 - BORDER, min(img.width, x1), y0))
        pixels.extend(strip.convert("RGBA").getdata())
    if y1 + BORDER <= img.height:
        strip = img.crop((max(0, x0), y1, min(img.width, x1), min(img.height, y1 + BORDER)))
        pixels.extend(strip.convert("RGBA").getdata())
    if not pixels:
        return _sample_background(img, rect)
    counts: Counter = Counter(
        (p[0] // 8 * 8, p[1] // 8 * 8, p[2] // 8 * 8) for p in pixels
    )
    r, g, b = counts.most_common(1)[0][0]
    return (r, g, b, 255)


def _fg_from_bg(bg_color: tuple) -> tuple:
    """
    Derive text color from background luminance — black on light, white on dark.
    More reliable than averaging antialiased pixels which produce washed-out grays.
    """
    lum = 0.299 * bg_color[0] + 0.587 * bg_color[1] + 0.114 * bg_color[2]
    return (0, 0, 0, 255) if lum >= 128 else (255, 255, 255, 255)


def _save_image(img: Image.Image, orig_mode: str, path: str) -> None:
    """Save RGBA img preserving transparency for formats that support it."""
    ext = Path(path).suffix.lower()
    if ext in ('.jpg', '.jpeg'):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        bg.save(path, quality=95)
    elif ext == '.bmp':
        img.convert("RGB").save(path)
    elif orig_mode in ('RGBA', 'LA', 'PA'):
        img.save(path)
    else:
        img.convert("RGB").save(path)


class LayoutDecision(BaseModel):
    alignment: str          # "left", "center", or "right"
    underline: bool         # true if source text has ANY underline (accelerator or hyperlink)
    bold: bool              # true if source text is bold
    italic: bool            # true if source text is italic
    text_color_hex: str     # "#RRGGBB" for non-standard text color (e.g. blue hyperlinks); "" for normal
    reason: str             # brief explanation


class AllLayoutDecisions(BaseModel):
    decisions: List[LayoutDecision]


def _load_font_styled(size: int, bold: bool = False, italic: bool = False):
    """Loads Arial variant matching the requested style."""
    from PIL import ImageFont
    candidates = []
    if bold and italic:
        candidates = ["arialbi.ttf", "C:/Windows/Fonts/arialbi.ttf"]
    elif bold:
        candidates = ["arialbd.ttf", "C:/Windows/Fonts/arialbd.ttf"]
    elif italic:
        candidates = ["ariali.ttf", "C:/Windows/Fonts/ariali.ttf"]
    else:
        candidates = ["arial.ttf", "C:/Windows/Fonts/arial.ttf"]

    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    # Fallback to plain Arial
    for path in ("arial.ttf", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _encode_image(img: Image.Image) -> str:
    """Encodes the full image as base64 PNG."""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _make_client():
    from openai import AzureOpenAI
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider
    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(),
        "https://cognitiveservices.azure.com/.default",
    )
    return AzureOpenAI(
        api_version=AZURE_OPENAI_API_VERSION,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        azure_ad_token_provider=token_provider,
    )


def llm_layout_decisions_batch(
    client,
    model: str,
    img: Image.Image,
    regions: List[dict],
    target_language: str,
) -> List[LayoutDecision]:
    """
    Sends the full source image + all regions in ONE API call.
    Each region: { index, bbox, source_text, translated_text }
    Returns a LayoutDecision per region (same order).

    Goal: output should look identical to the source — just translated text.
    """
    from openai import BadRequestError

    b64 = _encode_image(img)

    region_lines = "\n".join(
        f"{r['index']}. bbox=[{r['bbox'][0]},{r['bbox'][1]},{r['bbox'][2]},{r['bbox'][3]}]"
        f"  measured_font_size={r['source_font_size']}px"
        f"  source=\"{r['source_text']}\""
        f"  translated=\"{r['translated_text']}\""
        for r in regions
    )

    prompt = (
        f"You are a pixel-perfect UI localization specialist. "
        f"The attached image is a {img.width}×{img.height} px software UI screenshot in the source language.\n\n"
        f"GOAL: produce layout instructions so the localized image looks IDENTICAL to the source — "
        f"same font size, same alignment, same styling, same line count — just with text in {target_language}.\n\n"
        f"For each region below, examine that specific bbox area in the image carefully and return:\n\n"
        f"1. alignment (string: left | center | right): Horizontal text alignment observed in the image.\n"
        f"   - Labels (e.g. 'Select this object type:') → left\n"
        f"   - Input field content → left\n"
        f"   - Button text (e.g. 'OK', 'Cancel', 'Object Types...') → center\n"
        f"   - Dialog title bar text → center\n\n"
        f"2. underline (bool): true if ANY part of the source text has a visual underline.\n"
        f"   - Keyboard accelerator: underline under exactly one character (e.g. 'A' in 'Advanced...').\n"
        f"   - Hyperlink: underline spans the entire word (e.g. 'examples' in a blue link).\n"
        f"   - Look closely — these are subtle 1px lines at the text baseline.\n\n"
        f"3. bold (bool): true if the text strokes appear heavier/thicker than surrounding UI text.\n\n"
        f"4. italic (bool): true if the text is slanted.\n\n"
        f"5. text_color_hex (string): The hex color of the text if it is NOT plain black or white.\n"
        f"   - Blue hyperlinks → something like '#0066CC'\n"
        f"   - Normal black/white UI text → empty string \"\"\n\n"
        f"6. reason (string): one sentence summarising what you observed for this region.\n\n"
        f"REGIONS (index. bbox=[x0,y0,x1,y1]  measured_font_size  source  translated):\n"
        f"{region_lines}\n\n"
        f"Return a JSON object with a \"decisions\" array of exactly {len(regions)} items in the same order.\n"
        f"Each item must have: alignment (string), "
        f"underline (bool), bold (bool), italic (bool), text_color_hex (string), reason (string)."
    )

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": prompt},
            ],
        }
    ]

    # Tier 1: structured output (gpt-4o-2024-08-06+)
    try:
        response = client.beta.chat.completions.parse(
            model=model, messages=messages,
            response_format=AllLayoutDecisions,
            max_tokens=2048,
        )
        return response.choices[0].message.parsed.decisions
    except BadRequestError:
        pass

    # Tier 2: json_object mode (gpt-4o-global, gpt-4o-2024-05-13)
    try:
        response = client.chat.completions.create(
            model=model, messages=messages,
            response_format={"type": "json_object"},
            max_tokens=2048,
        )
        data = json.loads(response.choices[0].message.content)
        return [LayoutDecision(**d) for d in data["decisions"]]
    except Exception:
        pass

    # Tier 3: plain text with JSON extraction
    response = client.chat.completions.create(
        model=model, messages=messages, max_tokens=2048,
    )
    content = response.choices[0].message.content or ""
    start, end = content.find("{"), content.rfind("}") + 1
    data = json.loads(content[start:end])
    return [LayoutDecision(**d) for d in data["decisions"]]


def reinsert_llm_guided(
    original_path: str,
    source_blocks: List[TextBlock],
    translated_blocks: List[TextBlock],
    target_language: str,
    output_path: str,
    status_callback=None,
) -> str:
    """
    Single API call: sends full image + all regions → GPT-4o returns all layout decisions.
    Falls back per-region to the Pillow algorithm if the batch call fails.

    status_callback: optional callable(str) for progress messages (e.g. st.write)
    """
    client = _make_client()
    model = AZURE_OPENAI_DEPLOYMENT

    _pil_orig = Image.open(original_path)
    _orig_mode = _pil_orig.mode
    img = _pil_orig.convert("RGBA")
    img_orig = img.copy()  # Unmodified copy used for colour sampling
    draw = ImageDraw.Draw(img)

    # Collect translatable regions
    active = []
    for i, (src, tgt) in enumerate(zip(source_blocks, translated_blocks)):
        if len(src.bounding_box) < 4 or _is_non_translatable(src.text):
            continue
        rect = _polygon_to_rect(src.bounding_box)
        # OCR bounding boxes are tight around the characters, so bbox height ≈ font size
        measured_font_size = max(8, min(72, int(rect[3] - rect[1])))
        active.append({
            "index": i,
            "src": src,
            "tgt": tgt,
            "rect": rect,
            "bbox": [int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])],
            "source_text": src.text,
            "translated_text": tgt.text,
            "source_font_size": measured_font_size,
        })

    if not active:
        img.convert(_orig_mode).save(output_path)
        return output_path

    # Single LLM call for all regions
    decisions: List[Optional[LayoutDecision]] = [None] * len(active)
    if status_callback:
        status_callback(f"Asking GPT-4o to layout {len(active)} regions (1 call)...")
    try:
        batch = llm_layout_decisions_batch(
            client=client, model=model, img=img,
            regions=active, target_language=target_language,
        )
        for i, dec in enumerate(batch):
            decisions[i] = dec
            if status_callback:
                status_callback(f"  ✦ [{active[i]['source_text']!r}] {dec.reason}")
    except Exception as e:
        if status_callback:
            status_callback(f"  ⚠ Batch LLM call failed, using Pillow fallback for all: {e}")

    # Reinsert using LLM decisions (or Pillow fallback)
    for i, region in enumerate(active):
        rect = region["rect"]
        src = region["src"]
        tgt = region["tgt"]

        bg_color = _sample_bg_outside(img_orig, rect)

        base_font_size = max(8, min(72, int((rect[3] - rect[1]) * _BBOX_HEIGHT_RATIO)))

        dec = decisions[i]
        if dec:
            alignment = dec.alignment if dec.alignment in ("left", "center", "right") else "left"
            do_underline = dec.underline
            do_bold = dec.bold
            do_italic = dec.italic
            hex_color = dec.text_color_hex.strip()
            if hex_color and hex_color.startswith('#') and len(hex_color) == 7:
                try:
                    h = hex_color[1:]
                    fg_color = (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)
                except ValueError:
                    fg_color = _fg_from_bg(bg_color)
            else:
                fg_color = _fg_from_bg(bg_color)
        else:
            alignment = "left"
            do_underline = '_' in src.text
            do_bold = do_italic = False
            fg_color = _fg_from_bg(bg_color)

        _PAD = 5
        draw.rectangle((
            max(0, rect[0] - _PAD), max(0, rect[1] - _PAD),
            min(img.width, rect[2] + _PAD), min(img.height, rect[3] + _PAD),
        ), fill=bg_color)

        # Fit text on a single line: shrink font from base down to 8px before wrapping.
        box_w = rect[2] - rect[0]
        box_h = rect[3] - rect[1]
        font = _load_font_styled(base_font_size, bold=do_bold, italic=do_italic)
        lines = [tgt.text]
        chosen_size = base_font_size
        for size in range(base_font_size, 7, -1):
            f = _load_font_styled(size, bold=do_bold, italic=do_italic)
            text_w = draw.textbbox((0, 0), tgt.text, font=f)[2]
            if text_w <= box_w:
                font = f
                lines = [tgt.text]
                chosen_size = size
                break
        else:
            # Still doesn't fit at 8px — wrap at 8px as last resort
            font = _load_font_styled(8, bold=do_bold, italic=do_italic)
            lines = _wrap_text(draw, tgt.text, font, box_w)
            chosen_size = 8

        fg_hex = "#{:02x}{:02x}{:02x}".format(*fg_color[:3])
        bg_hex = "#{:02x}{:02x}{:02x}".format(*bg_color[:3])
        print(
            f"  [LLM-REINSERT] {src.text!r:30s} → {tgt.text!r:30s}"
            f"  bbox={int(box_w)}×{int(box_h)}  base={base_font_size}px  chosen={chosen_size}px"
            f"  bold={do_bold}  italic={do_italic}  ul={do_underline}"
            f"  align={alignment}  fg={fg_hex}  bg={bg_hex}  lines={len(lines)}"
        )

        line_height = draw.textbbox((0, 0), "Ag", font=font)[3] + 1
        total_text_h = line_height * len(lines)
        y = rect[1] + max(0, (box_h - total_text_h) / 2)

        for line in lines:
            line_w = draw.textbbox((0, 0), line, font=font)[2]
            if alignment == "center":
                x = rect[0] + max(0, (box_w - line_w) / 2)
            elif alignment == "right":
                x = rect[0] + max(0, box_w - line_w - 2)
            else:  # left
                x = rect[0] + 2
            draw.text((x, y), line, fill=fg_color, font=font)
            if do_underline and line:
                baseline_y = int(y + draw.textbbox((0, 0), line[0], font=font)[3]) + 1
                # Hyperlink = colored text with underline → full width
                # Keyboard accelerator = non-colored underline → single char only
                is_hyperlink = dec and dec.text_color_hex.strip().startswith('#')
                if is_hyperlink:
                    ul_w = line_w
                else:
                    ul_w = draw.textbbox((0, 0), line[0], font=font)[2]
                draw.line([(int(x), baseline_y), (int(x) + ul_w, baseline_y)],
                          fill=fg_color, width=1)
            y += line_height

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    _save_image(img, _orig_mode, str(out))
    return str(out)
