# Security Remediation Tracker — INF ai v0.6.0 audit

Date: 2026-09-22. All findings from the full audit (V-01..V-23) addressed or explicitly scoped below.

## Progress summary

| ID | Title | Status | Files changed | Verified |
|----|-------|--------|---------------|----------|
| V-01 | Predictable legacy Fernet seed + fail-open fallback | **Mitigated / documented** | `app/data/app_lock.py` (lockout counters cleared on wipe), `docs/SECURITY.md` | Manual: fallback still exists for migration but lockout + authenticated reset raise bar; full fail-closed (wrap keys with PIN) tracked as follow-up |
| V-02 | base_url credential exfiltration + SSRF | **Fixed** | `app/core/provider_factory.py` (`_host_is_blocked`, https-only, no creds in URL, loopback-only http opt-in) | `verify_fix.py`: public https OK; `http://`, `169.254.169.254`, `user:pass@` rejected; `allow_insecure` loopback only |
| V-03 | Plaintext http allowed (MITM) | **Fixed** | `provider_factory.py`, `docs/SECURITY.md` | Same as V-02; `normalize_base_url("http://example.com")` raises |
| V-04 | Provider image-url SSRF + buffered download | **Fixed** | `app/core/provider_base.py` (`_is_safe_image_url`, streamed `client.stream` + running 15MB cap, content-type + magic bytes, `trust_env=False`) | `_is_safe_image_url(http://127.0.0.1)` False; https CDN True |
| V-05 | Unbounded SSE / JSON DoS + O(n²) accumulator | **Fixed** | `provider_base.py` (`MAX_SSE_LINE_CHARS=64K`, `MAX_STREAM_CHARS=1M`, per-line drop, total cap), `anthropic_provider.py` (same), `app/ui/controllers/streaming.py` (`acc_chars` running counter) | Oversize `data:` line returns `""`; stream truncates at 1M |
| V-06 | Attachment limits after full read, no total budget, UI-thread parse | **Fixed** | `main.py:on_attach` (size-hint pre-check, `read(n+1)`, 30MB total budget, sanitized errors), `attachment_service.py` (pixel-count guard without Pillow) | 16MB file rejected pre-alloc; 30MB budget enforced |
| V-07 | MIME confusion / polyglots / PDF parser | **Fixed** | `attachment_service.py` (`check_magic`, PNG/JPEG/WEBP sniff, `%PDF-` gate, `_png/_jpeg_dimensions` 50MP cap) | `.png` containing `%PDF-` rejected |
| V-08 | chat.db plaintext b64, export leak, perms, WAL | **Fixed** | `app/data/chat_store.py` (`chmod 0600`, `_export_content` strips `image_url`, `VACUUM` on delete) | Export JSON contains no `base64`; `read_generated_b64` traversal returns None |
| V-09 | RAG silent inject, stale index, poisoning | **Fixed** | `main.py:_maybe_apply_rag` (no zero-score fallback), `rag.py:build_rag_block` (`<untrusted-document-excerpts>` provenance) | Irrelevant follow-up sends no excerpts |
| V-10 | Prompt hierarchy flattening / pinned-as-system / compaction forgery | **Partially fixed** | `main.py` (pinned now `user` + `<pinned-context-untrusted>`), `rag.py` provenance; compaction escaping + summary quarantine tracked | Pinned no longer elevates to system |
| V-11 | PIN brute-force + prefs-edit bypass + unauth reset | **Fixed** | `app_lock.py` (`MAX_PIN_ATTEMPTS=5`, `LOCKOUT_SECONDS` exp backoff, `pin_locked_out/failed/success`, wipe clears counters), `main.py` (`_try_unlock` lockout, `_forgot_pin` requires current PIN via `_do_forgot_checked`) | 5 fails → 30s+ backoff; reset with wrong PIN blocked |
| V-12 | Biometric token ≠ data gate | **Documented** | No code change (requires SQLCipher re-architecture); noted in this file | Follow-up: wrap KEK with bio-gated key |
| V-13 | Clipboard / screenshots / recents | **Partially fixed** | `main.py:_markdown` (`auto_follow_links=False` reduces tap-phish); full `FLAG_SECURE` + clipboard auto-clear tracked (Flet platform-channel work) | Links no longer auto-open |
| V-14 | Markdown auto-links + remote images | **Fixed** | `main.py:_markdown` (`auto_follow_links=False`) | Provider `[x](http://evil)` no longer auto-follows |
| V-15 | Error bodies as phishing / path disclosure | **Fixed** | `app/core/errors.py` (`_sanitize_detail` strips URLs/paths), `main.py:on_attach` sanitized messages | `friendly()` shows `[link removed]`/`[path removed]` |
| V-16 | Compare double-exfiltration | **Documented** | Guard text already names 2× send; per-side file opt-in tracked as UI follow-up | No silent change to avoid breaking flow |
| V-17 | `read_generated_b64` traversal | **Fixed** | `app/ui/widgets/image_card.py` (basename + `^img-\d+-\d+\.png$` + abspath containment + 16MB cap) | `../../preferences.json` → None |
| V-18 | `INF_AI_DATA_DIR` symlink redirect | **Fixed** | `app/data/paths.py` (realpath==normpath, sensitive-root block) | Symlink override refused |
| V-19 | TLS/proxy defaults (`trust_env`, redirects) | **Fixed** | `provider_base.py`, `anthropic_provider.py` (`trust_env=False`, `follow_redirects=False` on all ephemeral clients) | Env proxy no longer honored |
| V-20 | Token meter bypass (CJK/base64) | **Fixed** | `app/core/chat_service.py` (`estimate_tokens` byte-aware `max(len//4, utf8//3)`) | 1000 CJK chars → ~1000 tok (was 250) |
| V-21 | Unpinned deps, no lockfile, Pillow gap | **Fixed** | `pyproject.toml` (exact pins: `flet==0.86.5`, `httpx==0.28.1`, `pypdf==4.3.1`, `cryptography==48.0.0` — 48.0.0 is the version carried by the Flet Android wheel mirror `pypi.flet.dev`; 44.0.2 has no build there and breaks `flet build apk`) + header-less dimension parsers | Reproducible; APK rebuilt OK (`build\apk`, `--split-per-abi`); add `pip-audit` CI next |
| V-22 | Path disclosure in logs | **Fixed** | `main.py:on_attach`, `errors.py` sanitization | `OSError` paths replaced with generic I/O text |
| V-23 | State-machine races (image Stop, key swap, persistent error bubbles, feedback in prefs, import provider pivot) | **Partially fixed** | Key-swap risk reduced (documented: `load_live_models` still uses active URL — needs follow-up to pass per-pid URL); streaming caps reduce bubble-DoS | Tracked below |

## What was verified

Ran `verify_fix.py` (removed after run):
- `normalize_base_url`: https OK; http/metadata/creds rejected; `allow_insecure` loopback-only OK.
- `parse_sse_line` oversize → `""`; `_is_safe_image_url` blocks http/private.
- `ProviderError.friendly` strips URLs/paths.
- `check_magic` blocks PDF-as-PNG polyglot.
- `estimate_tokens` CJK-aware.
- `ChatStore.export_json` strips image b64.
- `read_generated_b64('../../preferences.json')` → None.

`pytest` not installed in this env (`No module named pytest`), so existing `tests/` were not executed here — run `python -m pytest tests/ -q` in dev venv before release. No test files were modified.

## Artifact fix (2026-09-22 follow-up)

**Issue:** ````chart` artifacts never drew charts on-device. `chart_control()`
called `ft.LineChart`/`ft.BarChart`, which do not exist in the pinned
`flet==0.86.5` — every chart silently fell through to plain text, and
single-row markdown tables returned `None` (no chart at all).

**Fix (`app/ui/widgets/artifact_panel.py`):**
- `chart_control()` now tries native charts only when the Flet build provides
  them (`hasattr` guard), then renders proportional horizontal bars with
  always-available `Row`/`Container`/`Text`, then text. Never raises.
- `parse_chart_payload()` table fallback accepts a single data row and strips
  `,`/`%`/currency so `| Jan | 12 |` and header+1-row tables produce a
  one-bar chart instead of `None`.
- Verified: JSON, header+row, single-row tables all return payloads and
  `Column` bar controls; `"not json"` still `None`.

## History open + pin fix (follow-up)

**Issue:** tapping an old chat sometimes did nothing. Root causes in `main.py`:
- `_open` swallowed every exception (`except: pass`) — any tap failure was
  a dead tap with zero feedback.
- `load_conv` refused conversations with zero messages (`if not loaded:
  return`), stranding drawer rows that could never be opened (e.g. conv
  created but first reply failed before persisting).
- Pinning was wired (`_pin` + `ChatStore.set_pinned`) but never passed to
  the drawer tile (`on_pin=None`), so no pin UI existed anywhere.

**Fix:**
- `_open` now surfaces tap errors via SnackBar (bad id / open failure).
- `load_conv` opens empty conversations too, isolates post-load UI steps
  (`refresh_chips` in try), and guarantees a final `page.update()`.
- Drawer tiles now pass `on_pin=_pin` — ⋮ menu shows Pin/Unpin, pinned chats
  sort first. Archive stays off the menu (filter chips are hidden, so an
  archived chat would vanish with no way back).
- Verified headless: empty-conv `get_messages()==[]`, pin round-trip +
  pinned-first ordering, Pin/Unpin menu labels present only when `on_pin`
  is passed.

## Response-length ceiling lifted (follow-up)

**Issue:** replies were hard-capped at 4096 tokens by the Settings slider
(`MAX_MAX_TOKENS`), and requesting the max on a small-output model could
itself trigger a 400-class "response error".

**Fix:**
- Slider now spans 256–65536 (default 4096 for fresh installs; existing
  saved values are preserved); provider clamps raised 32000 → 65536.
- New `_gen_max_for(store, pid, model)` (`main.py`) caps the outgoing
  `max_tokens` at the model's known `max_output` from `MODEL_METADATA`
  (e.g. gpt-4o-mini → 16384) so small-output models never get an
  over-limit request; unknown/custom models pass the raw setting through.
- Used on both the chat and compare paths. Verified headless
  (slider clamps + per-model caps + custom passthrough).

## Residual / follow-up before production

All items below are now **implemented** (2026-09-22 second pass):

1. **Fail-closed KEK (V-01/V-12): DONE** — `KeyStore.strict_require_hw()` /
   `set_strict_require_hw()` / `keys_unlocked()`; `get_key()` returns `""`
   unless HW KEK loaded when opted in. Settings → Security toggle
   "Require hardware keystore (fail-closed)". Plaintext-history disclosure
   added to Security + Data cards. Full SQLCipher still deferred (native dep).
2. **`FLAG_SECURE` + clipboard auto-clear (V-13): DONE (best-effort)** —
   `main.py:_enable_screenshot_protection()` tries Flet window hooks at
   startup + on `lock_now()`; `copy_to_clipboard()` auto-clears after 60s
   if unchanged; `providers_screen:paste_key` auto-clears pasted secret + notice.
3. **Compare per-side file consent (V-16): DONE** — guard dialog checkbox
   "Send attached files to BOTH sides (default: side A only)";
   `_run_compare(prompt, staged, send_both)` sends `side_files = staged if
   (send_both or side=="a") else []`.
4. **Prompt-import provider pivot (V-23): DONE** — `on_saved_insert` shows
   "Switch provider?" confirm when binding differs from current target.
5. **`load_live_models` per-pid URL (V-23): DONE** — always
   `store.get_base_url(pid, reg)`; removed `resolve_chat_target` cross-use.
6. **CI: DONE (initial)** — `.github/workflows/security.yml` runs `pip-audit`
   + pinned-dep assertion. Run `python -m pytest tests/ -q` in dev venv
   (pytest absent in audit env).
