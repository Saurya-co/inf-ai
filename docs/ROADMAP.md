# Roadmap

- [x] Scope lock: BYOK only, free-tier first, simple attach+send, Android-first desktop-dev
- [x] P0 Scaffold: `main.py` + `pyproject.toml` + `flet run` hello-chat (`com.saurya.multiai`)
- [x] P1 Providers: OpenAI-compat core + Anthropic/Gemini adapters + Providers screen + Test button
- [x] P2 Chat: streaming bubbles, model picker, cancel/retry/copy, token estimate
- [x] P3 Attach: FilePicker images + pdf/txt, capability badges, truncation warnings
- [x] P4 Persist: sqlite history, export md/json, theme, icons/splash
- [x] v0.2.0: new logo/splash, provider refresh (Groq gpt-oss, Together -Free, gemini-2.5-flash, gpt-5-mini), history_utils extraction + 18 tests, FTS search, rename-chat, optional Fernet key encryption
- [x] v0.3.0 (P5 Ship): targetSdk 36, split-per-abi APKs + AAB, Sept-2026 registry refresh (Gemini 3.8, Groq qwen3.6/3.8, Claude 4.5/5 IDs, OpenRouter rotation + free-router), cryptography hard dep, 26 tests
- [x] v0.4.0: hardware-backed KEK (SecureStorage) + PIN/biometric app lock, local TF-IDF RAG over long docs (doc_chunks, §n citations, follow-up retrieval), 41 tests
- [x] v0.4 UI pack: streaming buffer, input morph, inline artifacts/citations, grouped inbox, starter cards, 60 tests
- [x] v0.4 refinement: message lifecycle (edit/fork/pin, code-copy, tokens, reason sheet), zoom lightbox, artifacts panel + charts + save, model recents/presets/matrix, history pin/archive + filters + in-drawer bulk, text-size/OLED/contrast/RTL/shortcuts, 87 tests
- [x] v0.5 round R1+R6: isolated streaming bubble + flush coalescing, windowed long-chat render, live jump pill; find-in-chat (counter, wrap nav, highlight, Ctrl+F), first main.py streaming extraction (`app/ui/controllers/streaming.py`), 116 tests
- [x] v0.5 round R7+R3+R4: token totals + context meter, provider latency/health/capability tiles, RAG source viewer + doc index + relevance tooltip, 135 tests
- [x] v0.5 round R8+R5+R2: prompt library + backup, onboarding tour + replay, 2-slot compare with guard/verdict, 148 tests
- [ ] v0.5 (deferred): iOS build (needs macOS+Xcode+Apple Developer), Flet 1.0 stable re-check (1.0.0.dev0 is prerelease — stay on 0.86.5)

## Build commands

```bash
flet run main.py
flet build apk --split-per-abi
flet build aab
# iOS (later, macOS only): flet build ipa --ios-team-id <ID>
```

Android needs `INTERNET` permission; FilePicker media needs photo/library permission (set in `pyproject.toml`).
