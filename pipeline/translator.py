"""
Step 4 – Translate extracted text using an LLM (Azure OpenAI).

Improvements over the previous version:
- Structured output via Pydantic — no fragile line-by-line text parsing
- Space-aware prompts — each string includes a [max N chars] budget derived
  from its bounding box so the layout refiner fires less often
- Batching — inputs are chunked into groups of ≤20 to reduce ordering drift
"""

import re
from typing import List, Dict, Optional
from pydantic import BaseModel
from PIL import Image, ImageDraw

from config import (
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_DEPLOYMENT,
    AZURE_OPENAI_MODEL,
    AZURE_OPENAI_API_VERSION,
)
from pipeline.extractor import TextBlock
from pipeline.reinsert import _polygon_to_rect, _load_font

_BATCH_SIZE = 20
_MIN_CHAR_SIZE = 8  # minimum readable font size — matches layout_refiner


class _TranslationResponse(BaseModel):
    translations: list[str]


def translate_blocks(
    blocks: List[TextBlock],
    source_language: str,
    target_language: str,
    glossary: Optional[Dict[str, str]] = None,
) -> List[TextBlock]:
    """
    Translates all TextBlocks via the configured LLM backend.
    Returns a new TextBlock list with translated text. Original blocks are not mutated.
    """
    if not blocks:
        return []

    max_chars_list = _compute_max_chars(blocks)
    translated_texts: List[str] = []

    for i in range(0, len(blocks), _BATCH_SIZE):
        chunk_blocks = blocks[i:i + _BATCH_SIZE]
        chunk_max = max_chars_list[i:i + _BATCH_SIZE]
        texts = [_clean_ocr_text(b.text) for b in chunk_blocks]
        prompt = _build_prompt(texts, source_language, target_language, chunk_max, glossary)
        batch_result = _translate_via_azure_openai(prompt, len(texts))
        translated_texts.extend(batch_result)

    return [
        TextBlock(
            text=translated,
            bounding_box=original.bounding_box,
            page=original.page,
            confidence=original.confidence,
            element_id=original.element_id,
        )
        for original, translated in zip(blocks, translated_texts)
    ]


def _clean_ocr_text(text: str) -> str:
    """
    Removes OCR artifacts common in Windows UI screenshots:
    - Underscores anywhere in the text (read from keyboard-shortcut underlines, e.g. _Advanced_ or Advanced_)
    - Trailing single/double dots normalised to ellipsis (OCR often reads '...' as '..')
    """
    text = text.replace('_', '')
    # Normalise trailing dots/ellipsis — OCR reads "..." as ".", "..", or " ."
    text = re.sub(r'\s*\.{1,3}\s*$', '...', text)  # "Locations ." → "Locations..."
    return text


def _compute_max_chars(blocks: List[TextBlock]) -> List[Optional[int]]:
    """
    Derives a character budget for each block from its bounding box width
    at the minimum readable font size.
    """
    font = _load_font(_MIN_CHAR_SIZE)
    dummy = Image.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(dummy)
    avg_w = max(1, draw.textbbox((0, 0), "M", font=font)[2])

    result = []
    for b in blocks:
        if len(b.bounding_box) >= 4:
            rect = _polygon_to_rect(b.bounding_box)
            result.append(max(5, int((rect[2] - rect[0]) / avg_w)))
        else:
            result.append(None)
    return result


def _translate_via_azure_openai(prompt: str, expected_count: int) -> List[str]:
    import json
    from openai import AzureOpenAI, BadRequestError
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

    messages = [
        {"role": "system", "content": "You are a professional software UI localization translator."},
        {"role": "user", "content": prompt},
    ]

    # Tier 1: structured output (gpt-4o-2024-08-06+)
    try:
        response = client.beta.chat.completions.parse(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=messages,
            response_format=_TranslationResponse,
            max_completion_tokens=4096,
        )
        translations = response.choices[0].message.parsed.translations
    except BadRequestError:
        # Tier 2: json_object mode (gpt-4o-2024-05-13, gpt-35-turbo-1106+)
        try:
            response = client.chat.completions.create(
                model=AZURE_OPENAI_DEPLOYMENT,
                messages=messages,
                response_format={"type": "json_object"},
                max_completion_tokens=4096,
            )
            translations = json.loads(response.choices[0].message.content)["translations"]
        except (BadRequestError, KeyError, json.JSONDecodeError):
            # Tier 3: plain text — parse JSON from response content
            response = client.chat.completions.create(
                model=AZURE_OPENAI_DEPLOYMENT,
                messages=messages,
                max_completion_tokens=4096,
            )
            content = response.choices[0].message.content or ""
            # Extract the first JSON object from the response
            start = content.find("{")
            end = content.rfind("}") + 1
            translations = json.loads(content[start:end])["translations"]

    # Safety: pad or trim to expected count
    while len(translations) < expected_count:
        translations.append("")
    return translations[:expected_count]


def _build_prompt(
    texts: List[str],
    source_lang: str,
    target_lang: str,
    max_chars_list: List[Optional[int]],
    glossary: Optional[Dict[str, str]],
) -> str:
    numbered = "\n".join(
        f"{i + 1}. [max {max_chars_list[i]} chars] {t}" if max_chars_list[i] is not None
        else f"{i + 1}. {t}"
        for i, t in enumerate(texts)
    )
    glossary_section = _format_glossary(glossary) if glossary else ""

    return f"""Translate the following UI strings from {source_lang} to {target_lang}.

Rules:
- Translate ONLY the text content
- Do NOT translate single-character UI icons such as ×, ✓, ▶, or decorative symbols — skip them entirely
- Stay within the character budget shown in [max N chars] for each string
- Preserve UI placeholders like {{0}}, %s, %1, <variable> exactly as-is
- Keep proper nouns, product names, and brand names unchanged unless in the glossary
- Match the tone and brevity of UI strings (short, clear, imperative)
{glossary_section}
Return a JSON object with a "translations" array containing exactly {len(texts)} translated strings in the same order.

Strings to translate:
{numbered}"""


def _format_glossary(glossary: Dict[str, str]) -> str:
    lines = "\n".join(f"  {src} → {tgt}" for src, tgt in glossary.items())
    return f"\nGlossary (use these exact translations):\n{lines}\n"
