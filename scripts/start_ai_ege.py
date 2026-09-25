"""Launch the local AI-Ege Council using its existing 9Router credential."""

import json
import os
import sys
from pathlib import Path


def main() -> None:
    config_path = Path.home() / ".openclaw" / "openclaw.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    provider = config["models"]["providers"]["9router"]
    key = provider["apiKey"]
    base_url = provider["baseUrl"].rstrip("/")
    if not key or not base_url.endswith("/v1"):
        raise RuntimeError("AI-Ege 9Router bağlantısı eksik veya beklenen biçimde değil.")

    env = os.environ.copy()
    env.update({
        "LLM_API_KEY": key,
        "LLM_API_BASE_URL": base_url,
        "NINEROUTER_BASE_URL": base_url.removesuffix("/v1"),
        "COUNCIL_COMBO": "llm-council",
        "COUNCIL_CHAIRMAN_MODEL": "cx/gpt-6-astra",
        "COUNCIL_EXCLUDE_PATTERNS": "contributor",
        "COUNCIL_MAX_REVIEWERS": "6",
        "COUNCIL_DATA_DIR": str(Path.home() / ".local/share/ai-ege/llm-council/conversations"),
    })
    os.execvpe(sys.executable, [sys.executable, "-m", "backend.main"], env)


if __name__ == "__main__":
    main()
