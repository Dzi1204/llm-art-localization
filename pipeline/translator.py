"""
Step 4 – Translate extracted text using Azure OpenAI.
Auth: DefaultAzureCredential (az login / Managed Identity) — no key required.
"""

from typing import List, Dict, Optional

from config import (
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_DEPLOYMENT,
    AZURE_OPENAI_API_VERSION,
)
from pipeline.extractor import TextBlock


def translate_blocks(
    blocks: List[TextBlock],
    source_language: str,
    target_language: str,
    glossary: Optional[Dict[str, str]] = None,
    model: Optional[str] = None,
) -> List[TextBlock]:
    """
    Translates all TextBlocks via the configured LLM backend.
    Returns a new TextBlock list with translated text. Original blocks are not mutated.
    """
    if not blocks:
        return []

    texts = [b.text for b in blocks]
    prompt = _build_prompt(texts, source_language, target_language, glossary)
    response_text = _translate_via_azure_openai(prompt, model=model or AZURE_OPENAI_DEPLOYMENT)

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


def _translate_via_azure_openai(prompt: str, model: str = AZURE_OPENAI_DEPLOYMENT) -> str:
    from openai import AzureOpenAI
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
    response = client.chat.completions.create(
        model=model,
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
