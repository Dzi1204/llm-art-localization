"""
Mock test: Vision LLM extraction → translate → Pillow reinsert

Replaces EasyOCR with GPT-4o vision for the extraction step.

What this tests:
  - GPT-4o vision extracts text regions WITH exact colors, font size,
    alignment, and UI element context — no pixel sampling needed
  - Translation reuses the existing translate_blocks pipeline
  - Reinsertion uses the LLM-provided colors directly instead of guessing

Run:
    python -m tests.test_vision_reinsert
    python -m tests.test_vision_reinsert --file select-everyone.png
    python -m tests.test_vision_reinsert --file select-everyone.png --target sk-SK
"""

import sys
import os
import base64
import json
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel
from PIL import Image, ImageDraw

from config import (
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_DEPLOYMENT,
    AZURE_OPENAI_API_VERSION,
    SOURCE_LANGUAGE,
    TARGET_LANGUAGES,
)
from pipeline.extractor import TextBlock
from pipeline.reinsert import _polygon_to_rect, _load_font, _fit_text

SOURCE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "source-art")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "output", "test_vision_reinsert")


# ── Pydantic models for vision extraction response ─────────────────────────

class VisionRegion(BaseModel):
    text: str
    bounding_box: List[int]          # [x, y, w, h]
    font_size_estimate: str          # small / medium / large / xlarge
    font_weight: str                 # normal / bold
    text_color_hex: str              # e.g. "#000000"
    background_color_hex: str        # e.g. "#FFFFFF"
    alignment: str                   # left / center / right
    context: str                     # e.g. "button", "window title", "label"
    translatable: bool               # False for GUIDs, paths, brand names etc.


class VisionExtractionResponse(BaseModel):
    regions: List[VisionRegion]


# ── Vision extraction ───────────────────────────────────────────────────────

def extract_via_vision_llm(image_path: str) -> List[VisionRegion]:
    """
    Sends the image to GPT-4o vision and gets back structured text regions
    with exact colors, font info, alignment, and context.
    """
    from openai import AzureOpenAI
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider

    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    ext = Path(image_path).suffix.lower().lstrip(".")
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"

    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(),
        "https://cognitiveservices.azure.com/.default",
    )
    client = AzureOpenAI(
        api_version=AZURE_OPENAI_API_VERSION,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        azure_ad_token_provider=token_provider,
    )

    system_prompt = """You are a UI text extraction specialist for software localization.
Analyze the provided UI screenshot and extract ALL visible text regions.

For each region return:
- text: the exact text content (no OCR artifacts like underscores from keyboard shortcut underlines)
- bounding_box: [x, y, width, height] in pixels
- font_size_estimate: one of small / medium / large / xlarge
- font_weight: normal or bold
- text_color_hex: hex color of the text (e.g. "#000000")
- background_color_hex: hex color of the region background (e.g. "#FFFFFF")
- alignment: left, center, or right
- context: what kind of UI element this is (e.g. "button", "window title", "label", "input field", "menu item", "tooltip")
- translatable: true if this text should be localized, false for GUIDs, file paths, domain names, IP addresses, brand names, version numbers

Return a JSON object with a "regions" array."""

    response = client.beta.chat.completions.parse(
        model=AZURE_OPENAI_DEPLOYMENT,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                },
                {"type": "text", "text": "Extract all text regions from this UI screenshot."},
            ]},
        ],
        response_format=VisionExtractionResponse,
        max_tokens=4096,
    )

    return response.choices[0].message.parsed.regions


# ── Convert to TextBlocks for the existing translation pipeline ─────────────

def regions_to_blocks(regions: List[VisionRegion]) -> List[TextBlock]:
    blocks = []
    for r in regions:
        x, y, w, h = r.bounding_box
        # Convert [x,y,w,h] → polygon [x0,y0, x1,y0, x1,y1, x0,y1]
        bbox = [x, y, x + w, y, x + w, y + h, x, y + h]
        blocks.append(TextBlock(
            text=r.text,
            bounding_box=bbox,
            page=1,
            confidence=1.0,
            element_id=r.context,   # store context for potential use
        ))
    return blocks


# ── Reinsertion using LLM-provided colors ───────────────────────────────────

def _hex_to_rgba(hex_color: str) -> tuple:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return (r, g, b, 255)


def reinsert_with_vision_metadata(
    original_path: str,
    regions: List[VisionRegion],
    translated_blocks: List[TextBlock],
    output_path: str,
) -> str:
    """
    Reinsertion driven by LLM-provided colors and alignment.
    No pixel sampling needed — uses exact hex colors from extraction.
    """
    img = Image.open(original_path).convert("RGBA")
    draw = ImageDraw.Draw(img)

    for region, tgt_block in zip(regions, translated_blocks):
        if not region.translatable:
            continue

        x, y, w, h = region.bounding_box
        rect = (x, y, x + w, y + h)

        bg_color = _hex_to_rgba(region.background_color_hex)
        fg_color = _hex_to_rgba(region.text_color_hex)

        # Expand fill by 3px to cover underlines / trailing dots outside bbox
        _PAD = 3
        fill_rect = (
            max(0, rect[0] - _PAD),
            max(0, rect[1] - _PAD),
            min(img.width, rect[2] + _PAD),
            min(img.height, rect[3] + _PAD),
        )
        draw.rectangle(fill_rect, fill=bg_color)

        # Font size from LLM hint
        size_map = {"small": 9, "medium": 12, "large": 15, "xlarge": 18}
        default_size = size_map.get(region.font_size_estimate, 12)

        font, lines = _fit_text(draw, tgt_block.text, rect, default_size=default_size)

        box_w = rect[2] - rect[0]
        box_h = rect[3] - rect[1]
        line_height = draw.textbbox((0, 0), "Ag", font=font)[3] + 1
        total_text_h = line_height * len(lines)
        y_pos = rect[1] + max(0, (box_h - total_text_h) / 2)

        for line in lines:
            line_w = draw.textbbox((0, 0), line, font=font)[2]
            if region.alignment == "center":
                x_pos = rect[0] + max(0, (box_w - line_w) / 2)
            elif region.alignment == "right":
                x_pos = rect[2] - line_w
            else:
                x_pos = rect[0] + 2  # left with small padding

            draw.text((x_pos, y_pos), line, fill=fg_color, font=font)
            y_pos += line_height

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(str(out))
    return str(out)


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="select-everyone.png")
    parser.add_argument("--target", default=None)
    args = parser.parse_args()

    targets = [args.target] if args.target else TARGET_LANGUAGES

    if not AZURE_OPENAI_ENDPOINT:
        print("ERROR: AZURE_OPENAI_ENDPOINT not set in .env")
        sys.exit(1)

    image_path = os.path.join(SOURCE_DIR, args.file)
    if not os.path.exists(image_path):
        print(f"ERROR: file not found: {image_path}")
        sys.exit(1)

    name = Path(args.file).stem
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"Image   : {args.file}")
    print(f"Targets : {targets}\n")

    # Step 1 — Vision extraction
    print("Extracting via GPT-4o vision...")
    regions = extract_via_vision_llm(image_path)
    translatable = [r for r in regions if r.translatable]
    print(f"  {len(regions)} regions found, {len(translatable)} translatable\n")

    for r in regions:
        flag = "" if r.translatable else "  [skip]"
        print(f"  [{r.context:20s}] {r.text!r:40s}  bg={r.background_color_hex}  fg={r.text_color_hex}{flag}")

    # Save extraction JSON for inspection
    extraction_path = os.path.join(OUTPUT_DIR, f"{name}_extraction.json")
    with open(extraction_path, "w", encoding="utf-8") as f:
        json.dump([r.model_dump() for r in regions], f, indent=2, ensure_ascii=False)
    print(f"\n  Extraction saved → {extraction_path}")

    # Step 2 — Translate + reinsert per target language
    from pipeline.translator import translate_blocks

    source_blocks = regions_to_blocks(translatable)

    for target_lang in targets:
        print(f"\n[{target_lang}]")
        print("  Translating...")
        translated = translate_blocks(source_blocks, SOURCE_LANGUAGE, target_lang)

        print("  Reinserting with LLM-provided colors...")
        out_path = os.path.join(OUTPUT_DIR, f"{name}_{target_lang}.png")
        reinsert_with_vision_metadata(image_path, translatable, translated, out_path)
        print(f"  → {out_path}")

    print("\nDone. Compare output/test_vision_reinsert/ vs output/test_reinsert/")


if __name__ == "__main__":
    main()
