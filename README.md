# LLMage

LLM-based art localization pipeline. Extracts visible text from UI screenshots and images, translates it using an LLM via Azure AI Foundry, and reinserts the translated text back into the original asset — ready for MATUA / AT Art Review.

Built to operate fully outside of iCMS. No iCMS integration, no auto-publishing. No external API keys — all auth via Azure Managed Identity / `az login`.

---

## Purpose

Microsoft's existing art localization flow (MATUA) relies on classic MT for translation. LLMage replaces that MT step with an LLM while keeping the rest of the MATUA review process unchanged.

```
Source image (en-US)
       │
       ▼
  OCR extraction          ← Azure AI Document Intelligence or EasyOCR (local)
       │
       ▼
  LLM translation         ← Claude (or any model) via Azure AI Foundry + One Term glossary
       │
       ▼
  Text reinsertion        ← Pillow
       │
       ▼
  MATUA review ZIP        ← original + localized + text mapping
       │
       ▼
  Supplier review         ← Pass → done / Fail → escalate or NoLoc fallback
```

---

## Pilot Language

| Phase | Languages |
|-------|-----------|
| Phase 1 – Initial pilot | Italian (`it-IT`) |
| Phase 2 – Expansion | Additional languages with known characteristics (e.g. longer text expansion, different scripts) |
| Phase 3 – Scale-out | Broad language coverage |

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
├── .env.example                  # copy to .env and fill in your endpoints
├── requirements.txt
├── config.py                     # all settings in one place
├── main.py                       # run the full pipeline on a file or folder
├── data/
│   ├── source-art/               # English source images (pilot input)
│   ├── matua-pass/               # reference: localized images that passed review
│   └── matua-fail/               # reference: localized images that failed review
├── pipeline/
│   ├── eligibility.py            # Step 1:  file type check
│   ├── extractor.py              # Step 3:  OCR text extraction + bounding boxes
│   ├── translator.py             # Step 4:  LLM translation via Azure AI Foundry
│   ├── reinsert.py               # Step 5:  text reinsertion into asset
│   ├── packager.py               # Step 6:  MATUA review ZIP creation
│   └── metrics.py                # Step 10: pass/fail/escalation logging
└── tests/
    ├── test_ocr.py               # OCR only — validate extraction on samples
    └── test_extract_reinsert.py  # Extract + translate + reinsert end-to-end
```

---

## Setup

### 1. Prerequisites

- Python 3.10+
- pip
- Azure CLI (`az login`) for authentication

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

> First run will download EasyOCR models (~200 MB). This is automatic and one-time only.

### 3. Login to Azure

```bash
az login
```

This is the only auth step needed. No API keys, no personal billing.

### 4. Configure environment

```bash
cp .env.example .env
```

```env
# OCR — set endpoint to switch from EasyOCR to Azure automatically
# Leave KEY blank to use az login / Managed Identity (recommended)
AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=https://<your-resource>.cognitiveservices.azure.com/
AZURE_DOCUMENT_INTELLIGENCE_KEY=

# LLM Translation — Azure AI Foundry
# Change AZURE_FOUNDRY_MODEL to compare different models (e.g. gpt-4o, claude-sonnet-4-6)
AZURE_FOUNDRY_ENDPOINT=https://<your-foundry-resource>.services.ai.azure.com/models
AZURE_FOUNDRY_MODEL=claude-sonnet-4-6

TARGET_LANGUAGE=it-IT
```

---

## Running

### Test extraction + translation + reinsertion

```bash
python -m tests.test_extract_reinsert
```

- If `AZURE_FOUNDRY_ENDPOINT` is set → uses real LLM translation via Foundry
- If not set → falls back to stub `[IT: original text]` so OCR and reinsertion can be validated without Foundry access

Output images saved to:
```
output/test_reinsert/
  select-everyone_it-IT.png
  view-report-for-compliance-policy_it-IT.png
  8680235-limited-query-preview_it-IT.png
  configuration-properties_it-IT.png
```

### Test OCR only

```bash
python -m tests.test_ocr
```

### Run the full pipeline on a single image

```bash
python main.py --input "path/to/image.png" --target it-IT
```

### Run on a folder

```bash
python main.py --input "data/source-art" --target it-IT
```

Output packages (MATUA review ZIPs) are saved to `output/packages/`.

---

## OCR Backend

Auto-selected based on `.env`:

| Condition | Backend | Auth |
|-----------|---------|------|
| Endpoint set, no key | Azure AI Document Intelligence | `az login` / Managed Identity |
| Endpoint set, key set | Azure AI Document Intelligence | API key |
| No endpoint | EasyOCR (local) | None |

To set up Azure AI Document Intelligence:
1. Go to [portal.azure.com](https://portal.azure.com)
2. Create resource → search **Document Intelligence**
3. Copy the endpoint into `.env` — no key needed when using `az login`

---

## Translation Backend

All translation goes through **Azure AI Foundry** using `DefaultAzureCredential` — enterprise-safe, no external API keys, no personal billing.

To switch or compare models, change `AZURE_FOUNDRY_MODEL` in `.env`:

```env
AZURE_FOUNDRY_MODEL=claude-sonnet-4-6   # default
AZURE_FOUNDRY_MODEL=gpt-4o              # or any other model deployed in your Foundry
```

To set up Azure AI Foundry:
1. Go to [ai.azure.com](https://ai.azure.com)
2. Open your project → **Deployments** → deploy a model (Claude or GPT)
3. Copy the endpoint into `.env`

---

## MATUA Review Package

Each processed asset produces a ZIP following the MATUA / AT Art Review structure:

```
<asset_id>/
  original.<ext>          source image
  localized.<ext>         LLM-localized image
  text_mapping.json       source ↔ translated string pairs
  metadata.json           language info, model used, string count
```

---

## Out of Scope

- iCMS integration
- Auto-publishing
- Non-art content types (text files, XLIFF, etc.)
- LLM involvement in review decisions (LLM is translation only)
