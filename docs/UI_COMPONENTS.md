# UI Components — MIT-licensed strategy for Flet

> Key constraint: **Flet (Python) cannot `pip install` Flutter/Dart packages.**
> MIT Flutter chat kits below are **UX references to re-implement in Python**, not code dependencies.
> Direct code deps must be Python + Android-wheel-safe.

## 1. What we actually ship (code)

### A. Flet built-ins — Apache-2.0 (permissive, bundled, preferred for 95% of UI)

Source: `flet-dev/flet` (Apache-2.0). Already included when you `pip install flet`. No extra license action beyond `THIRD_PARTY_LICENSES.md`.

Use these, don't reinvent:

| Need | Flet control |
|---|---|
| App shell, routing | `ft.View`, `ft.Page.go`, `NavigationDrawer`, `NavigationBar`, `AppBar` |
| Chat list | `ListView(auto_scroll=True)`, `Container`, `CircleAvatar`, `Badge` |
| Message bubble | `Markdown` (code + tables) inside `Container` (rounded, tonal colors) |
| Input bar | `TextField(multiline, shift_enter)`, `IconButton`, `FloatingActionButton` |
| Model picker | `Dropdown` / `BottomSheet` + `SearchBar`, grouped by provider, `free` badge |
| Attach | `FilePicker(pick_files with_data=True)`, `Chip` previews, `ProgressRing` |
| Dialogs/feedback | `AlertDialog`, `BottomSheet`, `SnackBar`, `Banner` |
| Theming | Material 3 `ThemeMode.LIGHT/DARK`, `ColorScheme` seed |

Custom composites (our own MIT code, `app/ui/widgets/`):
`MessageBubble`, `StreamingBubble` (isolated control, `self.update()`), `ModelPicker`, `AttachBar`, `ProviderCard`, `CapabilityBadge`, `EmptyState`, `ErrorRetry`.

Build with `@ft.component` (recommended) or `@ft.control` inheritance per Flet cookbook. Mark streaming widgets `is_isolated=True`.

### B. Optional Python lib — MIT

- **`flet-components` (PyPI, MIT)** — extra buttons/cards/modals. Optional only. Vet before use: check maintenance + Android build still passes. If in doubt, skip — Flet built-ins cover v1.

### C. `flet-contrib` — Apache-2.0 (permissive, not MIT)

Community controls (e.g. `ColorPicker`). Permissive and usable, but Apache-2.0, not MIT. Only take what you need; prefer copying the *pattern* into our widgets.

## 2. MIT references — UX patterns only (do not add as deps)

| Project | License | What to steal (pattern, not code) |
|---|---|---|
| **LibreChat** (`danny-avila/LibreChat`) | **MIT** | Multi-provider sidebar, presets/model picker grouping, artifacts panel, prompt presets, side-by-side compare (v2) |
| **`flutter_gen_ai_chat_ui`** (pub.dev) | **MIT** | Word-by-word streaming animation, markdown+code highlight in bubbles, `rich` full-width widget messages, mic/send toggle, welcome screen + example prompts, file-attachment with progress + lightbox |
| **`simple_chat`** (Tealseed-Lab) | **MIT** | Message grouping, custom message cell, image preview |
| **`flutter_chat_kits` / `chat_toolkit`** | **MIT** | `ChatInbox` conversation row, `ChatInput`, read/loading/failed states, scroll-to-bottom + “new messages” pill |

Re-implement each pattern with Flet controls above (e.g. streaming = async generator + `Markdown` update throttle ~100ms; lightbox = `AlertDialog` with `Image`).

## 3. Explicitly avoid / mislicensed for our needs

- **Open WebUI** — custom license with branding clause, **not OSI-approved**. Do not copy branding/gated code. Treat as feature checklist only.
- **`flyerhq/flutter_chat_ui`** — Apache-2.0 (fine license, but Dart-only; reference only, not MIT).
- **PyMuPDF (`fitz`)** — AGPL-3.0. **Banned in v1.** Use `pypdf` (BSD) for PDF text. (AGPL would infect distribution.)
- Any Dart/Flutter package as a “Flet dependency” — technically impossible via pip; would require a Flet Flutter extension build. Out of scope for v1.

## 4. v0.5 widget map (Flet-only, no new deps)

```
ChatScreen
├─ NavigationDrawer (grouped inbox: Today/Yesterday/7d/Older, unread dot,
│   All/Pinned/Archived + provider filters, in-drawer bulk-select + delete,
│   pin/archive popup actions, per-filter empty states, ~tok subtitles)
├─ AppBar (model pill + FREE/vision/docs badges, Artifacts entry)
├─ ContextMeter (~used/limit bar under model strip, 70/90% bands)
├─ FindBar (field + i/n counter + prev/next, Ctrl+F)
├─ CompareBar (side A/B chips + exit; verdict row: Keep A/B, Retry A/B, Dismiss)
├─ ListView (windowed: last 50 + Show earlier; rows keyed msg-{i})
│   └─ MessageBubble [user: FilledTonal + edit/fork/pin | assistant: Surface]
│       ├─ Markdown (buffered: half-open fences held back, cursor ▍)
│       ├─ CodeCopyCards (per-fence copy, ft.Markdown workaround)
│       ├─ ArtifactCard (```table/json/card → DataTable/Card, max 3)
│       ├─ ChartCard (```chart JSON → LineChart/BarChart, table fallback)
│       ├─ CitationCard ([file §n] → source viewer: highlight + § pager)
│       └─ Actions (copy, retry, thumbs + reason sheet, ~N tokens footer)
├─ ArtifactsPanel (BottomSheet registry per conversation + detail + save)
├─ AttachBar (FilePicker chips + tap-to-preview zoom lightbox + statuses)
├─ PromptLibrary (BottomSheet CRUD + editor; Saved section in empty state)
└─ InputBar (attach + library + TextField + send/stop/mic morph)
OnboardingTour (first-run BottomSheet: provider → key+Test → model → starter)
ProvidersScreen: ProviderCard × N (+ latency/health badges, live counts, capability line)
SettingsScreen: theme, text size, OLED, high contrast, temperature,
  max_tokens, RAG toggle, export all/prompts, import prompts, wipe data, replay tour
ModelSheet: search + Recent section + preset chips + capability matrix (+ compare slot mode)
```

New modules: `streaming_bubble.py` (incl. isolated `StreamingBubble`),
`input_bar.py`, `artifact_card.py`, `artifact_panel.py`, `history_row.py`,
`starter_cards.py`, `find_bar.py`, `source_viewer.py`, `prompt_library.py`, `onboarding.py`,
`controllers/streaming.py` (R0 extraction:
`StreamAccumulator`, `window_slice`, `window_for_index`), `controllers/metering.py` (R7:
`format_tokens`, `meter_band`, `context_used`), `controllers/compare.py` (R2:
pair persistence/validation, guard text, verdict note).
Tests: `tests/test_v040_ui.py` (18) + `tests/test_v041_refine.py` (27) + `tests/test_v05_r1r6.py` (17) + `tests/test_v05_r7r3r4.py` (19) + `tests/test_v05_r8r5r2.py` (13).
Tests: `tests/test_v040_ui.py` (18) + `tests/test_v041_refine.py` (27) + `tests/test_v05_r1r6.py` (17) + `tests/test_v05_r7r3r4.py` (19).
Shortcuts (desktop): Ctrl+K history, Ctrl+F find, Esc close find/sheets, Ctrl+Enter send.
Chat list renders windowed (last 50 + Show earlier); rows keyed `msg-{i}` for find nav.

## 5. Attribution

Keep `THIRD_PARTY_LICENSES.md` updated. For MIT references used as inspiration (no vendored code), a “UX inspired by …” line suffices. If any snippet is vendored, copy its full MIT header into the file + row in the table.
