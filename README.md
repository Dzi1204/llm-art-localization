# LLMage

LLM-based art localization pipeline. Extracts visible text from UI screenshots and images, translates it using an LLM, scores translation quality via QE, and reinserts the translated text back into the original asset — ready for MATUA / AT Art Review.

Built to operate fully outside of iCMS. No iCMS integration, no auto-publishing.

---

## Purpose

Microsoft's existing art localization flow (MATUA) relies on classic MT for translation. LLMage replaces that MT step with an LLM while keeping the rest of the MATUA review process unchanged.

```
Source image (en-US)
       |
       v
  OCR extraction          <- Azure AI Document Intelligence or EasyOCR (local)
       |
       v
  LLM translation         <- Azure AI Foundry (preferred) or OpenAI (dev fallback)
       |
       v
  QE scoring              <- LLMQualityEstimation service (dev)
       |
       v
  Text reinsertion        <- Pillow
       |
       v
  MATUA review ZIP        <- original + localized + text mapping
       |
       v
  Supplier review         <- Pass -> done / Fail -> escalate or NoLoc fallback
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
| PDF | Azure Doc Intelligence |

---

## Project Structure

```
LLMage/
+-- .env.example                  # copy to .env and fill in your values
+-- requirements.txt
+-- config.py                     # all settings in one place
+-- main.py                       # run the full pipeline on a file or folder
+-- data/
|   +-- source-art/               # English source images (pilot input)
|   +-- matua-pass/               # reference: localized images that passed review
|   +-- matua-fail/               # reference: localized images that failed review
+-- pipeline/
|   +-- eligibility.py            # Step 1:  file type check
|   +-- extractor.py              # Step 3:  OCR text extraction + bounding boxes
|   +-- translator.py             # Step 4:  LLM translation (Foundry or OpenAI)
|   +-- qe_client.py              # Step 4b: QE quality scoring
|   +-- reinsert.py               # Step 5:  text reinsertion into asset
|   +-- packager.py               # Step 6:  MATUA review ZIP creation
|   +-- metrics.py                # Step 10: pass/fail/escalation logging
+-- tests/
    +-- test_ocr.py               # OCR only -- validate extraction on samples
    +-- test_extract_reinsert.py  # Extract + translate + QE + reinsert end-to-end
```

---

## Setup

### 1. Prerequisites

- Python 3.10+
- pip

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

> First run will download EasyOCR models (~200 MB). This is automatic and one-time only.

### 3. Configure environment

**Windows:**
```cmd
copy .env.example .env
```

**Mac / Linux:**
```bash
cp .env.example .env
```

Edit `.env` with your values — see sections below for each service.

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

Two backends are supported. **Foundry takes priority** if both are configured.

| Condition | Backend | Auth |
|-----------|---------|------|
| `AZURE_FOUNDRY_ENDPOINT` set | Azure AI Foundry | `az login` / Managed Identity |
| `OPENAI_API_KEY` set (Foundry not set) | OpenAI | API key |
| Neither set | Stub `[IT: original text]` | None |

### Option 1 — Azure AI Foundry (preferred)

Enterprise-safe, no personal API keys, auth via `az login`.

```env
AZURE_FOUNDRY_ENDPOINT=https://<your-foundry-resource>.services.ai.azure.com/models
AZURE_FOUNDRY_MODEL=claude-sonnet-4-6
```

To set up:
1. Go to [ai.azure.com](https://ai.azure.com)
2. Open your project -> **Deployments** -> deploy a model (Claude or GPT)
3. Copy the endpoint into `.env`
4. Run `az login` — no key needed

### Option 2 — OpenAI (dev fallback)

Use when Foundry access is not available.

```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o        # or gpt-4o-mini for lower cost
```

---

## QE Scoring

After translation, each string is scored by the **LLMQualityEstimation** service (dev).
Strings scoring below `QE_SCORE_THRESHOLD` are flagged in the console report.

Auth uses a manually obtained Bearer token.

```env
QE_ENDPOINT=https://llm-quality-estimation-dev.azurewebsites.net/
QE_BEARER_TOKEN=<your token>
QE_SCORE_THRESHOLD=0.7
```

> Do not include `.scm.` in the QE endpoint URL — that is the Kudu deployment portal, not the API.

To get a fresh token:
```bash
az account get-access-token --resource api://0da43d3e-94e5-42fe-a9f4-09600ef73478
```
Copy the `accessToken` value into `.env` as `QE_BEARER_TOKEN`.

QE scoring is skipped silently if `QE_ENDPOINT` or `QE_BEARER_TOKEN` is not set.

**About `[N/A]` scores:** Strings where source equals translated (GUIDs, IP addresses, product names, numbers) are filtered out by the QE service as non-translatable and return no score. This is expected.

---

## Running

### End-to-end test (extract + translate + QE + reinsert)

```bash
python -m tests.test_extract_reinsert
```

Sample output:

```
Source      : en-US
Target      : it-IT
Translator  : OpenAI
QE scoring  : enabled (dev)

============================================================
  select-everyone.png
============================================================
  Blocks extracted : 16  |  Localizable : True

  Translating via OpenAI (it-IT)...

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
  [0.95]
    EN: 'Check Names'
    IT: 'Verifica Nomi'
  [N/A]
    EN: 'OK'
    IT: 'OK'

  -> Localized image : select-everyone_it-IT.png
  -> Review package  : select-everyone_it-IT.zip
```

> `[N/A]` = source and translated text are identical (e.g. "OK", GUIDs, IPs) — QE service skips these as non-translatable.

Output files:
```
output/
+-- test_reinsert/
|   +-- select-everyone_it-IT.png
|   +-- view-report-for-compliance-policy_it-IT.png
|   +-- 8680235-limited-query-preview_it-IT.png
|   +-- configuration-properties_it-IT.png
+-- packages/
    +-- select-everyone_it-IT.zip
    +-- view-report-for-compliance-policy_it-IT.zip
    +-- 8680235-limited-query-preview_it-IT.zip
    +-- configuration-properties_it-IT.zip
```

### OCR only

```bash
python -m tests.test_ocr
```

### Full pipeline on a single image

```bash
python main.py --input "path/to/image.png" --target it-IT
```

### Full pipeline on a folder

```bash
python main.py --input "data/source-art" --target it-IT
```

---

## MATUA Review Package

Each processed asset produces a ZIP following the MATUA / AT Art Review structure:

```
<asset_id>/
  original.<ext>          source image
  localized.<ext>         LLM-localized image
  text_mapping.json       source <-> translated string pairs with QE scores
  metadata.json           language info, model used, string count
```

---

## Out of Scope

- iCMS integration
- Auto-publishing
- Non-art content types (text files, XLIFF, etc.)
- LLM involvement in review decisions (LLM is translation only)
