# Architecture

## Principles

1. **No backend.** All LLM calls go direct from phone → provider over HTTPS (`httpx.AsyncClient`).
2. **One chat interface, N providers.** `OpenAI-compat` covers ~80%. Two adapters only: Anthropic Messages, Gemini native fallback.
3. **Mobile-safe deps only.** Pure-Python + prebuilt Android wheels. If a dep lacks an Android wheel, it doesn't ship in v1.
4. **Streaming first.** SSE (`data: ...`, `data: [DONE]`) → async generator → live bubble update + cancel.

## Core flow

```
ChatScreen (Flet UI)
  → chat_service.stream(conversation, user_text, attachments)
    → attachment_service.build_payload(provider, model, files)
    → provider_factory.get(provider_id).chat_stream(messages, model)
      → httpx POST {base_url}/chat/completions (or Messages API)
    → yield tokens → UI appends
  → chat_store.save_message()
```

## Modules

| File | Responsibility |
|---|---|
| `app/config.py` | Provider registry (`id, display_name, base_url, models[]`, `supports_vision/docs`, `max_tokens`, `free` flag) |
| `app/core/types.py` | `Message(role, content, attachments)`, `Attachment(name, mime, size, text?, data_url?)` |
| `app/core/provider_base.py` | `BaseProvider.chat_stream()` + `OpenAICompatProvider` (SSE parse, 401/429/404 mapping, timeout 60s, 1x retry on network only) |
| `app/core/anthropic_provider.py` | Messages API (`anthropic-version: 2023-06-01`, `system` separate, image `base64` blocks) |
| `app/core/gemini_provider.py` | Prefers `.../v1beta/openai/` compat; native fallback only if needed |
| `app/core/provider_factory.py` | `get(provider_id, key, base_url_override)` |
| `app/core/chat_service.py` | Orchestration: token estimate (`len//4`), context-limit preflight, cancel, retry, error → user string |
| `app/core/attachment_service.py` | Validate (type/size), image downscale-or-reject, PDF→text via `pypdf`, full-text retention (200k) for RAG; plain path injects 12k head |
| `app/core/rag.py` | v0.4.0 local RAG (stdlib-only): `chunk_for_rag` (~1500/200 overlap), `TfidfIndex.retrieve` cosine top-k, `build_rag_block` with `[file §n]` citations |
| `app/core/history_utils.py` | Pure helpers extracted from `main.py` closures (testable) |
| `app/data/key_store.py` | Fernet-encrypted prefs (`multiai.` prefix) + `rekey()` migration chain; accepts injected KEK Fernet; never log keys |
| `app/data/kek_store.py` | v0.4.0: random 32B KEK in SecureStorage (async load, sync cache, legacy-seed fallback) |
| `app/data/app_lock.py` | v0.4.0: PBKDF2 PIN hash/verify + biometric-gated unlock token + lock/wipe helpers |
| `app/data/chat_store.py` | `sqlite3`: `conversations`, `messages`, `messages_fts`, `doc_chunks` (RAG); export `.md`/`.json` |
| `app/ui/*` | Screens + composite widgets (see `UI_COMPONENTS.md`) |

## Data

- Keys: Fernet-encrypted `data/preferences.json` (`multiai.<provider>.key`) under a hardware-backed KEK. See `SECURITY.md`.
- Chats: `data/chat.db` (sqlite3 stdlib — Android-safe).
- RAG (v0.4.0): long staged docs are chunked + indexed per conversation
  (`doc_chunks`); send path injects top-3 TF-IDF excerpts with citations.
  Follow-up prompts retrieve over the conversation index. Short docs and
  images keep the direct-injection path.
- Attachments: metadata in DB; bytes under `app_data/attachments/` only if <5MB.

## Limits (v0.4.0)

- Images: `png/jpg/webp`, ≤10MB. Vision models only, else blocked with explainer.
- Docs: `txt/md/pdf`, ≤15MB, full text retained to 200k chars. Plain send
  injects the 12k head with truncation warning; RAG (Settings → Documents,
  default on) retrieves top-3 excerpts for docs >12k chars instead.
- Preflight: `est_tokens < model_limit - 2000` else “file too large” dialog.

## Why not LiteLLM on-device

`litellm` is the right pattern for servers (unified `completion()` over 100+ models) but too heavy for `flet build apk` (dependency + wheel risk). We port its *idea* — one OpenAI-shaped interface — in ~200 lines we control.
