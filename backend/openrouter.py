"""OpenAI-compatible client for 9Router and OpenRouter."""

import asyncio
import logging
import httpx
from typing import List, Dict, Any, Optional
from .config import LLM_API_KEY, LLM_API_URL

logger = logging.getLogger(__name__)


async def query_model(
    model: str,
    messages: List[Dict[str, str]],
    timeout: float = 150.0,
    max_tokens: int = 900,
) -> Optional[Dict[str, Any]]:
    """
    Query a single model via OpenRouter API.

    Args:
        model: OpenRouter model identifier (e.g., "openai/gpt-4o")
        messages: List of message dicts with 'role' and 'content'
        timeout: Request timeout in seconds

    Returns:
        Response dict with 'content' and optional 'reasoning_details', or None if failed
    """
    if not LLM_API_KEY:
        raise RuntimeError("LLM_API_KEY veya OPENROUTER_API_KEY ayarlanmalı.")
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": False,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            for attempt in range(2):
                response = await client.post(LLM_API_URL, headers=headers, json=payload)
                if response.status_code in {429, 500, 502, 503, 504} and attempt == 0:
                    await asyncio.sleep(1)
                    continue
                response.raise_for_status()
                data = response.json()
                message = data["choices"][0]["message"]
                content = message.get("content")
                if isinstance(content, list):
                    content = "\n".join(part.get("text", "") for part in content if isinstance(part, dict))
                if not isinstance(content, str) or not content.strip():
                    if attempt == 0:
                        payload["max_tokens"] = min(max_tokens * 2, 2600)
                        continue
                    logger.warning("Model %s returned empty content after one larger-budget retry", model)
                    return None
                return {"content": content.strip(), "reasoning_details": message.get("reasoning_details"),
                        "usage": data.get("usage")}
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
        status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        logger.warning("Model %s failed: %s%s", model, type(exc).__name__, f" HTTP {status}" if status else "")
    return None


async def query_models_parallel(
    models: List[str],
    messages: List[Dict[str, str]],
    max_tokens: int = 900,
) -> Dict[str, Optional[Dict[str, Any]]]:
    """
    Query multiple models in parallel.

    Args:
        models: List of OpenRouter model identifiers
        messages: List of message dicts to send to each model

    Returns:
        Dict mapping model identifier to response dict (or None if failed)
    """
    import asyncio

    # 9Router multiplexes provider requests. Bound in-flight calls so a large
    # council cannot exhaust the gateway and time out every member together.
    semaphore = asyncio.Semaphore(3)

    async def limited(model):
        async with semaphore:
            return await query_model(model, messages, max_tokens=max_tokens)

    tasks = [limited(model) for model in models]

    # Wait for all to complete
    responses = await asyncio.gather(*tasks)

    # Map models to their responses
    return {model: response for model, response in zip(models, responses)}
