# LLM Council development guide

This is Ege's fork of `karpathy/llm-council`. Keep upstream attribution and the three-stage process: independent answers, anonymous peer reviews, then a chairman synthesis.

For 9Router, `COUNCIL_COMBO` is a source of **member IDs**, never the model ID for a single council request. Resolve the combo on every run and call each member ID separately. A missing or unreadable combo must fail clearly; never silently replace it with a one-model fallback.

Before a change, identify one user-visible problem and a concrete acceptance check. Keep changes small enough to review. Avoid adding model calls for cosmetic tasks. Do not log prompts, responses, API keys, authorization headers, or `.env` values. Conversation data stays under the ignored `data/` directory.

Verification before committing or publishing:

```sh
uv sync --frozen
uv run python -m unittest discover -s tests -v
cd frontend
npm ci
npm test
npm run lint
npm run build
npm audit --audit-level=high
```

When a provider is unavailable, report which model failed and whether the final answer is degraded. Never claim all council members answered unless the stage metadata proves it. For AI-Ege/Telegram integration, use the local `/api/council/ask` endpoint after the service is actually running, and verify the returned `stage1`, `stage2`, `stage3`, and failure lists with a synthetic question. Never publish personal conversations or server credentials to GitHub.
