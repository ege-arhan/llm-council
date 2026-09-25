"""Resolve the council's individual members from 9Router or local config."""

import json

import httpx

from . import config


async def resolve_council_models() -> list[str]:
    if not config.COUNCIL_COMBO:
        return list(dict.fromkeys(config.COUNCIL_MODELS))

    url = f"{config.NINEROUTER_BASE_URL}/api/combos"
    headers = {"Authorization": f"Bearer {config.LLM_API_KEY}"} if config.LLM_API_KEY else {}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError("9Router combo listesi okunamadı; Council çalıştırılmadı.") from exc

    combos = payload.get("combos") if isinstance(payload, dict) else payload
    if not isinstance(combos, list):
        raise RuntimeError("9Router combo listesi beklenen biçimde değil.")
    combo = next((item for item in combos if isinstance(item, dict) and item.get("name") == config.COUNCIL_COMBO), None)
    if combo is None:
        raise RuntimeError(f"9Router'da {config.COUNCIL_COMBO} combosu bulunamadı.")
    entries = combo.get("models")
    if isinstance(entries, str):
        try:
            entries = json.loads(entries)
        except ValueError as exc:
            raise RuntimeError("9Router combo model listesi okunamadı.") from exc
    if not isinstance(entries, list):
        raise RuntimeError("9Router combo model listesi beklenen biçimde değil.")

    models = []
    for entry in entries:
        if isinstance(entry, dict):
            if entry.get("enabled") is False:
                continue
            entry = entry.get("model") or entry.get("id")
        if not isinstance(entry, str) or not entry.strip():
            continue
        model = entry.strip()
        if "/" not in model:
            raise RuntimeError(f"{model} iç içe combo olabilir; Council doğrudan üye model gerektirir.")
        if model not in models:
            models.append(model)

    if len(models) < 2:
        raise RuntimeError("Council için comboda en az iki etkin üye model gerekli.")
    return models
