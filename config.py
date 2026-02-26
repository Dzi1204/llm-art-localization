import os
from dotenv import load_dotenv

load_dotenv()

# Azure AI Document Intelligence
# Auth priority:
#   1. Managed Identity / DefaultAzureCredential (recommended — run 'az login' locally)
#   2. API key fallback — only if AZURE_DOCUMENT_INTELLIGENCE_KEY is set in .env
AZURE_ENDPOINT = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT")
AZURE_KEY = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_KEY")  # leave blank to use DefaultAzureCredential
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
TARGET_LANGUAGE = os.getenv("TARGET_LANGUAGE", "it-IT")

# Source is always English — confirmed in iCMS Cedar (SourceFileIngestedEvent, en-US hardcoded)
SOURCE_LANGUAGE = "en-US"

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".pdf"}

# EasyOCR source language — always English since source is en-US
EASYOCR_LANGUAGES = ["en"]

# Minimum number of words extracted before an asset is considered localizable
MIN_WORD_COUNT = 3
