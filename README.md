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
  LLM translation         ← Claude (Anthropic) + One Term glossary + RTL support
       │
       ▼
  Text reinsertion        ← Pillow (raster) / lxml (SVG)
       │
       ▼
  MATUA review ZIP        ← original + localized + text mapping
       │
       ▼
  Supplier review         ← Pass → done / Fail → escalate or NoLoc fallback
```

---

## Pilot Languages

| Phase | Languages |
|-------|-----------|
| Phase 1 – Initial pilot | Slovak (`sk-SK`), Italian (`it-IT`) |
| Phase 2 – Expansion | Additional languages with known characteristics (e.g. longer text expansion, different scripts) |
| Phase 3 – Scale-out | Broad language coverage |

---

## Supported Asset Types

| Type | Handling |
|------|----------|
| PNG, JPG, BMP, TIFF | Azure Doc Intelligence or EasyOCR |
| PDF | Azure Doc Intelligence |
| SVG | Direct XML parsing — no OCR needed |

---

## Project Structure

```
LLMage/
├── .env.example                  # copy to .env and fill in keys
├── requirements.txt
├── config.py                     # all settings in one place
├── main.py                       # run the full pipeline on a file or folder
├── pipeline/
│   ├── eligibility.py            # Step 1:  file type check
│   ├── extractor.py              # Step 3:  OCR text extraction + bounding boxes
│   ├── translator.py             # Step 4:  LLM translation (data scientist scope)
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

Open `.env` and fill in what you have. Azure keys are optional — leave blank to use EasyOCR locally.

```env
# Leave blank to use local EasyOCR (no cloud needed)
AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=
AZURE_DOCUMENT_INTELLIGENCE_KEY=

# Required only for translation step
ANTHROPIC_API_KEY=

# Target language for pilot
TARGET_LANGUAGE=sk-SK
```

---

## Running

### Test extraction + reinsertion (no API keys needed)

Validates that text is correctly extracted and reinserted into the source images.
Uses a stub translation (`[SK: original text]`) so you can visually verify bounding box positions.

```bash
python -m tests.test_extract_reinsert
```

Output images are saved to:
```
output/test_reinsert/
  select-everyone_sk-SK.png
  select-everyone_it-IT.png
  view-report-for-compliance-policy_sk-SK.png
  view-report-for-compliance-policy_it-IT.png
  ...
```

### Test OCR only

```bash
python -m tests.test_ocr
```

### Run the full pipeline on a single image

```bash
python main.py --input "path/to/image.png" --target sk-SK
```

### Run on a folder

```bash
python main.py --input "C:\path\to\Source Art Matua" --target sk-SK
```

Output packages (MATUA review ZIPs) are saved to `output/packages/`.

---

## OCR Backend

The pipeline auto-selects the OCR backend based on your `.env`:

| Condition | Backend used |
|-----------|-------------|
| Azure keys present in `.env` | Azure AI Document Intelligence (`prebuilt-read`) |
| No Azure keys | EasyOCR (local, no cloud) |

To set up Azure AI Document Intelligence:
1. Go to [portal.azure.com](https://portal.azure.com)
2. Create resource → search **Document Intelligence**
3. Copy the endpoint and key into `.env`

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
