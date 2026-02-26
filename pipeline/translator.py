"""
Step 4 – Translate extracted text using Claude (LLM).

- Sends all extracted strings in a single batched prompt to reduce API calls
- Enforces One Term glossary if provided
- Flags RTL languages
"""

from typing import List, Dict, Optional
import anthropic

from config import ANTHROPIC_API_KEY
from pipeline.extractor import TextBlock


RTL_LANGUAGES = {"ar", "ar-SA", "ar-AE", "he", "he-IL", "fa", "ur"}

CLAUDE_MODEL = "claude-sonnet-4-6"


def is_rtl(language_code: str) -> bool:
    base = language_code.split("-")[0].lower()
    return language_code in RTL_LANGUAGES or base in {l.split("-")[0] for l in RTL_LANGUAGES}


def translate_blocks(
    blocks: List[TextBlock],
    source_language: str,
    target_language: str,
    glossary: Optional[Dict[str, str]] = None,
) -> List[TextBlock]:
    """
    Translates all TextBlocks. Returns new TextBlock list with translated text.
    Original blocks are not mutated.
    """
    if not blocks:
        return []

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    texts = [b.text for b in blocks]
    glossary_section = _format_glossary(glossary) if glossary else ""
    rtl_note = "IMPORTANT: The target language is RTL (right-to-left). Preserve RTL text direction." if is_rtl(target_language) else ""

    prompt = _build_prompt(texts, source_language, target_language, glossary_section, rtl_note)

    message = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    translated_texts = _parse_response(message.content[0].text, len(texts))

    translated_blocks = []
    for original, translated in zip(blocks, translated_texts):
        translated_blocks.append(
            TextBlock(
                text=translated,
                bounding_box=original.bounding_box,
                page=original.page,
                confidence=original.confidence,
                element_id=original.element_id,
            )
        )

    return translated_blocks


def _build_prompt(
    texts: List[str],
    source_lang: str,
    target_lang: str,
    glossary_section: str,
    rtl_note: str,
) -> str:
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))
    return f"""You are a professional software UI localization translator.

Translate the following UI strings from {source_lang} to {target_lang}.

Rules:
- Translate ONLY the text content, do not change numbering or formatting
- Preserve UI placeholders like {{0}}, %s, %1, <variable> exactly as-is
- Keep proper nouns, product names, and brand names unchanged unless in the glossary
- Match the tone and brevity of UI strings (short, clear, imperative)
{rtl_note}
{glossary_section}

Return ONLY the translated strings, one per line, with the same numbering. No explanations.

Strings to translate:
{numbered}"""


def _format_glossary(glossary: Dict[str, str]) -> str:
    if not glossary:
        return ""
    lines = "\n".join(f"  {src} → {tgt}" for src, tgt in glossary.items())
    return f"\nOne Term glossary (use these exact translations):\n{lines}\n"


def _parse_response(response_text: str, expected_count: int) -> List[str]:
    """Parses numbered response lines back into a list of strings."""
    lines = response_text.strip().splitlines()
    results = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Remove leading number+dot: "1. text" → "text"
        if line[0].isdigit():
            dot_pos = line.find(".")
            if dot_pos != -1:
                line = line[dot_pos + 1:].strip()
        results.append(line)

    # Pad or truncate to match expected count
    while len(results) < expected_count:
        results.append("")
    return results[:expected_count]
