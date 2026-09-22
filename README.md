# INF ai — Student AI Toolkit (Flet Phone App)

BYOK study toolkit for students (Android, desktop-dev, mobile-first).
Explain, solve, summarise & revise with free-tier models. No backend. Keys stay on device. Attach images + docs to capable models.

## Scope (v1 locked)

- **Keys:** BYOK on-device only, Fernet-encrypted under a hardware-backed
  KEK (SecureStorage/Keystore). Optional PIN + biometric app lock. No proxy server.
- **Providers:** Big 4 + open-compat, free-tier first
  (Gemini, Groq, Together, OpenRouter `:free`, HuggingFace, DeepSeek, OpenAI, Anthropic, Custom base_url).
- **Files:** images + docs; long docs (>12k chars) use on-device TF-IDF
  retrieval (top-3 excerpts, cited) instead of truncation.
- **Target:** develop with `flet run` on desktop, ship `flet build apk/aab`. iOS deferred.

## Quickstart

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
pip install flet flet-secure-storage httpx pypdf cryptography

# run (desktop dev loop)
flet run main.py

# Android (Windows can build APK/AAB; iOS needs macOS+Xcode)
flet build apk --split-per-abi
flet build aab
```

See `docs/` → `ARCHITECTURE.md`, `UI_COMPONENTS.md`, `PROVIDERS.md`, `SECURITY.md`, `ROADMAP.md`.

## Repo layout (planned)

```
main.py
pyproject.toml
app/
  config.py
  core/{types,provider_base,anthropic_provider,gemini_provider,provider_factory,chat_service,attachment_service}.py
  data/{key_store,chat_store}.py
  ui/{theme,screens/chat_screen,screens/providers_screen,screens/settings_screen,widgets/*}.py
assets/
docs/
```

## License

Project code: MIT (see `LICENSE`).
Third-party licenses: see `THIRD_PARTY_LICENSES.md`.
Flet framework itself is Apache-2.0 — compatible, no action needed beyond attribution file.
