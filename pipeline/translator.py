"""
Step 4 – Translate extracted text using an LLM.

Backend priority (auto-selected from .env):
  1. Azure AI Foundry  — set AZURE_FOUNDRY_ENDPOINT  (enterprise, no personal key)
  2. OpenAI            — set OPENAI_API_KEY           (dev fallback)

If neither is set, raises EnvironmentError (caller should use stub translator).
"""

from typing import List, Dict, Optional

from config import AZURE_FOUNDRY_ENDPOINT, AZURE_FOUNDRY_MODEL, OPENAI_API_KEY, OPENAI_MODEL
from pipeline.extractor import TextBlock


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

    texts = [b.text for b in blocks]
    prompt = _build_prompt(texts, source_language, target_language, glossary)

    if AZURE_FOUNDRY_ENDPOINT:
        response_text = _translate_via_foundry(prompt)
    elif OPENAI_API_KEY:
        response_text = _translate_via_openai(prompt)
    else:
        raise EnvironmentError(
            "No translation backend configured. "
            "Set AZURE_FOUNDRY_ENDPOINT (Foundry) or OPENAI_API_KEY (OpenAI) in .env."
        )

    translated_texts = _parse_response(response_text, len(texts))

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


def _translate_via_foundry(prompt: str) -> str:
    from azure.ai.inference import ChatCompletionsClient
    from azure.ai.inference.models import SystemMessage, UserMessage
    from azure.identity import DefaultAzureCredential

    client = ChatCompletionsClient(
        endpoint=AZURE_FOUNDRY_ENDPOINT,
        credential=DefaultAzureCredential(),
    )
    response = client.complete(
        model=AZURE_FOUNDRY_MODEL,
        messages=[
            SystemMessage("You are a professional software UI localization translator."),
            UserMessage(prompt),
        ],
        max_tokens=4096,
    )
    return response.choices[0].message.content


def _translate_via_openai(prompt: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=OPENAI_API_KEY)
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": "You are a professional software UI localization translator."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=4096,
    )
    return response.choices[0].message.content


def _build_prompt(
    texts: List[str],
    source_lang: str,
    target_lang: str,
    glossary: Optional[Dict[str, str]],
) -> str:
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))
    glossary_section = _format_glossary(glossary) if glossary else ""

    return f"""Translate the following UI strings from {source_lang} to {target_lang}.

Rules:
- Translate ONLY the text content, do not change numbering or formatting
- Preserve UI placeholders like {{0}}, %s, %1, <variable> exactly as-is
- Keep proper nouns, product names, and brand names unchanged unless in the glossary
- Match the tone and brevity of UI strings (short, clear, imperative)
{glossary_section}
Return ONLY the translated strings, one per line, with the same numbering. No explanations.

Strings to translate:
{numbered}"""


def _format_glossary(glossary: Dict[str, str]) -> str:
    lines = "\n".join(f"  {src} → {tgt}" for src, tgt in glossary.items())
    return f"\nOne Term glossary (use these exact translations):\n{lines}\n"


def _parse_response(response_text: str, expected_count: int) -> List[str]:
    lines = response_text.strip().splitlines()
    results = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line[0].isdigit():
            dot_pos = line.find(".")
            if dot_pos != -1:
                line = line[dot_pos + 1:].strip()
        results.append(line)

    while len(results) < expected_count:
        results.append("")
    return results[:expected_count]
