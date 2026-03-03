# LLMArtLocalization

LLM-based art localization pipeline. Extracts visible text from UI screenshots and images, translates it using an LLM, scores translation quality via QE, and reinserts the translated text back into the original asset — ready for MATUA / AT Art Review.

Built to operate fully outside of iCMS. No iCMS integration, no auto-publishing.

---

## Purpose

Microsoft's existing art localization flow (MATUA) relies on classic MT for translation. LLM - Art Localization replaces that MT step with an LLM while keeping the rest of the MATUA review process unchanged.

```
Source image (en-US)
       |
       v
  Eligibility check       <- file type + extension filter
       |
       v
  OCR extraction          <- Azure AI Document Intelligence or EasyOCR (local)
       |
       v                  <- NoLoc: no text found → copy to output/no-loc/
  LLM translation         <- Azure OpenAI (az login)
       |
       v
  Layout refinement       <- second LLM pass: condense strings that overflow their bbox
       |
       v
  QE scoring              <- LLMQualityEstimation service (dev)
       |
       v
  Text reinsertion        <- Pillow (auto-fit font, skip non-translatable strings)
       |
       v
  MATUA review ZIP        <- created only if QE flagged strings (or QE disabled)
       |
       v
  Supplier review         <- QE pass -> no review needed / QE flag -> human review
```

---

## Pilot Language

| Phase | Languages |
|-------|-----------|
| Phase 1 - Initial pilot | Italian (`it-IT`) |
| Phase 2 - Expansion | Additional languages (e.g. longer text expansion, different scripts) |
| Phase 3 - Scale-out | Broad language coverage |

---

## Supported Asset Types

| Type | Handling |
|------|----------|
| PNG, JPG, BMP, TIFF | Azure Doc Intelligence or EasyOCR |
| PDF | Azure Doc Intelligence (OCR only — reinsertion not yet supported) |

---

## Project Structure

```
LLMArtLocalization/
+-- .env.example                  # copy to .env and fill in your values
+-- requirements.txt
+-- config.py                     # all settings in one place
+-- app.py                        # Streamlit UI — run with: streamlit run app.py
+-- main.py                       # CLI — run the full pipeline on a file or folder
+-- data/
|   +-- source-art/               # English source images (pilot input)
|   +-- no-loc/                   # reference: known NoLoc images (no text to localize)
|   +-- matua-pass/               # reference: localized images that passed review
|   +-- matua-fail/               # reference: localized images that failed review
+-- output/                       # pipeline results (generated at runtime)
|   +-- localized/                # localized images (main.py)
|   +-- no-loc/                   # images detected as NoLoc during pipeline run
|   +-- test_reinsert/            # localized images (test runner)
|   +-- packages/                 # MATUA review ZIPs
+-- pipeline/
|   +-- eligibility.py            # Step 1:  file type check
|   +-- extractor.py              # Step 3:  OCR text extraction + bounding boxes
|   +-- translator.py             # Step 4:  LLM translation (Azure OpenAI)
|   +-- layout_refiner.py        # Step 4b: LLM condensation pass for overflowing strings
|   +-- qe_client.py              # Step 4c: QE quality scoring
|   +-- reinsert.py               # Step 5:  text reinsertion into asset
|   +-- packager.py               # Step 6:  MATUA review ZIP creation
|   +-- metrics.py                # Step 10: pass/fail/escalation logging
+-- tests/
    +-- test_ocr.py               # OCR only — validate extraction on samples
    +-- test_extract_reinsert.py  # Extract + translate + QE + reinsert end-to-end
```

---

## Setup

### 1. Prerequisites

- Python 3.10+
- pip
- Windows (font rendering uses system fonts from `C:/Windows/Fonts/`)

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

> First run will download EasyOCR models (~200 MB). This is automatic and one-time only.

### 3. Configure environment

```cmd
copy .env.example .env
```

Edit `.env` with your values — see sections below for each service.

---

## UI — Streamlit App

The easiest way to run the pipeline is via the Streamlit UI:

```bash
streamlit run app.py
```

Opens in your browser automatically. Features:

- **Multi-image upload** — select one or more PNG / JPG source images at once
- **Language selector** — multiselect showing only currently enabled languages (Italian for Phase 1); more languages added to the selector as each phase activates
- **Sidebar** shows which backends are active (Translator / OCR / QE) with status indicators
- **Scrollable comparison strip** — original and all localizations shown side by side; scroll horizontally to compare when multiple languages are selected
- **Language switcher** — click a language button below the strip to see its QE score, translations table, and downloads — updates live without re-running
- **NoLoc handling** — images with no localizable text are skipped and saved to `output/no-loc/`
- **Per-image expanders** — when multiple images are uploaded, each gets its own comparison section
- **QE banner** — red warning if strings were flagged by QE, green if all passed
- **Download buttons** — localized image and MATUA review ZIP per language

Active languages (UI selector):

| Language | Code | Status |
|----------|------|--------|
| Italian | `it-IT` | Active |
| German, Spanish, French, Portuguese (BR) | `de-DE`, `es-ES`, `fr-FR`, `pt-BR` | Planned |
| Japanese, Korean, Chinese (CN/TW) | `ja-JP`, `ko-KR`, `zh-CN`, `zh-TW` | Planned |
| Slovak, Czech, Polish, Romanian, Dutch, Danish, Latvian | `sk-SK`, `cs-CZ`, `pl-PL`, `ro-RO`, `nl-NL`, `da-DK`, `lv-LV` | Planned |

---

## CLI

### End-to-end test (extract + translate + QE + reinsert)

```bash
python -m tests.test_extract_reinsert
```

Sample output:

```
Source      : en-US
Target      : ['it-IT']
Translator  : Azure OpenAI (az login) — model: gpt-4o-global
QE scoring  : enabled (az login)

============================================================
  select-everyone.png
============================================================
  Blocks extracted : 16  |  Localizable : True

  Translating via Azure OpenAI (az login) — model: gpt-4o-global (it-IT)...

  Scoring translations via QE (dev)...

  QE Results -- 16 strings scored
  Threshold : 0.7
  OK        : 15
  Flagged   : 1

  [0.88]
    EN: 'Select User; Computer; Service Account; or'
    IT: 'Seleziona Utente; Computer; Account di Servizio; o'
  [1.00]
    EN: 'Select this object type:'
    IT: 'Seleziona questo tipo di oggetto:'
  [0.55]  FLAG
    EN: 'or Built-in security principal'
    IT: 'o Principale di sicurezza integrato'
  [N/A]
    EN: 'OK'
    IT: 'OK'

  -> Localized image : select-everyone_it-IT.png
  -> Review package  : select-everyone_it-IT.zip
```

> `[N/A]` = non-translatable string (GUIDs, IPs, numbers) — QE service skips these, reinsertion leaves original pixels intact.

Output files:
```
output/
+-- test_reinsert/
|   +-- select-everyone_it-IT.png
|   +-- view-report-for-compliance-policy_it-IT.png
|   +-- 8680235-limited-query-preview_it-IT.png
|   +-- configuration-properties_it-IT.png
+-- packages/
|   +-- select-everyone_it-IT.zip
|   +-- view-report-for-compliance-policy_it-IT.zip
|   +-- 8680235-limited-query-preview_it-IT.zip
|   +-- configuration-properties_it-IT.zip
+-- no-loc/
    +-- <images with no localizable text>
```

### OCR only

```bash
python -m tests.test_ocr
```

### Full pipeline on a single image

```bash
python main.py --input "path/to/image.png" --target it-IT
```

Output: `output/localized/<image>_it-IT.png` + `output/packages/<image>_it-IT.zip`

### Full pipeline on a folder

```bash
python main.py --input "data/source-art" --target it-IT
```

NoLoc images are automatically copied to `output/no-loc/`.

---

## OCR Backend

Auto-selected based on `.env`:

| Condition | Backend | Auth |
|-----------|---------|------|
| `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT` set, no key | Azure AI Document Intelligence | `az login` / Managed Identity |
| `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT` set, key set | Azure AI Document Intelligence | API key |
| No endpoint set | EasyOCR (local) | None |

```env
# Leave KEY blank to use az login / Managed Identity (recommended)
AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=https://<your-resource>.cognitiveservices.azure.com/
AZURE_DOCUMENT_INTELLIGENCE_KEY=
```

To set up Azure AI Document Intelligence:
1. Go to [portal.azure.com](https://portal.azure.com)
2. Create resource -> search **Document Intelligence**
3. Copy the endpoint into `.env` — no key needed when using `az login`

---

## Translation Backend

| Condition | Backend | Auth |
|-----------|---------|------|
| `AZURE_OPENAI_ENDPOINT` set | Azure OpenAI | `az login` / Managed Identity |
| Nothing set | Stub `[IT: original text]` | None |

```env
AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4o-global
AZURE_OPENAI_API_VERSION=2024-08-01-preview
```

Run `az login` — no API key needed.

---

## LLM Translation — How It Works

Translation uses two sequential LLM calls (Azure OpenAI / GPT-4o) with structured output.

### Call 1 — Translation (`pipeline/translator.py`)

Text blocks are chunked into batches of ≤ 20 and sent with a per-string character budget
derived from each block's bounding box width:

```
Translate the following UI strings from en-US to it-IT.

Rules:
- Stay within the character budget shown in [max N chars] for each string
- Preserve UI placeholders like {0}, %s, %1, <variable> exactly as-is
- Keep proper nouns, product names, and brand names unchanged
- Match the tone and brevity of UI strings (short, clear, imperative)

Return a JSON object with a "translations" array containing exactly 3 translated strings.

Strings to translate:
1. [max 8 chars] Save
2. [max 25 chars] Open file
3. [max 12 chars] Cancel
```

The response is a Pydantic-validated JSON object (`{"translations": [...]}`) — no text parsing required. An optional glossary section can be injected to enforce specific term translations.

### Call 2 — Layout Refinement (`pipeline/layout_refiner.py`)

After translation, each string is checked against its source bounding box pixel budget. Strings that still overflow or whose bounding boxes overlap (after the space-aware Call 1) trigger a second LLM call to condense them:

```
0. source="Save" | current="Salvare il documento" | max_chars=8 | reason=overflow
```

The response is a Pydantic-validated JSON object (`{"condensed": [...]}`). The LLM is instructed to shorten as little as possible, use standard UI abbreviations for the target language, and never switch to English. Because Call 1 already respects pixel budgets, this step fires much less often.

### Remaining limitations

| Limitation | Effect |
|---|---|
| No UI element type context (button / tooltip / header) | LLM cannot tailor brevity to element type — `element_id` is not populated by extractors |

---

## QE Scoring

After translation, each string is scored by the **LLMQualityEstimation** service (dev).
Strings scoring below `QE_SCORE_THRESHOLD` (default: `0.7`) are flagged — and only flagged assets are packaged for MATUA review.

```env
QE_ENDPOINT=https://llm-quality-estimation-dev.azurewebsites.net/
QE_SCORE_THRESHOLD=0.7
```

Auth uses `DefaultAzureCredential` (same `az login` as the translator — no token needed).

> Leave `QE_ENDPOINT` blank to disable QE scoring. Assets will always be packaged for review when QE is disabled.

> Do not include `.scm.` in the QE endpoint URL — that is the Kudu deployment portal, not the API.

Non-translatable strings (GUIDs, IP addresses, numbers, emails) are automatically excluded from QE scoring — the service receives only meaningful text strings.

---

## MATUA Review Package

Each processed asset produces a ZIP following the MATUA / AT Art Review structure:

```
<asset_id>/
  original.<ext>          source image
  localized.<ext>         LLM-localized image
  text_mapping.json       source <-> translated string pairs with QE scores and flagged status
  metadata.json           language info, model, string count, QE summary + flagged strings list
```

Example `metadata.json`:
```json
{
  "asset_id": "select-everyone",
  "source_language": "en-US",
  "target_language": "it-IT",
  "total_strings": 16,
  "qe": {
    "scored": 13,
    "flagged": 1,
    "not_scored": 3,
    "flagged_strings": [
      {
        "source": "or Built-in security principal",
        "translated": "o Principale di sicurezza integrato",
        "qe_score": 0.55
      }
    ]
  }
}
```

---

## Out of Scope

- iCMS integration
- Auto-publishing
- Non-art content types (text files, XLIFF, etc.)
- LLM involvement in review decisions (LLM is translation only)
- PDF reinsertion (OCR extraction works, reinsertion not yet implemented)
