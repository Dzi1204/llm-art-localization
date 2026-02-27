import os
from dotenv import load_dotenv

load_dotenv()

# Azure AI Document Intelligence
# Auth priority:
#   1. Managed Identity / DefaultAzureCredential (recommended — run 'az login' locally)
#   2. API key fallback — only if AZURE_DOCUMENT_INTELLIGENCE_KEY is set in .env
AZURE_ENDPOINT = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT")
AZURE_KEY = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_KEY")  # leave blank to use DefaultAzureCredential
# Azure OpenAI — used for LLM translation
# Auth: DefaultAzureCredential (az login / Managed Identity) — no key required
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-global")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")
TARGET_LANGUAGES = [l.strip() for l in os.getenv("TARGET_LANGUAGES", "it-IT").split(",") if l.strip()]

# Source is always English — confirmed in iCMS Cedar (SourceFileIngestedEvent, en-US hardcoded)
SOURCE_LANGUAGE = "en-US"

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".pdf"}

# EasyOCR source language — always English since source is en-US
EASYOCR_LANGUAGES = ["en"]

# QE Service (dev) — quality scoring after translation
# Auth: paste a manually obtained Bearer token into .env
QE_ENDPOINT = os.getenv("QE_ENDPOINT")          # e.g. https://<func>.azurewebsites.net
QE_BEARER_TOKEN = os.getenv("QE_BEARER_TOKEN")  # manually obtained token
QE_SCORE_THRESHOLD = float(os.getenv("QE_SCORE_THRESHOLD", "0.7"))  # flag strings below this

# Minimum number of words extracted before an asset is considered localizable
MIN_WORD_COUNT = 3
