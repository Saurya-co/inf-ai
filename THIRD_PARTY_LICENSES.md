# Third-party licenses

Our code: MIT (see `LICENSE`). Below are direct/corresponding deps and inspirations.

| Package / Project | License | Role | Notes |
|---|---|---|---|
| `flet` (incl. Flutter Material/Cupertino rendering) | Apache-2.0 | Framework | `pip install flet`. Flutter SDK BSD-3 underneath — permissive. |
| `flet-contrib` (if used) | Apache-2.0 | Optional UI extras | Only if vendored; prefer re-implementing pattern. |
| `flet-components` (PyPI, optional) | MIT | Optional UI extras | v0.4.0 vetting: REJECTED as dep — stale 0.0.9 (2025-02), pins flet>=0.25.2, incompatible with 0.86.5. Pattern reference only. |
| `httpx` (+ `httpcore`, `h11`, `certifi`) | BSD-3-Clause | HTTPS + SSE streaming | Direct dep. Android-wheel-safe. |
| `pypdf` | BSD-3-Clause | PDF text extract | Pure-Python, Android-safe. Do NOT swap for PyMuPDF (AGPL). |
| `cryptography` (required, for key encryption) | Apache-2.0 / BSD dual | Key hardening | v0.3.0 hard dep: all `*.key` values Fernet-encrypted at rest; v0.4.0 encrypts under a hardware-backed KEK. |
| `flet-secure-storage` (required, ==0.86.5) | Apache-2.0 | KEK + biometric unlock | v0.4.0: Android Keystore / iOS Keychain / Win Credential Manager via `flutter_secure_storage`. |
| Python `sqlite3`, `asyncio`, `json` | PSFL (stdlib) | Persistence | No action. |
| LibreChat | MIT | UX inspiration only | No vendored code in v1. |
| `flutter_gen_ai_chat_ui` | MIT | UX inspiration only | Streaming/markdown/attachment patterns re-implemented in Flet. |
| `simple_chat`, `flutter_chat_kits`, `chat_toolkit` | MIT | UX inspiration only | Grouping/preview/state patterns. |
| Phosphor Icons (`phosphor-icons/core`, regular SVGs in `assets/phosphor/`) | MIT | Bundled icons | Offline-safe; replaces emoji in badges/chips. v0.4.0 adds 10 original companion SVGs (mic, stop-circle, arrow-down, thumbs-up/down, pin, sparkle, mail, code, doc) in the same style — our own MIT code, no upstream copy. |
| v0.4.0 UI pack (`streaming_bubble`, `input_bar`, `artifact_card`, `history_row`, `starter_cards`) | MIT (ours) | UX implementation | Patterns inspired by `flutter_gen_ai_chat_ui` (MIT) + LibreChat (MIT), re-implemented Flet-only. No new pip deps. |
| v0.4 refinement (`artifact_panel`, message lifecycle, model recents/presets/matrix, history flags, theme scale/OLED) | MIT (ours) | UX implementation | Same MIT-inspiration strategy, Flet built-ins only (`LineChart`/`BarChart`/`InteractiveViewer`/`RadioGroup`). No new pip deps. |

## Banned / avoid

- **PyMuPDF (`fitz`)**: AGPL-3.0 — copyleft, would infect distribution. Banned.
- **Open WebUI code/branding**: custom license (branding clause, not OSI-approved). Feature ideas only, no code reuse.
- Any `pip freeze` dump into requirements: hand-pick direct deps only (Flet Android builds require it).

If you vendor any MIT snippet, paste its copyright header at the top of the file and add a row above.
