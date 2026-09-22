# Providers (BYOK, free-tier first)

All calls are direct device → provider. No proxy. User pastes keys in Providers screen.

## Registry (v0.3.0 defaults, user-editable)

| ID | Base URL | Auth | Free path | Default models |
|---|---|---|---|---|
| `gemini` | `https://generativelanguage.googleapis.com/v1beta/openai/` | `Authorization: Bearer` | **Yes, generous** | `gemini-3.8-flash`, `gemini-2.5-flash` |
| `groq` | `https://api.groq.com/openai/v1` | Bearer | **Yes** | `openai/gpt-oss-20b`, `openai/gpt-oss-120b`, `qwen/qwen3.6-27b` (qwen3-32b + llama-4-scout retired 07/17/26) |
| `openrouter` | `https://openrouter.ai/api/v1` | Bearer (+ `HTTP-Referer`) | **Yes, `:free` suffix, ~20/min + 50–1000/day** | `openrouter/free` router, `glm-5.2:free`, `minimax-m3:free`, `qwen3-coder:free` |
| `together` | `https://api.together.xyz/v1` | Bearer | **Yes, `-Free` suffix** | `...-Turbo-Free`, `DeepSeek-R1-Distill-...-free`, `Llama-Vision-Free` |
| `huggingface` | `https://api-inference.huggingface.co/v1` (or router) | Bearer | **Yes** | user-picked |
| `deepseek` | `https://api.deepseek.com/v1` | Bearer | Cheap | `deepseek-chat` |
| `openai` | `https://api.openai.com/v1` | Bearer | Paid | `gpt-4o-mini`, `gpt-5-mini`, `gpt-4o` |
| `anthropic` | `https://api.anthropic.com/v1` (Messages API) | `x-api-key` + `anthropic-version` | Paid (trial credit) | `claude-haiku-4-5`, `claude-sonnet-5` (1M ctx), `claude-opus-5` |
| `custom` | user input | Bearer | Ollama/LM Studio LAN | user-picked |

Model names churn (esp. Groq/OpenRouter). `config.py` holds defaults, but UI always allows **“+ Custom model”** and per-provider model list edit.

## Capabilities matrix (show as badges)

Each model entry: `supports_vision: bool`, `supports_docs: bool` (as text), `max_tokens: int`, `free: bool`.
Images → `image_url` parts only if `supports_vision`, else block with explainer. PDFs/txt → text injection with truncation warning.

## Test-connection

`Test` button sends cheapest call (`GET /models` if supported, else 1-token chat `“ping”`, `max_tokens=1`). Surface 401 (bad key), 404 (bad model/base_url), 429 (rate limit) in plain language.

## Headers per provider

- OpenAI-compat: `Authorization: Bearer $KEY`, `Content-Type: application/json`.
- Anthropic: `x-api-key: $KEY`, `anthropic-version: 2023-06-01`.
- OpenRouter: + `HTTP-Referer: <app-url-or-name>`, `X-Title: Multi-AI Flet`.
