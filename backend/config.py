"""Configuration for the LLM Council."""

import os
from dotenv import load_dotenv

load_dotenv()

# Any OpenAI-compatible chat API, including 9Router and OpenRouter.
LLM_API_KEY = os.getenv("LLM_API_KEY") or os.getenv("OPENROUTER_API_KEY")
LLM_API_BASE_URL = (os.getenv("LLM_API_BASE_URL") or "https://openrouter.ai/api/v1").rstrip("/")
LLM_API_URL = f"{LLM_API_BASE_URL}/chat/completions"

# When set, read the member list from 9Router before every council run. This
# keeps the council in sync with edits made in the 9Router dashboard.
COUNCIL_COMBO = os.getenv("COUNCIL_COMBO", "").strip()
NINEROUTER_BASE_URL = (os.getenv("NINEROUTER_BASE_URL") or LLM_API_BASE_URL.removesuffix("/v1")).rstrip("/")

# Council members - list of OpenRouter model identifiers
COUNCIL_MODELS = [model.strip() for model in os.getenv("COUNCIL_MODELS", "").split(",") if model.strip()] or [
    "openai/gpt-5.1",
    "google/gemini-3-pro-preview",
    "anthropic/claude-sonnet-4.5",
    "x-ai/grok-4",
]

# Chairman model - synthesizes final response
CHAIRMAN_MODEL = os.getenv("COUNCIL_CHAIRMAN_MODEL", "").strip() or ("" if COUNCIL_COMBO else "google/gemini-3-pro-preview")

# Compatibility for callers that import the original names.
OPENROUTER_API_KEY = LLM_API_KEY
OPENROUTER_API_URL = LLM_API_URL

# Data directory for conversation storage
DATA_DIR = os.getenv("COUNCIL_DATA_DIR", "data/conversations")
