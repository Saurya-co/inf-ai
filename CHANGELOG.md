# Changelog

## Unreleased — v0.6 (Flet-only)

### Added
- Image output: text-to-image via `POST {base}/images/generations`
  (`OpenAICompatProvider.generate_image`, b64_json + url payloads) for
  OpenAI (gpt-image-1, dall-e-3), Together (FLUX.1-schnell-Free/FLUX.1-dev)
  and Custom OpenAI-compat servers; entry via the input "+" menu or the
  `/image <prompt>` chat command; provider/model/size dialog lists only
  linked image-capable providers; PNGs persist to `data/generated/` with a
  plain-text history note (card rebuilt from disk on reload, tap-to-zoom
  lightbox, save-to-device).
- Smart model search: query tokenizes on whitespace (AND semantics) and
  matches ids, provider names, capabilities (vision/docs/…), context
  shorthands (`1m`, `128k`), pricing tier and family words; live match
  count under the search field.
- Readable streaming: `StreamRevealPacer` releases tokens at a steady
  word-boundary pace (~160 chars/s) with catch-up speedup, plus a
  post-stream drain loop; "Thinking…" indicator until the first token.

### Changed
- Model pill moved into the AppBar next to the menu (chat area gains the
  freed row); pill hidden on Providers/Settings tabs.
- Model sheet lists only API-linked providers, with an add-key guidance
  tile when nothing is linked.
- Logo refined: smooth lemniscate infinity stroke + sparkle on the indigo
  gradient (`tools_make_logo.py` regenerates `assets/icon.png` + splash).

## Unreleased — v0.5 round R8+R5+R2 (Flet-only)

### Added
- Prompt library (R8): user-saved presets (title + prompt + optional
  provider/model binding, cap 20) with BottomSheet list (insert/edit/
  delete), editor dialog, `+ Saved` section in the empty state
  (insert-only, no auto-send), bookmark button in the input row, and
  Settings export/import JSON backup (survives reinstall).
- Onboarding tour (R5): first-run BottomSheet wizard (provider → key +
  Test → model → starter), progress dots, always-skippable, non-blocking;
  completion persists `ui.onboarded`; no keys + not onboarded triggers it;
  replay via Settings → About → "Replay setup tour".
- Multi-model compare (R2): `⋮ → Compare models`, max 2 slots with tap-
  to-pick via the model sheet (last pair persisted), cost-guard confirm
  (`~N tokens in each`), concurrent streaming into labeled side rows,
  Keep A/B (winner recorded to history + chats + token totals, loser
  collapsed to a one-line note), per-side Retry, Dismiss (nothing saved).
  Shared Stop; no RAG/compaction in compare (docs inject as plain text).
- `tests/test_v05_r8r5r2.py`: 13 new tests. 148 tests total, all green.
- No new pip deps.

## Unreleased — v0.5 round R7+R3+R4 (Flet-only)

## Unreleased — v0.5 round R7+R3+R4 (Flet-only)

### Added
- Token metering (R7): per-conversation input/output totals (additive
  `input_tokens`/`output_tokens` migration, accumulated each reply);
  drawer rows show `• ~12.3k tok`; slim context meter under the model
  strip (`used/limit • %`, amber >70%, red >90%, tooltip notes estimates
  + auto-compact state). Estimates only, always `~`, never currency.
- Providers polish (R3): per-tile health row (OK/Failed + latency +
  tested time), live-model count + refresh stamp, capability summary
  line; Test records latency/health, Refresh records count/stamp.
- RAG source UX (R4): tappable `[file §n]` citations open a source
  viewer (chunk text, query-term highlight via TextSpan, § prev/next
  pager with fuzzy file match); `⋮ → Doc index` shows per-chat files,
  chunk counts, toggle state, and Clear index; RAG status line carries a
  "why these" relevance tooltip (strong/related/weak bands).
- `tests/test_v05_r7r3r4.py`: 19 new tests. 135 tests total, all green.
- No new pip deps.

## Unreleased — v0.5 round R1+R6 (Flet-only)

## Unreleased — v0.5 round R1+R6 (Flet-only)

### Added
- Streaming performance (R1): isolated `StreamingBubble` — live flushes
  call `self.update()` on the bubble only, with automatic fallback to
  `page.update()`; `StreamAccumulator` (`app/ui/controllers/streaming.py`,
  first R0 extraction out of `main.py`) coalesces flushes and skips
  updates when the safe-to-render prefix is unchanged; long chats render
  windowed (last 50 + "Show earlier" header with position restore); the
  jump button doubles as a live row-count pill while streaming.
- Find-in-chat (R6): `⋮ → Find in chat` (Ctrl+F, Esc closes), match
  counter `i/n`, wrap-around prev/next, scroll-to-match via row keys
  (`msg-{history_index}`), highlight ring on the current match, window
  auto-expands to hidden matches, index refreshes after each reply.
- `tests/test_v05_r1r6.py`: 17 new tests. 116 tests total, all green.
- No new pip deps.

## Unreleased — v0.4 refinement pack (Flet-only, no multimodal compare)

### Added (refinement)
- Vision-capability fix: OpenRouter routes/IDs default to attempt (no more
  substring misfires on `:free`/VLM IDs); broader `-vl`/maverick/scout
  markers for Groq + Together; vision-mismatch now offers Send anyway
  (remembered per model, badge shows `vision (override)`), Send text-only,
  or Switch model — nothing is lost, staged files + prompt are kept.
- Message lifecycle: user edit-and-resubmit dialog, fork-from-here
  truncation, pin toggle, per-code-block copy cards, `~N tokens` footer,
  thumbs-down reason sheet (Inaccurate/Irrelevant/Incomplete/Harmful + note).
- Input/attachments v2: tap-to-preview zoomable lightbox
  (`InteractiveViewer` pan/zoom), per-file `AttachmentState`
  (reading/ready/too-large/failed) helpers.
- Artifacts v2: per-conversation registry + BottomSheet panel + detail
  dialog with Copy/Save (`.csv/.json/.md` via FilePicker), real
  `LineChart`/`BarChart` rendering for ```chart JSON with table fallback.
- Model picker v2: recents (KeyStore `ui.recents`, max 5), preset chips
  (all/free/vision/docs), capability-matrix dialog (provider × models).
- History v2: `pinned`/`archived` columns (additive idempotent migration),
  All/Pinned/Archived + provider filter chips, in-drawer bulk-select mode
  with delete, pin/archive popup actions, per-filter empty states.
- Theme/a11y/i18n: text-size setting (standard/large/xl), OLED true-black,
  high-contrast switch (Settings → Appearance), RTL row mirroring,
  desktop shortcuts (Ctrl+K history, Esc close, Ctrl+Enter send),
  48px touch targets on bubble actions.
- `tests/test_v041_refine.py`: 27 new tests. 87 tests total, all green.
- `tests/test_v042_vision.py`: 12 new tests (default-allow, markers,
  override bypass, send paths). 99 tests total, all green.
- No new pip deps; multimodal compare stays cut per scope.

## Unreleased — v0.4 UI pack (Flet-only, no multimodal compare)

### Added
- Streaming polish: half-open fence/marker buffering (`split_stream_safe`),
  block cursor, typing/shimmer placeholders, per-bubble thumbs feedback.
- Input pack: send/stop/mic morph (mic explains voice deferred), live morph
  on text/attach change, preview-strip + lightbox builders.
- Artifacts: ```table/json/card fences render as inline cards (max 3);
  `[file §n]` citations render as source cards. Zero-config text fallback.
- History inbox: Today/Yesterday/7d/Older grouping, unread dot, popup
  rename/delete, selected highlight.
- Starter cards in empty state (config-driven presets with optional
  provider/model binding); model sheet adds docs badge.
- 10 original companion SVGs in Phosphor style (offline, our MIT code).
- `tests/test_v040_ui.py`: 18 new tests. 60 tests total, all green.
- No new pip deps; no multimodal compare (per scope cut).

## v0.4.0 — Lockdown + Chat-with-Docs

### Added
- Hardware-backed KEK: random 32-byte key in `flet-secure-storage`
  (Android Keystore), API keys Fernet-encrypted under it. Automatic
  migration (plaintext → device-seed → KEK), idempotent re-runs, with a
  device-seed fallback + Settings badge when the keystore is unavailable.
- Optional app lock (Settings → Security): 4–8 digit PIN (PBKDF2-HMAC-SHA256,
  200k rounds), biometric unlock via Keystore-enforced profile, lock at
  startup + "Lock now", forgot-PIN recovery (wipes lock + keys, keeps chats).
- Local RAG over long docs (stdlib-only TF-IDF + cosine, SQLite
  `doc_chunks`): docs >12k chars are chunked (~1500 chars / 200 overlap)
  and only top-3 excerpts are sent with `[file §n]` citations + grounding
  line; follow-up questions retrieve over the conversation's index.
  Toggle: Settings → Documents → Smart doc search.
- `tests/test_v040.py`: 15 new tests (chunker, TF-IDF ranking, retention,
  chunks store, rekey chain, PIN hashing). 41 tests total, all green.

### Changed
- Doc text retained up to 200k chars for retrieval (plain send path still
  injects the 12k head with the truncation flag).
- `USE_BIOMETRIC` (+ legacy `USE_FINGERPRINT`) Android permissions declared
  for the optional biometric unlock only.
- Version `0.4.0` (`build_number 4`).

### Upgrade notes
- Existing installs re-encrypt keys under the KEK on first launch (one
  async preload, chat stays usable meanwhile).
- Short docs behave exactly as before; long docs now answer from retrieved
  excerpts instead of a truncated head.

## v0.3.0 — Ship + Refresh

Play-compliant release with current provider defaults and always-on key encryption.

### Added
- `cryptography` is now a hard dependency: all `*.key` values are
  Fernet-encrypted at rest (verified in-APK:
  `libcryptography-hazmat-bindings` ships for arm64). Legacy plaintext
  keys migrate automatically on first open.
- `tests/test_v030.py`: 8 new tests (registry freshness, new context
  limits, encrypted-at-rest + migration). 26 tests total, all green.
- `openrouter/free` auto-router as the OpenRouter default — resilient to
  the rotating `:free` lineup.

### Changed
- **Groq**: dropped IDs retired 07/17/26 (`qwen3-32b`, `llama-4-scout`);
  lineup is now `gpt-oss-20b` (default), `gpt-oss-120b`,
  `qwen3.6-27b`, `qwen3.8-27b` (all text-only guards).
- **Anthropic**: new ID scheme — `claude-haiku-4-5` (default),
  `claude-sonnet-5` (1M ctx), `claude-opus-5` (1M ctx).
- **Gemini**: `gemini-3.8-flash` GA is the default (1M in / 65K out).
- **OpenRouter `:free`**: rotated to `z-ai/glm-5.2:free`,
  `minimax/minimax-m3:free`, `qwen3-coder-480b:free`, `kimi-k2.6:free`.
- Rate-limit message now mentions OpenRouter `:free` daily caps.
- Splash art no longer carries a version string (stops rotting each release).
- Version `0.3.0` (`build_number 3`).

### Ship (P5)
- `targetSdkVersion 36` confirmed via `aapt dump badging` — meets the
  Aug 31, 2026 Play requirement.
- Artifacts: `build/apk/multiai-chat-*.apk` (`--split-per-abi`),
  `build/aab/multiai-chat.aab` (Play upload).
- Flet stays on 0.86.5 (latest stable on PyPI; 0.86.6/0.86.7 not
  published) — re-check before v0.4.0.

### Upgrade notes
- Existing installs migrate automatically (FTS index + key encryption).
- Saved Groq `qwen3-32b` / `llama-4-scout` and old Claude/Gemini IDs:
  re-pick in the model sheet or Providers → Refresh live models.

## v0.2.0

New logo, current provider defaults, testable core, safer storage.

### Added
- New app logo + splash: white chat bubble with 3 multi-provider dots
  (teal / indigo / orange) + AI spark on dark `#101418` (`assets/icon.png`,
  `assets/splash.png`). Empty-state and AppBar pick it up automatically.
- `app/core/history_utils.py`: pure `user_text_of`, `assistant_text_of`,
  `short_title`, `filter_conversations` extracted from `main.py` closures.
- `tests/test_v020.py`: 18 stdlib `unittest` tests (SSE parse, attachments,
  registry, history utils, ChatStore round-trip + search, KeyStore round-trip).
  Run: `python -m unittest discover -s tests -v`.
- Chat history full-text search: FTS5 `messages_fts` with LIKE fallback via
  `ChatStore.search_conversations()`; drawer search now matches titles *and*
  message bodies.
- Rename-chat dialog in history drawer (edit icon per row).
- Optional at-rest encryption for `*.key` values: Fernet when `cryptography`
  is installed, with one-time plaintext→encrypted migration. Falls back to
  v0.1.x JSON layout when unavailable so upgrades never lose keys.

### Changed
- **Groq defaults refreshed** (old IDs retired 08/16/26): now
  `openai/gpt-oss-20b` (default), `openai/gpt-oss-120b`, `qwen/qwen3-32b`,
  `meta-llama/llama-4-scout-17b-16e-instruct`. Groq gpt-oss models marked
  text-only for the vision guard.
- **Together AI free tier fixed**: defaults now use `-Free` suffixed IDs
  (`Llama-3.3-70B-Instruct-Turbo-Free`, `DeepSeek-R1-Distill-Llama-70B-free`,
  `Llama-Vision-Free`).
- Gemini adds `gemini-2.5-flash` (default); OpenAI adds `gpt-5-mini` option;
  Anthropic adds `claude-sonnet-4-20250514` option.
- `CONTEXT_LIMITS` extended for gpt-oss / qwen3 / llama-4 / gpt-5-mini;
  retired Llama IDs kept for history compat.
- Version bumped to `0.2.0` (`build_number 2`).

### Upgrade notes
- Existing `data/chat.db` migrates automatically (FTS index backfills).
- Existing `data/preferences.json` keys migrate to encrypted form when
  `cryptography` is present; otherwise they keep working as-is.
- If a saved Groq model stops working, pick `openai/gpt-oss-20b` in the
  model sheet or Providers → Refresh live models.

## v0.1.0

- P0–P4: scaffold, providers (OpenAI-compat + Anthropic/Gemini), streaming
  chat, attachments (images + pdf/txt), SQLite history, export md/json,
  theme, icons/splash.
