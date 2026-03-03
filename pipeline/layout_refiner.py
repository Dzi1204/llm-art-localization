"""
Step 4b – LLM Layout Advisor (between translation and reinsertion).

Instead of just shortening overflowing translations, the LLM acts as a full
layout advisor for every string.  It analyses the source text, translated
text, and bounding-box dimensions, then returns per-string rendering hints:

  - size_ratio:     font-size multiplier relative to the estimated source size
                    (e.g. 0.85 to shrink slightly for a longer translation)
  - line_break_at:  suggested character position to split into two lines,
                    or null for single-line rendering
  - underline:      whether the source text has underlined characters
                    (keyboard accelerators, hyperlinks)
  - bold:           whether the source text appears bold
  - align:          "left", "center", or "right"

The reinsert module executes these hints directly instead of guessing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import List, Tuple, Optional, Dict
from PIL import ImageDraw, ImageFont, Image

from pipeline.extractor import TextBlock
from pipeline.reinsert import _polygon_to_rect, _load_font

_MIN_READABLE_SIZE = 8
_DEFAULT_SIZE = 13


@dataclass
class LayoutHint:
    """Per-string rendering instructions produced by the LLM layout advisor."""
    translation: str
    size_ratio: float = 1.0
    line_break_at: Optional[int] = None
    underline: bool = False
    bold: bool = False
    align: str = "left"
    link_text: Optional[str] = None  # substring that is a hyperlink (render blue + underlined)


def _text_width(text: str, font: ImageFont.FreeTypeFont) -> int:
    dummy = Image.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(dummy)
    return draw.textbbox((0, 0), text, font=font)[2]


def _estimate_max_chars(bbox: List[float]) -> Optional[int]:
    if len(bbox) < 4:
        return None
    rect = _polygon_to_rect(bbox)
    box_w = max(1, rect[2] - rect[0])
    font = _load_font(_DEFAULT_SIZE)
    avg_char_w = max(1, _text_width("n", font))
    return max(3, int(box_w / avg_char_w))


def _estimate_source_size(source_text: str, bbox: List[float]) -> int:
    if len(bbox) < 4:
        return _DEFAULT_SIZE
    rect = _polygon_to_rect(bbox)
    box_w = max(1, rect[2] - rect[0])
    dummy = Image.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(dummy)
    best = 7
    for size in range(7, 37):
        font = _load_font(size)
        if draw.textbbox((0, 0), source_text, font=font)[2] <= box_w:
            best = size
        else:
            break
    return best


def refine_translations(
    source_blocks: List[TextBlock],
    translated_blocks: List[TextBlock],
    target_language: str,
) -> Tuple[List[TextBlock], List[LayoutHint]]:
    """
    Calls the LLM layout advisor to produce rendering hints for every string.
    Returns (refined_blocks, layout_hints) — one hint per block.
    """
    entries = []
    for i, (src, tgt) in enumerate(zip(source_blocks, translated_blocks)):
        max_chars = _estimate_max_chars(src.bounding_box)
        src_size = _estimate_source_size(src.text, src.bounding_box)
        box_w = 0
        box_h = 0
        if len(src.bounding_box) >= 4:
            rect = _polygon_to_rect(src.bounding_box)
            box_w = int(rect[2] - rect[0])
            box_h = int(rect[3] - rect[1])
        entries.append({
            "idx": i,
            "source": src.text,
            "translated": tgt.text,
            "max_chars": max_chars,
            "source_font_size": src_size,
            "box_width_px": box_w,
            "box_height_px": box_h,
        })

    hints = _llm_layout_advise(entries, target_language)

    # Preserve trailing "..." — if the translator produced "..." but the LLM
    # layout advisor dropped it, re-append.
    for i, tgt in enumerate(translated_blocks):
        if i < len(hints):
            tgt_text = tgt.text.rstrip()
            hint_text = hints[i].translation.rstrip()
            if tgt_text.endswith('...') and not hint_text.endswith('...'):
                hints[i].translation = hint_text + '...'

    refined: List[TextBlock] = []
    for i, tgt in enumerate(translated_blocks):
        text = hints[i].translation if i < len(hints) else tgt.text
        refined.append(TextBlock(
            text=text,
            bounding_box=tgt.bounding_box,
            page=tgt.page,
            confidence=tgt.confidence,
            element_id=tgt.element_id,
        ))

    return refined, hints


def _llm_layout_advise(
    entries: List[dict],
    target_language: str,
) -> List[LayoutHint]:
    """Calls the LLM for layout hints on all strings."""
    from config import (
        AZURE_OPENAI_ENDPOINT,
        AZURE_OPENAI_DEPLOYMENT,
        AZURE_OPENAI_API_VERSION,
    )

    # Fallback when no LLM is available
    if not AZURE_OPENAI_ENDPOINT:
        return [
            LayoutHint(translation=e["translated"])
            for e in entries
        ]

    prompt = _build_advisor_prompt(entries, target_language)

    import time
    from openai import AzureOpenAI, RateLimitError
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider

    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(),
        "https://cognitiveservices.azure.com/.default",
    )
    client = AzureOpenAI(
        api_version=AZURE_OPENAI_API_VERSION,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        azure_ad_token_provider=token_provider,
    )

    # Retry with exponential backoff on rate limit errors
    for attempt in range(4):
        try:
            response = client.chat.completions.create(
                model=AZURE_OPENAI_DEPLOYMENT,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                max_completion_tokens=4096,
            )
            return _parse_advisor_response(response.choices[0].message.content, entries)
        except RateLimitError:
            wait = 2 ** (attempt + 1)
            print(f"  Rate limited — retrying in {wait}s...")
            time.sleep(wait)

    # All retries exhausted — return passthrough hints
    return [LayoutHint(translation=e["translated"]) for e in entries]


_SYSTEM_PROMPT = """\
You are an expert layout advisor for UI screenshot localisation.

You receive a list of source (English) + translated text pairs, each with its \
bounding box dimensions.  For EVERY string you must return rendering hints as JSON.

Your goals:
1. **Preserve the full translation** — do NOT shorten or abbreviate unless the \
   text physically cannot fit even at a reduced font size.  Prefer reducing \
   size_ratio (down to 0.7) or adding a line_break before shortening.
2. **Preserve trailing "..."** — if the translated text ends with "...", keep \
   the ellipsis.  In Windows UI, "..." means "opens a dialog".  NEVER drop it.
3. **Detect formatting** from the source text:
   - Underlined keyboard accelerators (e.g. "_S_elect", "_F_rom") → set underline: true
   - Bold text (e.g. title bars, headings) → set bold: true
   - Hyperlinks (e.g. "examples" in parentheses, typically blue + underlined \
     in UI) → set link_text to the TRANSLATED equivalent substring
4. **Suggest font size ratio** relative to the source font size:
   - 1.0 if the translation fits comfortably
   - < 1.0 (e.g. 0.85, 0.9) if the translation is longer but can still fit \
     with a slightly smaller font
   - Never below 0.7 — at that point prefer a line break instead
5. **Suggest line breaks** — if the text is too long for one line, provide the \
   character index where the line should break (prefer natural word boundaries)
6. **Suggest alignment** — "left" for labels/fields, "center" for buttons/titles

Return a JSON object: { "hints": [ { ... }, ... ] } with one entry per input \
string, in the same order.  Each entry has these fields:
  - translation (string): the final text to render (usually unchanged)
  - size_ratio (number): font size multiplier, 0.7–1.0
  - line_break_at (number|null): char index to break at, or null
  - underline (boolean): true if the source has underlined keyboard accelerator characters
  - bold (boolean): true if the source appears bold
  - align (string): "left", "center", or "right"
  - link_text (string|null): the translated substring that is a hyperlink \
    (will be rendered blue + underlined), or null if no link
"""


def _build_advisor_prompt(entries: List[dict], target_language: str) -> str:
    lines = []
    for e in entries:
        lines.append(
            f'{e["idx"]}. source="{e["source"]}" | '
            f'translated="{e["translated"]}" | '
            f'max_chars={e["max_chars"]} | '
            f'src_font={e["source_font_size"]}px | '
            f'box={e["box_width_px"]}×{e["box_height_px"]}px'
        )

    return f"""Analyse these {target_language} UI translations and provide layout hints.

{chr(10).join(lines)}"""


def _parse_advisor_response(
    response_text: str,
    entries: List[dict],
) -> List[LayoutHint]:
    """Parses the LLM JSON response into LayoutHint objects."""
    try:
        data = json.loads(response_text)
        raw_hints = data.get("hints", [])
    except (json.JSONDecodeError, AttributeError):
        # Fallback: no hints available
        return [LayoutHint(translation=e["translated"]) for e in entries]

    hints: List[LayoutHint] = []
    for i, e in enumerate(entries):
        if i < len(raw_hints):
            h = raw_hints[i]
            hints.append(LayoutHint(
                translation=h.get("translation", e["translated"]),
                size_ratio=max(0.7, min(1.0, float(h.get("size_ratio", 1.0)))),
                line_break_at=h.get("line_break_at"),
                underline=bool(h.get("underline", False)),
                bold=bool(h.get("bold", False)),
                align=h.get("align", "left"),
                link_text=h.get("link_text"),
            ))
        else:
            hints.append(LayoutHint(translation=e["translated"]))

    return hints

