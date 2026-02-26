# LLMage

LLM-based art localization pipeline. Extracts visible text from UI screenshots and images, translates it using an LLM, and reinserts the translated text back into the original asset — ready for MATUA / AT Art Review.

Built to operate fully outside of iCMS. No iCMS integration, no auto-publishing.

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
  LLM translation         ← Claude via Azure AI Foundry + One Term glossary
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
├── .env.example                  # copy to .env and fill in keys
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
│   ├── translator.py             # Step 4:  LLM translation
│   ├── reinsert.py               # Step 5:  text reinsertion into asset
│   ├── packager.py               # Step 6:  MATUA review ZIP creation
│   └── metrics.py                # Step 10: pass/fail/escalation logging
└── tests/
    ├── test_ocr.py               # OCR only — validate extraction on samples
    └── test_extract_reinsert.py  # Extract + stub translate + reinsert (no API keys needed)
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

```bash
cp .env.example .env
```

Open `.env` and set what you have. The endpoint alone is enough to switch to Azure — no key required if using Managed Identity.

```env
# Set endpoint to use Azure. Leave blank to use EasyOCR locally.
AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=https://<your-resource>.cognitiveservices.azure.com/
AZURE_DOCUMENT_INTELLIGENCE_KEY=   # optional — leave blank to use az login / Managed Identity

# Azure AI Foundry — for LLM translation (no API keys, uses az login / Managed Identity)
AZURE_FOUNDRY_ENDPOINT=https://<your-foundry-resource>.services.ai.azure.com/models
AZURE_FOUNDRY_MODEL=claude-sonnet-4-6

TARGET_LANGUAGE=it-IT
```

---

## Running

### Test extraction + reinsertion (no API keys needed)

Validates that text is correctly extracted and reinserted into the source images.
Uses a stub translation (`[IT: original text]`) so you can visually verify bounding box positions.

```bash
python -m tests.test_extract_reinsert
```

Output images are saved to:
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

The pipeline auto-selects the OCR backend based on your `.env`:

| Condition | Backend | Auth |
|-----------|---------|------|
| Endpoint set, no key | Azure AI Document Intelligence | Managed Identity / `az login` |
| Endpoint set, key set | Azure AI Document Intelligence | API key |
| No endpoint | EasyOCR (local) | None |

To set up Azure AI Document Intelligence:
1. Go to [portal.azure.com](https://portal.azure.com)
2. Create resource → search **Document Intelligence**
3. Copy the endpoint into `.env` — run `az login` locally, no key needed

---

## MATUA Review Package

Each processed asset produces a ZIP following the MATUA / AT Art Review structure:

```
<asset_id>/
  original.<ext>          source image
  localized.<ext>         LLM-localized image
  text_mapping.json       source ↔ translated string pairs
  metadata.json           language info, pipeline version, string count
```

---

## Out of Scope

- iCMS integration
- Auto-publishing
- Non-art content types (text files, XLIFF, etc.)
- LLM involvement in review decisions (LLM is translation only)
