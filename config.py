import os
from dotenv import load_dotenv

load_dotenv()

AZURE_ENDPOINT = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT")
AZURE_KEY = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
TARGET_LANGUAGE = os.getenv("TARGET_LANGUAGE", "sk-SK")

# Source is always English — confirmed in iCMS Cedar (SourceFileIngestedEvent, en-US hardcoded)
SOURCE_LANGUAGE = "en-US"

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".pdf", ".svg"}

# EasyOCR source language — always English since source is en-US
EASYOCR_LANGUAGES = ["en"]

# Minimum number of words extracted before an asset is considered localizable
MIN_WORD_COUNT = 3
