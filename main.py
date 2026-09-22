"""INF ai — student AI toolkit (P3 attachments + P4 history, Phase A+B UI refinement).

Run: `flet run main.py`
Bundle ID: com.saurya.multiai
"""

import sqlite3
import time

import asyncio
import json
import re

import flet as ft

from app.config import (
    ALLOWED_DOC_EXTS,
    ALLOWED_IMAGE_EXTS,
    IMAGE_GEN_TIMEOUT,
    IMAGE_SIZES,
    MODEL_METADATA,
    PROVIDER_IDS,
    PROVIDERS,
    available_image_models,
    available_models,
    set_live_models,
    supports_docs,
    supports_image_gen,
    supports_vision,
    vision_override_key,
)
from app.core.attachment_service import build_chat_messages, doc_block, prepare_file
from app.core import rag as rag_mod
from app.core.chat_service import (
    build_multimodal_messages,
    compaction_target_count,
    estimate_tokens,
    resolve_chat_target,
    should_compact,
)
from app.core.errors import ProviderError
from app.core.latex import latex_to_unicode
from app.core.history_utils import assistant_text_of, filter_conversations, short_title, user_text_of
from app.core.provider_factory import get_provider
from app.core.types import Attachment, Message
from app.data.app_lock import (
    BioUnlock,
    clear_lock,
    lock_prefs,
    verify_pin,
    wipe_keys,
)
from app.data.chat_store import ChatStore
from app.data.key_store import KeyStore
from app.data.kek_store import KekStore, fernet_for_kek
from app.ui.phosphor import ph
from app.ui.screens.providers_screen import build_providers_view
from app.ui.screens.settings_screen import build_settings_view, get_max_tokens
from app.ui.theme import (
    STREAM_CURSOR,
    STREAM_THROTTLE_MS,
    align_for_direction,
    app_theme,
    now_hhmm,
    ts,
)
from app.ui.widgets.attach_bar import build_attachment_chip
from app.ui.widgets.empty_state import build_empty_state
from app.ui.widgets.artifact_card import (
    artifact_control,
    citation_card,
    extract_artifacts,
    extract_citations,
)
from app.ui.widgets.artifact_panel import (
    ArtifactRegistry,
    artifact_to_csv,
    artifact_to_text,
    build_artifact_panel,
    chart_control,
    download_name,
    parse_chart_payload,
)
from app.ui.widgets.history_row import (
    HISTORY_FILTERS,
    apply_history_filter,
    empty_history_message,
    group_conversations,
    inbox_tile,
)
from app.ui.widgets.input_bar import InputState, build_lightbox, send_button_mode
from app.ui.widgets.camera_sheet import camera_filename, open_camera_capture
from app.ui.widgets.starter_cards import coerce_starters
from app.ui.controllers.compare import (
    COMPARE_SLOTS,
    default_pair,
    guard_text,
    loser_note,
    pair_from_json,
    pair_to_json,
    validate_pair,
)
from app.ui.controllers.metering import (
    context_limit_for,
    context_used,
    meter_band,
    meter_label,
)
from app.ui.controllers.streaming import (
    HISTORY_WINDOW,
    StreamAccumulator,
    StreamRevealPacer,
    window_for_index,
    window_slice,
)
from app.ui.widgets.find_bar import (
    build_match_index,
    format_counter,
    row_key,
    set_row_highlight,
    step_index,
)
from app.ui.widgets.source_viewer import (
    bands_tooltip,
    find_excerpt_span,
    parse_citation_label,
    score_bands,
)
from app.ui.widgets.streaming_bubble import (
    StreamingBubble,
    detect_text_direction,
    shimmer_placeholder,
    split_stream_safe,
    typing_indicator,
)
from app.ui.widgets.message_bubble import (
    FEEDBACK_REASONS,
    assistant_bubble,
    build_feedback_sheet,
    code_copy_cards,
    error_bubble,
    fork_history,
    parse_code_blocks,
    user_bubble,
)
from app.ui.widgets.prompt_library import (
    SavedPrompt,
    add_prompt,
    coerce_prompts,
    delete_prompt,
    load_prompts,
    prompts_from_json,
    prompts_to_json,
    save_prompts,
    update_prompt,
)
from app.ui.widgets.onboarding import (
    any_key_set,
    mark_onboarded,
    needs_onboarding,
    next_step,
    prev_step,
    step_dots,
    step_index,
    WIZARD_STEPS,
)
from app.ui.widgets.model_sheet import (
    PRESETS,
    apply_preset_filter,
    build_model_list,
    capability_matrix,
    iter_model_rows,
    parse_recents,
    push_recent,
)
from app.ui.widgets.model_detail_sheet import build_model_detail_sheet
from app.ui.widgets.image_card import (
    image_card,
    image_note,
    parse_image_note,
    png_to_b64,
    read_generated_b64,
    save_generated_png,
)

APP_TITLE = "INF ai"
BUNDLE_ID = "com.saurya.multiai"

# INF ai study tutor preamble: prepended as a system message so every
# reply teaches step-by-step. Never rendered as a bubble (system role).
STUDY_PREAMBLE = (
    "You are INF ai, a study tutor for school and college students. "
    "Explain step by step in simple words with one example, then end "
    "with 1 quick check question. Write formulas and equations in plain "
    "Unicode (H₂O, CO₂, →, ×, √) — never LaTeX or backslash commands, "
    "since the app cannot render TeX."
)


def _tex(raw: str) -> str:
    """Render-only LaTeX → Unicode (never breaks chat on failure)."""
    try:
        return latex_to_unicode(raw)
    except Exception:
        return raw


def _pad(h: int, v: int) -> ft.padding.Padding:
    """Flet >=0.86 removed padding.symmetric/all helpers — build Padding directly."""
    return ft.padding.Padding(left=h, top=v, right=h, bottom=v)


def _gen_max_for(store, pid: str, model: str) -> int:
    """User's max-response setting, capped at the model's known max output.

    Requesting more tokens than a model supports yields a 400-class
    "response error" on several providers, while models with big outputs
    (Gemini/GPT-5 class) accept large values. Unknown/custom models keep
    the raw user setting (provider clamp applies downstream).
    """
    want = get_max_tokens(store)
    try:
        meta = (MODEL_METADATA.get(pid, {}) or {}).get(model)
        if isinstance(meta, dict):
            cap = int(meta.get("max_output", 0) or 0)
            if cap > 0:
                want = min(want, cap)
    except Exception:
        pass
    return max(1, want)


def main(page: ft.Page) -> None:
    page.title = APP_TITLE
    page.theme = app_theme()
    page.dark_theme = app_theme()
    # Phone-first: no dead page margin — screens manage their own padding
    # so the 6" viewport goes to content, not gutters.
    page.padding = 0
    page.spacing = 0
    saved_theme = "dark"
    store = KeyStore(page)
    try:
        saved_theme = store.get("ui", "theme", "dark")
    except Exception:
        pass
    page.theme_mode = (
        ft.ThemeMode.LIGHT if saved_theme == "light" else ft.ThemeMode.DARK
    )
    page.vertical_alignment = ft.MainAxisAlignment.START
    page.horizontal_alignment = ft.CrossAxisAlignment.STRETCH
    try:
        page.data = {}
    except Exception:
        pass

    # v0.4.0: hardware-backed KEK loads async; chat stays usable on the
    # legacy seed until rekey completes (keys decrypt either way).
    kek = KekStore(page)

    async def _preload_kek() -> None:
        try:
            raw, secure = await kek.load()
        except Exception:
            return
        try:
            store.rekey(fernet_for_kek(raw))
        except Exception:
            pass
        store.secure_backing = secure
        try:
            inner = getattr(settings_view, "content", None)
            hooks = getattr(inner, "data", None)
            fn = hooks.get("refresh_security") if isinstance(hooks, dict) else None
            if callable(fn):
                fn()
        except Exception:
            pass
        show_snack(
            "Hardware key storage: on."
            if secure
            else "Keystore unavailable — using device-level key protection."
        )

    try:
        chats = ChatStore()
        store_note = ""
    except Exception as e:  # noqa: BLE001 — stay usable memory-only
        chats = None
        store_note = f" (history off: {e})"

    history: list[Message] = []
    attachments: list[Attachment] = []
    state = {
        "streaming": False,
        "stop": False,
        "last_assistant": "",
        "conv_id": None,
    }

    # ---- v0.4 refinement state (Flet-only, in-memory) ----
    # NOTE: must live here (top of main) — model-sheet preset chips and
    # other closures built below read model_ui/hist_ui at construction time.
    artifacts = ArtifactRegistry()
    hist_ui = {"filter": "all", "provider": "", "bulk": False, "checked": set(), "shown": None}
    model_ui: dict = {"preset": "all", "recents": []}
    prompt_ui: dict = {"items": load_prompts(store)}  # v0.5 R8 library
    if not prompt_ui.get("items"):  # INF ai: seed student pack once
        try:
            seed = [
                SavedPrompt(title="Explain simply", prompt="Explain this topic in simple steps with one example"),
                SavedPrompt(title="Solve step-by-step", prompt="Solve this maths/science problem step by step and check the answer"),
                SavedPrompt(title="Summarise chapter", prompt="Summarise my pasted notes into key points + 3 likely exam questions"),
                SavedPrompt(title="Quiz me", prompt="Quiz me on this topic — ask one question at a time and give feedback"),
                SavedPrompt(title="Study plan", prompt="Make a 7-day study plan for my exam with daily tasks"),
            ]
            prompt_ui["items"] = seed
            save_prompts(store, seed)
        except Exception:
            pass
    compare_ui: dict = {"active": False, "pick_slot": None,  # v0.5 R2 compare
                        "pair": None, "busy": False}
    try:
        model_ui["recents"] = parse_recents(store.get("ui", "recents", "[]"))
    except Exception:
        model_ui["recents"] = []
    # Pinned user messages: persisted so context pinning survives restart.
    def _load_pinned() -> set:
        try:
            raw = store.get("ui", "pinned_msgs", "[]")
            data = json.loads(raw or "[]")
            return {str(x) for x in data if str(x).strip()} if isinstance(data, list) else set()
        except Exception:
            return set()

    def _save_pinned(pinned: set) -> None:
        try:
            store.set("ui", "pinned_msgs", json.dumps(sorted(pinned)[:50], ensure_ascii=False))
        except Exception:
            pass

    def _load_feedback() -> list:
        try:
            raw = store.get("ui", "feedback", "[]")
            data = json.loads(raw or "[]")
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _save_feedback_entry(entry: dict) -> int:
        try:
            items = _load_feedback()
            items.append(entry)
            items = items[-50:]
            store.set("ui", "feedback", json.dumps(items, ensure_ascii=False))
            return len(items)
        except Exception:
            return 0

    def _pinned_block() -> str:
        try:
            pinned = state.get("pinned_msgs", set())
            texts = sorted(t for t in pinned if str(t).strip())
            if not texts:
                return ""
            return "Pinned context (always include):\n" + "\n---\n".join(texts[:10])[:4000]
        except Exception:
            return ""

    try:
        state["pinned_msgs"] = _load_pinned()
    except Exception:
        state["pinned_msgs"] = set()
    try:
        saved_preset = (store.get("ui", "preset", "all") or "all").strip() or "all"
        model_ui["preset"] = saved_preset
    except Exception:
        pass

    picker = ft.FilePicker()
    page.services.append(picker)

    # ---- transient feedback goes to SnackBar, not the chat ----
    snack = ft.SnackBar(content=ft.Text(""), behavior=ft.SnackBarBehavior.FLOATING)
    page.overlay.append(snack)

    def show_snack(text: str) -> None:
        try:
            snack.content.value = text  # type: ignore[union-attr]
            snack.open = True
            page.update()
        except Exception:
            pass

    def _enable_screenshot_protection() -> None:
        """Best-effort FLAG_SECURE equivalent (Flet has no stable API).

        Tries known Flet window hooks; silently no-ops when unavailable.
        Lock/PIN dialogs remain modal regardless — this only hardens
        recents/screenshots where supported.
        """
        for attr_chain in (("window", "prevent_screenshot"),
                           ("window", "secure"),):
            try:
                obj = page
                for a in attr_chain[:-1]:
                    obj = getattr(obj, a, None)
                    if obj is None:
                        break
                if obj is not None and hasattr(obj, attr_chain[-1]):
                    setattr(obj, attr_chain[-1], True)
            except Exception:
                pass

    try:
        _enable_screenshot_protection()
    except Exception:
        pass

    async def copy_to_clipboard(value: str, autoclear_s: int = 60) -> None:
        await page.clipboard.set(value)
        show_snack("Copied — clipboard auto-clears in 60s.")
        # Auto-clear sensitive clipboard copies (keys, replies, code).
        try:
            await asyncio.sleep(max(10, min(300, int(autoclear_s))))
            try:
                cur = await page.clipboard.get()
            except Exception:
                cur = None
            if cur == value:
                await page.clipboard.set("")
            # Never surface autoclear failures to chat.
        except Exception:
            pass

    status = ft.Text(
        "Pick a study model, then ask. Attach photos/docs with the + button."
        + store_note,
        size=11,
        max_lines=1,
        overflow=ft.TextOverflow.ELLIPSIS,
        color=ft.Colors.ON_SURFACE_VARIANT,
    )
    chat = ft.ListView(expand=True, spacing=12, auto_scroll=True)
    chips_row = ft.Row(wrap=True, spacing=6)

    # ---- empty state (ChatGPT-like: just our logo, centered) ----
    empty_state = ft.Container(
        content=ft.Column([], spacing=0, tight=True),
        expand=True,
        visible=False,
    )
    # Filled in later once chat_wrap / empty_wrap exist (see chat_view).
    _wrappers: dict = {}

    def refresh_empty() -> None:
        is_empty = len(chat.controls) == 0 and not state["streaming"]
        empty_state.visible = is_empty
        try:
            if "chat_wrap" in _wrappers:
                _wrappers["chat_wrap"].visible = not is_empty
            if "empty_wrap" in _wrappers:
                _wrappers["empty_wrap"].visible = is_empty
        except Exception:
            pass
        try:
            fab.visible = len(chat.controls) > 2
        except Exception:
            pass

    def on_example_prompt(prompt: str) -> None:
        input_box.value = prompt
        page.update()
        page.run_task(on_send, None)

    def on_starter(s) -> None:
        # Starter may bind a provider/model (config-driven presets).
        try:
            if getattr(s, "provider", "") and getattr(s, "provider", "") in PROVIDERS:
                provider_dd.value = s.provider
                refresh_models(None)
            if getattr(s, "model", ""):
                model_dd.value = s.model
                persist_model(None)
        except Exception:
            pass
        on_example_prompt(s.prompt)

    def on_saved_insert(s) -> None:
        # v0.5 R8: saved prompts insert into the field (no auto-send),
        # applying an optional provider/model binding like starters do.
        # Provider pivots require explicit confirm (imported JSON is untrusted).
        try:
            cur_pid = (provider_dd.value or "").strip()
        except Exception:
            cur_pid = ""
        want_pid = getattr(s, "provider", "") or ""
        if want_pid and want_pid in PROVIDERS and want_pid != cur_pid:
            dlg = ft.AlertDialog(
                modal=True,
                title=ft.Text("Switch provider?"),
                content=ft.Text(
                    f"This prompt wants {want_pid} / {getattr(s, 'model', '') or '—'}. "
                    f"Switching sends future prompts (and files) to that vendor.",
                    size=12, selectable=True),
                actions=[
                    ft.TextButton(content=ft.Text("Keep current"),
                                  on_click=lambda _: (_close_pivot(False))),
                    ft.FilledButton(content=ft.Text(f"Switch to {want_pid}"),
                                    on_click=lambda _: (_close_pivot(True))),
                ],
            )

            def _close_pivot(go: bool) -> None:
                dlg.open = False
                if go:
                    try:
                        provider_dd.value = want_pid
                        refresh_models(None)
                        if getattr(s, "model", ""):
                            model_dd.value = s.model
                            persist_model(None)
                    except Exception:
                        pass
                try:
                    input_box.value = s.prompt
                    page.update()
                except Exception:
                    pass
                show_snack("Prompt inserted — edit, then Send.")

            page.show_dialog(dlg)
            return
        try:
            if want_pid and want_pid in PROVIDERS:
                provider_dd.value = want_pid
                refresh_models(None)
            if getattr(s, "model", ""):
                model_dd.value = s.model
                persist_model(None)
        except Exception:
            pass
        try:
            input_box.value = s.prompt
            page.update()
        except Exception:
            pass
        show_snack("Prompt inserted — edit, then Send.")

    def refresh_empty_state() -> None:
        # Rebuild welcome content (picks up prompt-library changes).
        try:
            empty_state.content = build_empty_state(
                on_example_prompt, coerce_starters(None), on_starter,
                saved=prompt_ui.get("items", []), on_saved=on_saved_insert,
            )
        except Exception:
            pass

    empty_state.content = build_empty_state(
        on_example_prompt, coerce_starters(None), on_starter,
        saved=prompt_ui.get("items", []), on_saved=on_saved_insert,
    )

    # ---- model picker bar ----
    provider_dd = ft.Dropdown(
        label="Provider",
        options=[ft.dropdown.Option(pid) for pid in PROVIDER_IDS],
        value=store.get("chat", "provider", "gemini") or "gemini",
        expand=True,
    )
    model_dd = ft.Dropdown(
        label="Model (editable)",
        editable=True,
        enable_filter=True,
        options=[],
        expand=True,
    )
    model_button_label = ft.Text(
        "Pick model",
        size=14,
        weight=ft.FontWeight.BOLD,
        expand=True,
        max_lines=1,
        overflow=ft.TextOverflow.ELLIPSIS,
    )

    def _cap_words(pid: str, model: str) -> list[str]:
        """Capability words for the pill tooltip (details live in the sheet)."""
        reg = PROVIDERS.get(pid, {})
        caps: list[str] = []
        if reg.get("free"):
            caps.append("free")
        try:
            overridden = store.get("vision", vision_override_key(pid, model), "false") == "true"
        except Exception:
            overridden = False
        if supports_vision(pid, model, allow=(vision_override_key(pid, model),) if overridden else ()):
            caps.append("vision (override)" if overridden else "vision")
        else:
            caps.append("text-only")
        if supports_docs(pid, model):
            caps.append("docs")
        return caps

    def refresh_model_button() -> None:
        pid = (provider_dd.value or "gemini").strip()
        model = (model_dd.value or "").strip()
        reg = PROVIDERS.get(pid, {})
        # ChatGPT-style pill: only the model name — provider + capability
        # details stay in the tooltip; full specs live in the Model Sheet.
        model_button_label.value = model or "Pick model"
        try:
            model_pill.tooltip = (
                f"{reg.get('display_name', pid)} / {model or '—'} "
                f"({', '.join(_cap_words(pid, model))}) — tap to change"
            )
        except NameError:
            pass  # model_pill not built yet during startup init

    def _safe_update() -> None:
        try:
            page.update()
        except Exception:
            pass

    def refresh_models(_: ft.ControlEvent | None = None) -> None:
        try:
            pid = ((provider_dd.value or "gemini").strip() or "gemini")
        except Exception:
            pid = "gemini"
        reg = PROVIDERS.get(pid, PROVIDERS["gemini"])
        if not isinstance(reg, dict):
            reg = PROVIDERS["gemini"]
        try:
            saved_raw = store.get("chat", "model", "")
            saved = saved_raw.strip() if isinstance(saved_raw, str) else ""
        except Exception:
            saved = ""
        model_values = available_models(pid)
        if saved and saved not in model_values:
            model_values = [saved, *model_values]
        model_dd.options = [ft.dropdown.Option(m) for m in model_values]
        model_dd.value = saved or reg.get("default_model", "") or None
        refresh_model_button()
        try:
            store.set("chat", "provider", pid)
        except Exception:
            pass
        if model_dd.value:
            try:
                store.set("chat", "model", model_dd.value.strip())
            except Exception:
                pass
        try:
            _refresh_meter()
        except Exception:
            pass
        _safe_update()
        try:
            page.run_task(load_live_models, pid)
        except Exception:
            pass

    async def load_live_models(pid: str) -> None:
        """Refresh the active provider's model list without blocking the chat UI."""
        try:
            api_raw = store.get_key(pid)
            api_key = api_raw.strip() if isinstance(api_raw, str) else ""
        except Exception:
            return
        if not api_key:
            return
        try:
            # Per-pid URL always (never the active conv URL — avoids
            # cross-provider key swap where pid A's key is sent to pid B's host).
            reg = PROVIDERS.get(pid, {})
            base_url = store.get_base_url(pid, reg.get("base_url", "") if isinstance(reg, dict) else "")
            provider = get_provider(pid, api_key, base_url)
            models = await provider.list_models()
            try:
                cur_pid = (provider_dd.value or "").strip()
            except Exception:
                return
            if cur_pid != pid:
                return
            set_live_models(pid, models)
            try:
                current = (model_dd.value or "").strip()
            except Exception:
                current = ""
            model_dd.options = [ft.dropdown.Option(m) for m in models]
            model_dd.value = current if current else (models[0] if models else None)
            refresh_model_button()
            if model_dd.value:
                try:
                    store.set("chat", "model", model_dd.value)
                except Exception:
                    pass
            try:
                page.update()
            except Exception:
                pass  # page closed — stale fetch, drop silently
        except (ProviderError, ValueError) as e:
            # Keep the offline registry options, but don't swallow silently —
            # the status line explains why live models didn't load.
            try:
                status.value = f"Live models unavailable for {pid} ({e}); using built-in list."
                _safe_update()
            except Exception:
                pass
            return
        except Exception as e:  # noqa: BLE001
            try:
                status.value = f"Live models check failed: {e}"
                _safe_update()
            except Exception:
                pass
            return

    def persist_model(_: ft.ControlEvent | None = None) -> None:
        try:
            pid = (provider_dd.value or "").strip()
        except Exception:
            pid = ""
        try:
            model = (model_dd.value or "").strip()
        except Exception:
            model = ""
        try:
            store.set("chat", "provider", pid)
            store.set("chat", "model", model)
        except Exception:
            pass
        refresh_model_button()
        try:
            _refresh_meter()
        except Exception:
            pass
        _safe_update()

    provider_dd.on_change = refresh_models
    model_dd.on_change = persist_model

    # ---- bottom-sheet model picker (Android-first) ----
    sheet_search = ft.TextField(label="Search models", prefix_icon=ft.Icons.SEARCH, dense=True)
    sheet_count = ft.Text("", size=11, color=ft.Colors.ON_SURFACE_VARIANT)
    sheet_list = ft.Column(spacing=0, scroll=ft.ScrollMode.AUTO, expand=True)

    def _preset_chip(label: str) -> ft.Chip:
        selected = model_ui.get("preset", "all") == label
        return ft.Chip(
            label=ft.Text(label, size=12),
            autofocus=False,
            data=label,
            on_click=_pick_preset,
        )

    def _pick_preset(e: ft.ControlEvent) -> None:
        try:
            model_ui["preset"] = str(e.control.data or "all")
        except Exception:
            model_ui["preset"] = "all"
        try:
            store.set("ui", "preset", model_ui["preset"])
        except Exception:
            pass
        _refresh_sheet_list(None)

    # INF ai minimal: preset chips hidden (filter stays "all"),
    # capability matrix lives behind Advanced (model detail sheet).
    preset_row = ft.Row([_preset_chip(p) for p in PRESETS], spacing=6, tight=True,
                        scroll=ft.ScrollMode.AUTO, visible=False)

    def _open_matrix(_: ft.ControlEvent | None = None) -> None:
        try:
            rows = capability_matrix()
            table = ft.DataTable(
                columns=[ft.DataColumn(ft.Text(h, size=12, weight=ft.FontWeight.BOLD))
                         for h in ("Provider", "Models", "Vision", "Docs")],
                rows=[ft.DataRow(cells=[ft.DataCell(ft.Text(c, size=12)) for c in r]) for r in rows],
            )
            dlg = ft.AlertDialog(
                modal=False, title=ft.Text("Capability matrix", size=14),
                content=ft.Container(content=ft.Column([table], scroll=ft.ScrollMode.AUTO,
                                                       tight=True), width=360, height=300),
            )
            page.show_dialog(dlg)
        except Exception as e:  # noqa: BLE001
            show_snack(f"Matrix failed: {e}")

    sheet = ft.BottomSheet(
        content=ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("Choose study model", weight=ft.FontWeight.BOLD, size=16, expand=True),
                            ft.IconButton(icon=ft.Icons.CLOSE, tooltip="Close", icon_size=22, on_click=lambda _: _close_sheet()),
                        ]
                    ),
                    sheet_search,
                    preset_row,
                    sheet_count,
                    ft.Container(content=sheet_list, expand=True),
                ],
                spacing=8,
                tight=True,
            ),
            padding=16,
            height=560,
        ),
        show_drag_handle=True,
    )
    page.overlay.append(sheet)

    def _close_sheet() -> None:
        sheet.open = False
        page.update()

    def _pick_model(pid: str, model: str) -> None:
        # v0.5 R2: slot-pick mode routes to the compare pair, not the chat target.
        if compare_ui.get("pick_slot") in COMPARE_SLOTS:
            slot = compare_ui["pick_slot"]
            compare_ui["pick_slot"] = None
            pair = compare_ui.get("pair") or {}
            pair[slot] = [pid, model]
            compare_ui["pair"] = pair
            try:
                store.set("ui", "compare", pair_to_json(pair))
            except Exception:
                pass
            try:
                _refresh_compare_bar()
            except Exception:
                pass
            _close_sheet()
            show_snack(f"Side {slot.upper()}: {pid} / {model}")
            return
        if model == "__CUSTOM__":
            # Sheet's "Add custom model" tile: close the sheet, ask for the
            # model ID, apply it to the current provider.
            _close_sheet()
            _ask_custom_model()
            return
        provider_dd.value = pid
        refresh_models(None)
        # refresh_models may overwrite with saved; force picked model:
        model_dd.value = model
        persist_model(None)
        try:  # recents (KeyStore ui.recents, max 5)
            model_ui["recents"] = push_recent(model_ui.get("recents", []), pid, model)
            store.set("ui", "recents", __import__("json").dumps(model_ui["recents"]))
        except Exception:
            pass
        _close_sheet()
        show_snack(f"{pid} / {model} selected")

    def _refresh_sheet_list(_: ft.ControlEvent | None = None) -> None:
        current = ((provider_dd.value or "").strip(), (model_dd.value or "").strip())
        # Only providers with a linked API key are listed — offering a
        # model the user can't send to just produces errors on Send.
        linked: set[str] = set()
        for pid in PROVIDER_IDS:
            try:
                if store.get_key(pid).strip():
                    linked.add(pid)
            except Exception:
                continue
        preset = model_ui.get("preset", "all")
        try:
            n = len(apply_preset_filter(
                iter_model_rows(sheet_search.value or "", linked), preset))
            sheet_count.value = (
                "No keys linked — add one to unlock models"
                if not linked else
                f"{n} model{'s' if n != 1 else ''}"
                + (" — no match, try fewer words" if n == 0 else "")
            )
        except Exception:
            pass
        sheet_list.controls = build_model_list(
            sheet_search.value or "", current, _pick_model,
            preset=preset,
            recents=model_ui.get("recents", []),
            on_detail=_open_model_detail,
            linked=linked,
            on_add_key=_go_add_key,
        )
        page.update()

    sheet_search.on_change = lambda _: _debounced("sheet", lambda: _refresh_sheet_list(None))

    def _go_add_key() -> None:
        """Empty-catalog escape hatch: sheet → Study keys tab."""
        try:
            sheet.open = False
        except Exception:
            pass
        try:
            _go_tab(1)
        except Exception:
            pass
        try:
            page.update()
        except Exception:
            pass
        show_snack("Add a study key, then pick a model.")

    def open_model_sheet(_: ft.ControlEvent | None = None) -> None:
        sheet_search.value = ""
        _refresh_sheet_list(None)
        sheet.open = True
        page.update()

    # Manual provider/model fields stay as hidden state holders — the chat
    # page exposes only the model pill; switching happens via the Model
    # Sheet (or menu → Study keys). Custom models go through the sheet's
    # "Add custom model" tile, so no advanced toggle is needed here.
    advanced_row = ft.Row([provider_dd, model_dd], tight=True, visible=False)

    # ---- bubbles (forward decls for per-bubble actions) ----
    def _scroll_to_end() -> None:
        try:
            if state.get("bulk_render"):
                return
            if not chat.controls:
                return
            chat.scroll_to(offset=100000, duration=250)
        except Exception:
            pass

    def _pop_ui_bubbles(n: int) -> None:
        """Keep chat UI in sync when history entries are popped (retry)."""
        try:
            for _ in range(max(0, n)):
                if chat.controls:
                    chat.controls.pop()
        except Exception:
            pass

    async def on_retry(_: ft.ControlEvent | None = None) -> None:
        if state.get("streaming"):
            show_snack("Wait for the current reply to finish.")
            return
        if not history:
            return
        def _user_text(m: object) -> str:
            try:
                content = getattr(m, "content", "")
            except Exception:
                return ""
            if isinstance(content, str):
                return content
            if not isinstance(content, list):
                return ""
            bits: list[str] = []
            for p in content:
                if not isinstance(p, dict) or p.get("type") != "text":
                    continue
                t = p.get("text", "")
                bits.append(t if isinstance(t, str) else "")
            return "\n".join(b for b in bits if b)
        last_user = next(
            (_user_text(m) for m in reversed(history) if getattr(m, "role", "") == "user"),
            "",
        )
        if not (isinstance(last_user, str) and last_user.strip()):
            show_snack("Nothing to retry yet.")
            return
        last_user = last_user[:20000]
        # Pop history + matching UI bubbles together so UI never diverges.
        popped = 0
        if history and history[-1].role == "assistant":
            history.pop()
            popped += 1
        if history and history[-1].role == "user":
            history.pop()
            popped += 1
        _pop_ui_bubbles(popped)
        # Retry the FULL prompt (attachments are text-only on retry).
        _append_user(last_user)
        _safe_update()
        _scroll_to_end()
        await stream_reply(last_user)

    def on_copy_last(_: ft.ControlEvent | None = None) -> None:
        if not state["last_assistant"]:
            show_snack("Nothing to copy yet.")
            return
        try:
            page.run_task(copy_to_clipboard, state["last_assistant"])
        except Exception as e:  # noqa: BLE001
            show_snack(f"Copy failed: {e}")

    def _append_user(text: str, ts: str | None = None, key_idx: int | None = None) -> None:
        def _copy(_: ft.ControlEvent | None = None) -> None:
            try:
                page.run_task(copy_to_clipboard, text)
            except Exception as e:  # noqa: BLE001
                show_snack(f"Copy failed: {e}")

        def _edit(_: ft.ControlEvent | None = None) -> None:
            if state.get("streaming"):
                show_snack("Wait for the current reply to finish, then edit.")
                return
            # Bubbles carry display suffixes (" +2 file(s)", " (+images)")
            # that are not part of the prompt — strip for field + matching.
            clean = re.sub(r"\s+(\+\d+ file\(s\)|\(\+images\))$", "", text)
            field = ft.TextField(label="Edit message", value=clean, multiline=True,
                                 min_lines=2, max_lines=6, dense=True)
            dlg = ft.AlertDialog(
                modal=True, title=ft.Text("Edit and resubmit"),
                content=ft.Container(content=field, width=340),
                actions=[
                    ft.TextButton(content=ft.Text("Cancel"),
                                  on_click=lambda _: (setattr(dlg, "open", False), page.update())),
                    ft.FilledButton(content=ft.Text("Resubmit"),
                                     on_click=lambda _: _do_resubmit(dlg, field)),
                ],
            )

            def _do_resubmit(d: ft.AlertDialog, f: ft.TextField) -> None:
                new_text = (f.value or "").strip()
                d.open = False
                if not new_text:
                    page.update()
                    return
                if state.get("streaming"):
                    show_snack("Wait for the current reply to finish.")
                    try:
                        page.update()
                    except Exception:
                        pass
                    return
                # Truncate history to the edited turn so UI/DB never diverge:
                # drop the old user message + everything after it, persist,
                # then resend the edited text as a fresh turn.
                try:
                    want = re.sub(r"\s+(\+\d+ file\(s\)|\(\+images\))$", "", text)
                    edit_idx = None
                    for i, m in enumerate(history):
                        try:
                            t, _ = user_text_of(m.content)
                        except Exception:
                            t = m.content if isinstance(m.content, str) else ""
                        if m.role == "user" and (t or "") == text:
                            edit_idx = i
                    if edit_idx is None:
                        # Suffix-stripped retry (reloaded chats), else fall
                        # back to the latest user turn so we never resend
                        # on top of a full Q+A pair (the old duplicate bug).
                        for i, m in enumerate(history):
                            try:
                                t, _ = user_text_of(m.content)
                            except Exception:
                                t = m.content if isinstance(m.content, str) else ""
                            if m.role == "user" and re.sub(
                                r"\s+(\+\d+ file\(s\)|\(\+images\))$", "", (t or "")
                            ) == want:
                                edit_idx = i
                    if edit_idx is None:
                        edit_idx = next(
                            (i for i, m in reversed(list(enumerate(history)))
                             if m.role == "user"),
                            None,
                        )
                    if edit_idx is not None:
                        history[:] = history[:edit_idx]
                        if chats is not None and state.get("conv_id") is not None:
                            try:
                                chats.replace_messages(state["conv_id"], history)
                            except Exception:
                                pass
                        hist_ui["shown"] = None
                        render_history_to_ui()
                        try:
                            _refresh_meter()
                        except Exception:
                            pass
                except Exception:
                    pass
                input_box.value = new_text
                page.update()
                page.run_task(on_send, None)

            page.show_dialog(dlg)

        def _fork(_: ft.ControlEvent | None = None) -> None:
            try:
                idx = next((i for i, m in reversed(list(enumerate(history)))
                            if m.role == "user"), None)
                if idx is None:
                    show_snack("Nothing to fork yet.")
                    return
                history[:] = fork_history(history, idx)
                if chats is not None and state.get("conv_id") is not None:
                    try:
                        chats.replace_messages(state["conv_id"], history)
                    except Exception as e:  # noqa: BLE001
                        show_snack(f"Forked locally — save failed: {e}")
                        render_history_to_ui()
                        return
                render_history_to_ui()
                try:
                    _refresh_meter()
                except Exception:
                    pass
                show_snack("Forked — history truncated here. Send to continue.")
            except Exception as e:  # noqa: BLE001
                show_snack(f"Fork failed: {e}")

        def _pin(_: ft.ControlEvent | None = None) -> None:
            pinned = state.setdefault("pinned_msgs", set())
            if text in pinned:
                pinned.discard(text)
                show_snack("Unpinned.")
            else:
                if len(pinned) >= 10:
                    show_snack("Pin limit reached (10) — unpin one first.")
                    return
                pinned.add(text)
                show_snack("Pinned — kept for context.")
            _save_pinned(pinned)
            render_history_to_ui()
            try:
                _refresh_meter()
            except Exception:
                pass
            _safe_update()

        try:
            is_pinned = text in state.get("pinned_msgs", set())
        except Exception:
            is_pinned = False
        row = user_bubble(text, on_copy=_copy, timestamp=ts or now_hhmm(),
                          on_edit=_edit, on_fork=_fork,
                          pinned=is_pinned, on_pin=_pin)
        try:  # RTL mirror for user rows
            if detect_text_direction(text) == "rtl":
                row.alignment = align_for_direction("rtl", default_end=True)
        except Exception:
            pass
        try:  # v0.5 R6: key rows by history index for find-in-chat nav
            row.key = row_key(len(history) if key_idx is None else key_idx)
        except Exception:
            pass
        chat.controls.append(row)
        refresh_empty()
        _scroll_to_end()

    def _markdown(value: str) -> ft.Markdown:
        # Render exactly what the model returns: GFM (tables, fenced code,
        # strikethrough, task lists), selectable. Links do NOT auto-open
        # (provider output is untrusted — tap shows OS confirm instead).
        # soft_line_break=False => single \n stays soft (standard Markdown),
        # so we don't inject spurious <br/> into wrapped paragraphs.
        # LaTeX math (unsupported by the widget) renders as Unicode first;
        # history/DB keeps the raw text, code fences pass through verbatim.
        return ft.Markdown(
            _tex(value),
            selectable=True,
            extension_set=ft.MarkdownExtensionSet.GITHUB_FLAVORED,
            code_theme=ft.MarkdownCodeTheme.GITHUB,
            auto_follow_links=False,
            soft_line_break=False,
            shrink_wrap=True,
            fit_content=False,
        )

    def _append_assistant(body: str, ts: str | None = None, key_idx: int | None = None) -> None:
        md = _markdown(body)
        row = assistant_bubble(md, on_copy=lambda _: page.run_task(copy_to_clipboard, body), on_retry=lambda _: page.run_task(on_retry, None), timestamp=ts or now_hhmm())
        try:  # v0.5 R6: key rows by history index for find-in-chat nav
            row.key = row_key(len(history) if key_idx is None else key_idx)
        except Exception:
            pass
        chat.controls.append(row)
        refresh_empty()
        _scroll_to_end()

    # ---- attachments (P3) ----
    def refresh_chips() -> None:
        chips_row.controls.clear()
        for i, att in enumerate(attachments):
            try:
                chip = build_attachment_chip(att, i, remove_attachment)
                # Tap-to-preview: zoomable lightbox for images, text for docs.
                def _preview(_: ft.ControlEvent | None = None, _att=att) -> None:
                    try:
                        dlg = build_lightbox(
                            _att.name,
                            _att.data_url if _att.data_url else None,
                            _att.text or "",
                        )
                        page.show_dialog(dlg)
                    except Exception:
                        pass
                chip.on_click = _preview
                chip.tooltip = f"Preview {att.name} — tap to zoom"
                chips_row.controls.append(chip)
            except Exception:
                chips_row.controls.append(build_attachment_chip(att, i, remove_attachment))
        try:
            if not state["streaming"]:
                st = InputState(
                    streaming=False,
                    has_text=bool((input_box.value or "").strip()),
                    has_attachments=bool(attachments),
                )
                kind, tip = send_button_mode(st)
                # INF ai minimal: no mic placeholder — empty composer shows Send.
                send_stop_btn.icon = {
                    "STOP": ft.Icons.STOP, "SEND": ft.Icons.SEND, "MIC": ft.Icons.SEND,
                }.get(kind, ft.Icons.SEND)
                send_stop_btn.tooltip = "Type a study question first" if kind == "MIC" else tip
        except Exception:
            pass
        page.update()

    def remove_attachment(e: ft.ControlEvent) -> None:
        try:
            attachments.pop(int(e.control.data))
        except (IndexError, TypeError, ValueError):
            pass
        refresh_chips()

    async def on_attach(_: ft.ControlEvent) -> None:
        try:
            plus_menu.disabled = True
        except Exception:
            pass
        try:
            page.update()
        except Exception:
            pass
        try:
            files = await picker.pick_files(
                dialog_title="Attach images or docs",
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=sorted(ALLOWED_IMAGE_EXTS | ALLOWED_DOC_EXTS),
                allow_multiple=True,
                with_data=True,
            )
        except Exception as e:  # noqa: BLE001
            show_snack(f"File picker failed: {e}")
            try:
                status.value = f"File picker failed: {e}"
            except Exception:
                pass
            try:
                page.update()
            except Exception:
                pass
            return
        finally:
            try:
                plus_menu.disabled = False
            except Exception:
                pass
            try:
                page.update()
            except Exception:
                pass
        if not files:
            return
        if len(files) > 10:
            show_snack("Too many files — attaching the first 10.")
            files = files[:10]
        for f in files:
            if len(attachments) >= 10:
                show_snack("Attachment limit reached (10).")
                break
            try:
                fname = getattr(f, "name", "") or "file"
            except Exception:
                fname = "file"
            # Pre-read budget: enforce 10/15MB + 30MB total BEFORE allocating.
            try:
                hint = getattr(f, "size", None)
                staged_total = sum(getattr(a, "size", 0) for a in attachments)
                if isinstance(hint, int) and hint > 0:
                    if hint > 16 * 1024 * 1024:
                        chat.controls.append(error_bubble(f"'{fname}' is too large (max 15MB)."))
                        continue
                    if staged_total + hint > 30 * 1024 * 1024:
                        chat.controls.append(error_bubble("Total attachments exceed 30MB budget."))
                        break
            except Exception:
                pass
            raw = getattr(f, "bytes", None)
            if raw is not None and len(bytes(raw)) > 16 * 1024 * 1024:
                chat.controls.append(error_bubble(f"'{fname}' is too large (max 15MB)."))
                continue
            if raw is None and getattr(f, "path", None):
                try:
                    with open(f.path, "rb") as fh:
                        raw = fh.read(16 * 1024 * 1024 + 1)
                    if len(raw) > 16 * 1024 * 1024:
                        chat.controls.append(error_bubble(f"'{fname}' is too large (max 15MB)."))
                        continue
                except OSError:
                    chat.controls.append(error_bubble(f"Could not read '{fname}' (I/O error)."))
                    continue
            if raw is None:
                chat.controls.append(error_bubble(f"Could not read '{fname}' (no data)."))
                continue
            try:
                attachments.append(prepare_file(fname, bytes(raw)))
            except ValueError as e:
                chat.controls.append(error_bubble(str(e)[:300]))
            except Exception:  # noqa: BLE001 — never break attach loop, no paths
                chat.controls.append(error_bubble(f"Could not attach '{fname}'. Individual files cap at 10MB images / 15MB docs; total 30MB."))
        refresh_chips()
        refresh_empty()
        status.value = (
            f"{len(attachments)} file(s) attached."
            if attachments
            else "Pick a provider + model, then chat."
        )
        page.update()

    input_box = ft.TextField(
        label="Ask a study question",
        multiline=True,
        min_lines=1,
        max_lines=4,
        expand=True,
        dense=True,
    )
    send_stop_btn = ft.IconButton(icon=ft.Icons.SEND, tooltip="Send", icon_size=24)

    async def on_camera(_: ft.ControlEvent | None = None) -> None:
        """In-app capture: photo bytes → staged attachment (no gallery hop)."""
        if state.get("streaming"):
            show_snack("Wait for the current reply to finish.")
            return

        def _on_photo(data: bytes) -> None:
            try:
                attachments.append(prepare_file(camera_filename(), bytes(data)))
            except ValueError as e:
                chat.controls.append(error_bubble(str(e)))
                refresh_empty()
                _safe_update()
                return
            except Exception as e:  # noqa: BLE001
                show_snack(f"Could not attach photo: {e}")
                return
            refresh_chips()
            refresh_empty()
            status.value = f"{len(attachments)} file(s) attached."
            _safe_update()

        def _on_err(msg: str) -> None:
            show_snack(msg or "Camera unavailable.")

        try:
            await open_camera_capture(page, _on_photo, _on_err)
        except Exception as e:  # noqa: BLE001
            show_snack(f"Camera failed: {e}")

    # ---- prompt library sheet (v0.5 R8: insert/edit/delete, no auto-send) ----
    prompt_list_col = ft.Column(spacing=0, tight=True, scroll=ft.ScrollMode.AUTO)
    prompt_sheet = ft.BottomSheet(
        content=ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("Prompt library", weight=ft.FontWeight.BOLD, size=16, expand=True),
                            ft.IconButton(icon=ft.Icons.ADD, tooltip="New prompt",
                                          icon_size=22, on_click=lambda _: _edit_prompt(None)),
                            ft.IconButton(icon=ft.Icons.CLOSE, tooltip="Close",
                                          icon_size=22, on_click=lambda _: _close_prompt_sheet()),
                        ]
                    ),
                    ft.Container(content=prompt_list_col, height=380),
                ],
                spacing=8,
                tight=True,
            ),
            padding=16,
            height=480,
        ),
        show_drag_handle=True,
    )
    page.overlay.append(prompt_sheet)

    def _close_prompt_sheet() -> None:
        try:
            prompt_sheet.open = False
            page.update()
        except Exception:
            pass

    def _persist_prompts() -> None:
        save_prompts(store, prompt_ui.get("items", []))
        refresh_empty_state()

    def _refresh_prompt_list() -> None:
        items = prompt_ui.get("items", [])
        rows: list[ft.Control] = []
        if not items:
            rows.append(ft.Text("No saved prompts — tap + to save one.", size=12))
        for i, p in enumerate(items):
            rows.append(
                ft.ListTile(
                    title=ft.Text(p.title, size=13, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    subtitle=ft.Text((p.prompt[:80] + "…") if len(p.prompt) > 80 else p.prompt,
                                     size=11, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                    trailing=ft.Row(
                        [
                            ft.IconButton(icon=ft.Icons.ARROW_DOWNWARD, tooltip="Insert into input",
                                          icon_size=18, data=i, on_click=_insert_prompt),
                            ft.IconButton(icon=ft.Icons.EDIT_OUTLINED, tooltip="Edit",
                                          icon_size=18, data=i, on_click=_edit_prompt),
                            ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, tooltip="Delete",
                                          icon_size=18, data=i, on_click=_delete_prompt),
                        ],
                        spacing=0,
                        tight=True,
                    ),
                    data=i,
                    on_click=_insert_prompt,
                )
            )
        prompt_list_col.controls = rows

    def open_prompt_library(_: ft.ControlEvent | None = None) -> None:
        _refresh_prompt_list()
        prompt_sheet.open = True
        try:
            page.update()
        except Exception:
            pass

    def _insert_prompt(e: ft.ControlEvent) -> None:
        try:
            p = prompt_ui.get("items", [])[int(e.control.data)]
        except Exception:
            return
        _close_prompt_sheet()
        on_saved_insert(p)

    def _delete_prompt(e: ft.ControlEvent) -> None:
        try:
            prompt_ui["items"] = delete_prompt(prompt_ui.get("items", []), int(e.control.data))
            _persist_prompts()
            _refresh_prompt_list()
            page.update()
        except Exception as ex:  # noqa: BLE001
            show_snack(f"Delete failed: {ex}")

    def _edit_prompt(e: ft.ControlEvent | None) -> None:
        try:
            idx = int(e.control.data) if e is not None and e.control.data is not None else None
            existing = prompt_ui.get("items", [])[idx] if idx is not None else None
        except Exception:
            idx, existing = None, None
        title_f = ft.TextField(label="Title", value=existing.title if existing else "",
                               dense=True, max_length=40)
        prompt_f = ft.TextField(label="Prompt", value=existing.prompt if existing else "",
                                multiline=True, min_lines=3, max_lines=8, dense=True,
                                max_length=1000)
        bind = ft.Text(f"Binds to current: {(provider_dd.value or '').strip()} / "
                       f"{(model_dd.value or '').strip()}" if existing is None else
                       f"Binding: {existing.provider or '—'} / {existing.model or '—'}",
                       size=11, color=ft.Colors.ON_SURFACE_VARIANT)
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Edit prompt" if existing else "New prompt", size=14),
            content=ft.Container(
                content=ft.Column([title_f, prompt_f, bind], spacing=8, tight=True),
                width=340,
            ),
            actions=[
                ft.TextButton(content=ft.Text("Cancel"),
                              on_click=lambda _: (setattr(dlg, "open", False), page.update())),
                ft.FilledButton(content=ft.Text("Save"), on_click=lambda _: _save()),
            ],
        )

        def _save() -> None:
            title = (title_f.value or "").strip()
            prompt = (prompt_f.value or "").strip()
            if not title or not prompt:
                show_snack("Title and prompt are both required.")
                return
            if existing is None:
                try:
                    pid = (provider_dd.value or "").strip()
                    model = (model_dd.value or "").strip()
                except Exception:
                    pid, model = "", ""
                entry = SavedPrompt(title=title, prompt=prompt, provider=pid, model=model)
                prompt_ui["items"] = add_prompt(prompt_ui.get("items", []), entry)
            else:
                prompt_ui["items"] = update_prompt(
                    prompt_ui.get("items", []), idx,
                    SavedPrompt(title=title, prompt=prompt,
                                provider=existing.provider, model=existing.model))
            _persist_prompts()
            dlg.open = False
            _refresh_prompt_list()
            try:
                page.update()
            except Exception:
                pass
            show_snack("Prompt saved.")

        page.show_dialog(dlg)

    # (Prompt library moved into the input "+" menu — see plus_menu.)

    def update_send_stop() -> None:
        # INF ai minimal: Send/Stop only (no mic placeholder).
        try:
            st = InputState(
                streaming=bool(state["streaming"]),
                has_text=bool((input_box.value or "").strip()),
                has_attachments=bool(attachments),
            )
            kind, tip = send_button_mode(st)
        except Exception:
            kind, tip = ("STOP" if state["streaming"] else "SEND", "Send")
        send_stop_btn.icon = {
            "STOP": ft.Icons.STOP, "SEND": ft.Icons.SEND, "MIC": ft.Icons.SEND,
        }.get(kind, ft.Icons.SEND)
        send_stop_btn.tooltip = "Type a study question first" if kind == "MIC" else tip
        # Button-only update — page.update() per keystroke janks typing
        # (every bubble in the list re-renders).
        try:
            send_stop_btn.update()
        except Exception:
            pass

    def _clear_vision_override(_: ft.ControlEvent | None = None) -> None:
        """Revoke the remembered Send-anyway for the current model.

        Overrides are stored per (provider, model) with no expiry, so
        without this the vision gate could never ask again after a model
        silently drops image support.
        """
        try:
            pid = (provider_dd.value or "").strip()
            model = (model_dd.value or "").strip()
        except Exception:
            pid, model = "", ""
        if not pid or not model:
            show_snack("Pick a provider + model first.")
            return
        key = vision_override_key(pid, model)
        try:
            had = store.get("vision", key, "false") == "true"
        except Exception:
            had = False
        if not had:
            show_snack(f"No vision override set for {pid} / {model}.")
            return
        try:
            store.set("vision", key, "false")
        except Exception as e:  # noqa: BLE001
            show_snack(f"Could not clear override: {e}")
            return
        try:
            refresh_model_button()
            _safe_update()
        except Exception:
            pass
        show_snack(f"Vision override cleared for {pid} / {model} — will ask again.")

    # ---- app lock overlay (v0.4.0) ----
    lock_ui = {"unlocked": True}
    lock_pin = ft.TextField(
        label="PIN",
        password=True,
        keyboard_type=ft.KeyboardType.NUMBER,
        max_length=8,
        dense=True,
        autofocus=True,
    )
    lock_err = ft.Text("", size=12, color=ft.Colors.RED)
    lock_dlg = ft.AlertDialog(
        modal=True,
        title=ft.Text("Unlock INF ai"),
        content=ft.Column(
            [
                ft.Text("Enter your app-lock PIN to continue.", size=12),
                lock_pin,
                lock_err,
            ],
            spacing=8,
            tight=True,
        ),
        actions=[
            ft.TextButton(content=ft.Text("Forgot PIN?"), on_click=lambda _: _forgot_pin()),
            ft.FilledButton(content=ft.Text("Unlock"), on_click=lambda _: _try_unlock()),
        ],
    )
    lock_bio_btn = ft.OutlinedButton(
        content=ft.Text("Use biometrics"), icon=ft.Icons.FINGERPRINT
    )

    async def _bio_unlock() -> None:
        try:
            ok, reason = await BioUnlock(page).unlock_with_reason()
        except Exception as e:  # noqa: BLE001
            ok, reason = False, f"Biometrics failed: {e}"[:220]
        if ok:
            _unlock_ok()
        else:
            lock_err.value = reason or "Biometric unlock failed — enter PIN."
            try:
                page.update()
            except Exception:
                pass

    def _bio_tap(_: ft.ControlEvent) -> None:
        try:
            page.run_task(_bio_unlock)
        except Exception:
            lock_err.value = "Biometrics unavailable — enter PIN."
            page.update()

    lock_bio_btn.on_click = _bio_tap

    def _unlock_ok() -> None:
        lock_ui["unlocked"] = True
        lock_dlg.open = False
        lock_pin.value = ""
        lock_err.value = ""
        page.update()

    def _try_unlock() -> None:
        from app.data.app_lock import pin_failed, pin_locked_out, pin_success
        try:
            locked, wait = pin_locked_out(store)
        except Exception:
            locked, wait = False, 0
        if locked:
            lock_err.value = f"Too many attempts — wait {wait}s."
            page.update()
            return
        prefs = lock_prefs(store)
        if verify_pin(lock_pin.value or "", prefs["salt"], prefs["pin_hash"]):
            try:
                pin_success(store)
            except Exception:
                pass
            _unlock_ok()
        else:
            try:
                backoff = pin_failed(store)
            except Exception:
                backoff = 0
            lock_err.value = (
                f"Wrong PIN — wait {backoff}s." if backoff else "Wrong PIN — try again."
            )
            page.update()

    lock_pin.on_submit = lambda _: _try_unlock()

    def _forgot_pin() -> None:
        # Authenticated reset: require current PIN when lock is enabled so a
        # physical-access attacker cannot wipe the lock without knowing it.
        # Fallback path (truly forgotten) still exists via Settings after unlock.
        from app.data.app_lock import pin_locked_out
        try:
            locked, wait = pin_locked_out(store)
        except Exception:
            locked, wait = False, 0
        if locked:
            lock_err.value = f"Too many attempts — wait {wait}s."
            try:
                page.update()
            except Exception:
                pass
            return
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Reset app lock?"),
            content=ft.Column([
                ft.Text(
                    "Enter your current PIN to remove the lock AND all saved API keys. "
                    "Your chats stay on this device."
                ),
                ft.TextField(label="Current PIN", password=True,
                             keyboard_type=ft.KeyboardType.NUMBER, max_length=8, dense=True),
                ft.Text("", size=12, color=ft.Colors.RED),
            ], spacing=8, tight=True),
            actions=[
                ft.TextButton(
                    content=ft.Text("Cancel"),
                    on_click=lambda _: (setattr(dlg, "open", False), page.update()),
                ),
                ft.TextButton(
                    content=ft.Text("Reset", style=ft.TextStyle(color=ft.Colors.RED)),
                    on_click=lambda _: _do_forgot_checked(dlg),
                ),
            ],
        )
        page.show_dialog(dlg)

    def _do_forgot_checked(dlg: ft.AlertDialog) -> None:
        try:
            pin_f = dlg.content.controls[1] if hasattr(dlg.content, "controls") else None
            err_t = dlg.content.controls[2] if hasattr(dlg.content, "controls") else None
            guess = (pin_f.value or "") if pin_f is not None else ""
        except Exception:
            guess, err_t = "", None
        prefs = lock_prefs(store)
        if not verify_pin(guess, prefs["salt"], prefs["pin_hash"]):
            try:
                if err_t is not None:
                    err_t.value = "Current PIN is wrong — reset blocked."
                page.update()
            except Exception:
                pass
            return
        _do_forgot(dlg)

    def _do_forgot(dlg: ft.AlertDialog) -> None:
        async def _clear_bio() -> None:
            try:
                await BioUnlock(page).clear()
            except Exception:
                pass

        clear_lock(store)
        wipe_keys(store, PROVIDER_IDS)
        try:
            page.run_task(_clear_bio)
        except Exception:
            pass
        dlg.open = False
        _unlock_ok()
        show_snack("Lock removed and keys cleared. Chats kept.")

    def lock_now() -> None:
        """Show the lock dialog if app lock is enabled."""
        if not lock_prefs(store)["enabled"]:
            show_snack("App lock is off — set a PIN in Settings → Security.")
            return
        try:
            _enable_screenshot_protection()
        except Exception:
            pass
        lock_ui["unlocked"] = False
        lock_pin.value = ""
        lock_err.value = ""
        prefs = lock_prefs(store)
        lock_bio_btn.visible = bool(prefs["biometric"])
        if lock_bio_btn not in lock_dlg.actions:
            lock_dlg.actions = [lock_dlg.actions[0], lock_bio_btn, lock_dlg.actions[1]]
        page.show_dialog(lock_dlg)

    lock_ui["relock_gen"] = 0

    async def _relock_guard() -> None:
        # Debounced re-arm: runs after the pop animation settles and only
        # re-shows when (a) still locked, (b) lock still enabled, (c) the
        # dialog is actually closed. The triple check means legitimate
        # unlocks (which set unlocked=True first) and already-open dialogs
        # can never stack or loop — a sync re-show inside the dismiss event
        # raced the close and left stacked routes that no unlock could clear.
        # Generation counter: rapid Back presses schedule N guards; only the
        # latest may re-show, so dialogs can never stack.
        lock_ui["relock_gen"] = int(lock_ui.get("relock_gen", 0) or 0) + 1
        my_gen = lock_ui["relock_gen"]
        await asyncio.sleep(0.4)
        try:
            if my_gen != lock_ui.get("relock_gen"):
                return  # superseded by a newer dismiss
            if (
                not lock_ui.get("unlocked")
                and lock_prefs(store)["enabled"]
                and not getattr(lock_dlg, "open", True)
            ):
                page.show_dialog(lock_dlg)
        except Exception:
            pass

    def _on_lock_dismiss(_: ft.ControlEvent | None = None) -> None:
        # Android's system Back pops even modal dialogs — without this the
        # whole app lock is skippable with one Back press.
        try:
            page.run_task(_relock_guard)
        except Exception:
            pass

    try:
        lock_dlg.on_dismiss = _on_lock_dismiss
    except Exception:
        pass

    try:
        if isinstance(getattr(page, "data", None), dict):
            page.data["lock_now"] = lock_now
    except Exception:
        pass

    # ---- v0.4 refinement state: already initialised at top of main ----
    # (recents reloaded here in case KeyStore rekeyed meanwhile).
    try:
        model_ui["recents"] = parse_recents(store.get("ui", "recents", "[]"))
    except Exception:
        pass

    def _wire_assistant_actions(assistant_row: ft.Row, full: str) -> None:
        try:
            actions_row = assistant_row.data
            if isinstance(actions_row, ft.Row):
                def _feedback_ctx() -> dict:
                    try:
                        pid = (provider_dd.value or "").strip()
                    except Exception:
                        pid = ""
                    try:
                        model = (model_dd.value or "").strip()
                    except Exception:
                        model = ""
                    return {
                        "provider": pid,
                        "model": model,
                        "prompt": str(state.get("last_prompt", ""))[:200],
                        "reply": str(full or "")[:500],
                        "ts": int(time.time()),
                    }

                def _good(_: ft.ControlEvent | None = None) -> None:
                    ctx = _feedback_ctx()
                    ctx.update({"vote": "up", "reason": "helpful", "note": ""})
                    n = _save_feedback_entry(ctx)
                    state["last_feedback"] = ctx
                    show_snack(f"Thanks — marked as helpful ({n} saved).")

                def _bad(_: ft.ControlEvent | None = None) -> None:
                    try:
                        # Stash reply context so _submit_feedback persists it.
                        state["_pending_bad"] = _feedback_ctx()
                        state["_pending_bad_reply"] = full
                        # feedback_sheet is a BottomSheet (in page.overlay),
                        # not an AlertDialog — open it directly.
                        feedback_sheet.open = True
                        page.update()
                    except Exception:
                        show_snack("Thanks — marked for review.")

                def _copy_code(e: ft.ControlEvent) -> None:
                    try:
                        page.run_task(copy_to_clipboard, str(e.control.data or ""))
                    except Exception:
                        show_snack("Copy failed.")

                actions_row.controls.extend(
                    [
                        # Copy/retry already exist on the actions row (baked
                        # by assistant_bubble) — adding them again duplicated
                        # the buttons on every reply. Thumbs only here.
                        ft.IconButton(
                            icon=ft.Icons.THUMB_UP_OUTLINED,
                            tooltip="Good response",
                            icon_size=16,
                            style=ft.ButtonStyle(padding=12),
                            on_click=_good,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.THUMB_DOWN_OUTLINED,
                            tooltip="Bad response — tell us why",
                            icon_size=16,
                            style=ft.ButtonStyle(padding=12),
                            on_click=_bad,
                        ),
                    ]
                )
                # Per-code-block copy cards (ft.Markdown can't host buttons).
                try:
                    for card in code_copy_cards(full, _copy_code):
                        chat.controls.append(card)
                except Exception:
                    pass
        except Exception:
            pass

    def _submit_feedback(refs: dict, sheet: ft.BottomSheet) -> None:
        try:
            reason = getattr(refs.get("group"), "value", FEEDBACK_REASONS[0])
            note = (getattr(refs.get("note"), "value", "") or "").strip()
            ctx = dict(state.get("_pending_bad") or {})
            if not ctx:
                try:
                    ctx = {
                        "provider": (provider_dd.value or "").strip(),
                        "model": (model_dd.value or "").strip(),
                        "prompt": str(state.get("last_prompt", ""))[:200],
                        "reply": "",
                        "ts": int(time.time()),
                    }
                except Exception:
                    ctx = {"ts": int(time.time())}
            ctx.update({"vote": "down", "reason": reason, "note": note[:300]})
            try:
                pending_reply = state.pop("_pending_bad_reply", "")
                if pending_reply and not ctx.get("reply"):
                    ctx["reply"] = str(pending_reply)[:500]
            except Exception:
                pass
            try:
                state.pop("_pending_bad", None)
            except Exception:
                pass
            state["last_feedback"] = ctx
            n = _save_feedback_entry(ctx)
            show_snack(f"Feedback saved ({reason}, {n} total). Thanks!")
        except Exception:
            show_snack("Feedback saved. Thanks!")
        try:
            sheet.open = False
            page.update()
        except Exception:
            pass

    feedback_sheet, _feedback_refs = build_feedback_sheet(_submit_feedback)
    page.overlay.append(feedback_sheet)

    def _rag_enabled() -> bool:
        try:
            raw = store.get("rag", "enabled", "true")
            return raw.lower() != "false" if isinstance(raw, str) else True
        except Exception:
            return True

    def _maybe_apply_rag(
        prompt: str, staged: list[Attachment], messages: list[Message]
    ) -> tuple[list[Message] | None, list[str], list[float]]:
        """Rewrite the pending user message with RAG excerpts when useful.

        - Long staged docs (>= RAG_MIN_CHARS): chunk + index under the
          current conversation, inject top-k chunks with [file §n] labels.
        - No staged docs but indexed chunks exist (follow-up question):
          retrieve over the conversation's index; when nothing scores
          above zero, fall back to each doc's first chunk so the follow-up
          still sees grounded context instead of silently dropping it.
        - Multimodal payloads (images staged): the text portion is
          rewritten the same way while image parts are preserved.
        Returns (new_messages or None, source labels used, hit scores used
        for the v0.5 R4 "why these" tooltip).
        """
        if not _rag_enabled() or chats is None or state["conv_id"] is None:
            return None, [], []
        if not messages:
            return None, [], []
        last = messages[-1]
        if isinstance(last.content, str):
            last_images: list = []
        elif isinstance(last.content, list):
            # Multimodal: rewrite the text portion, preserve image parts.
            last_images = [
                p for p in last.content
                if isinstance(p, dict) and p.get("type") == "image_url"
            ]
        else:
            return None, [], []
        conv_id = state["conv_id"]
        assert conv_id is not None
        long_docs = [
            a
            for a in staged
            if (a.text or "") and len(a.text) >= rag_mod.RAG_MIN_CHARS
        ]
        short_docs = [
            a
            for a in staged
            if (a.text or "") and len(a.text) < rag_mod.RAG_MIN_CHARS
        ]
        blocks: list[str] = [doc_block(a) for a in short_docs]
        labels: list[str] = []
        scores: list[float] = []

        def _append_block(name: str, hits: list) -> None:
            block, lab = rag_mod.build_rag_block(name, hits)
            if block:
                blocks.append(block)
                labels.extend(lab)

        if long_docs:
            for a in long_docs:
                chunks = rag_mod.chunk_for_rag(a.text or "")
                if not chunks:
                    continue
                try:
                    chats.index_doc_chunks(conv_id, a.name, chunks)
                except Exception:
                    pass
                hits = rag_mod.TfidfIndex(chunks).retrieve(prompt)
                if not hits:
                    # No scored excerpt: do NOT inject chunk-0 silently
                    # (previous fail-open leaked doc content on irrelevant
                    # follow-ups). Short-doc path already covers small docs.
                    continue
                scores.extend(s for _, s, _ in hits)
                _append_block(a.name, hits)
        else:
            try:
                indexed = chats.get_doc_chunks(conv_id)
            except Exception:
                indexed = {}
            ranked: list[tuple[float, str, int, str]] = []
            for name, chunks in indexed.items():
                if not chunks:
                    continue
                for i, s, t in rag_mod.TfidfIndex(chunks).retrieve(prompt):
                    ranked.append((s, name, i, t))
            # No zero-score fallback: irrelevant follow-ups send no excerpts
            # instead of leaking chunk-0 to the provider.
            ranked.sort(key=lambda r: r[0], reverse=True)
            scores.extend(s for s, _, _, _ in ranked[: rag_mod.RAG_TOP_K])
            by_doc: dict[str, list[tuple[int, float, str]]] = {}
            for s, name, i, t in ranked[: rag_mod.RAG_TOP_K]:
                by_doc.setdefault(name, []).append((i, s, t))
            for name, hits in by_doc.items():
                _append_block(name, hits)
        if not blocks:
            return None, [], []
        text = prompt + "\n\n" + "\n\n".join(b for b in blocks if b)
        if labels:
            text += "\n\n" + rag_mod.GROUNDING_LINE
        if last_images:
            content: str | list = [{"type": "text", "text": text}, *last_images]
        else:
            content = text
        new_messages = list(messages)
        new_messages[-1] = Message("user", content)
        return new_messages, labels, scores

    def _ask_vision_override(prompt: str, staged: list[Attachment]) -> None:
        """Vision-mismatch choice: Send anyway / text-only / switch model.

        Keeps staged files + restores the prompt so nothing is lost.
        Send-anyway is remembered per (provider, model) in KeyStore section
        'vision' and reflected in the badges as 'vision (override)'.
        """
        attachments.extend(staged)  # keep files so the user can decide
        try:
            refresh_chips()
        except Exception:
            pass
        _pop_ui_bubbles(1)
        if not (input_box.value or "").strip():
            input_box.value = prompt
        try:
            pid, model, _, _ = resolve_chat_target(store)
        except ValueError as e:
            chat.controls.append(error_bubble(str(e)))
            refresh_empty()
            show_snack("Setup needed — add a key under Study keys.")
            status.value = "Setup needed — add a key under Study keys."
            _safe_update()
            _scroll_to_end()
            return
        n_images = sum(1 for a in staged if a.data_url)
        key = vision_override_key(pid, model)
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Send images anyway?"),
            content=ft.Text(
                f"Model '{model}' is marked text-only, so {n_images} image(s) "
                f"were held back. If this model does take images, send anyway "
                f"(remembered for {pid} / {model}). Otherwise send text-only "
                f"or switch model.",
                size=12,
                selectable=True,
            ),
            actions=[
                ft.TextButton(
                    content=ft.Text("Switch model"),
                    on_click=lambda _: (_close(), open_model_sheet(None)),
                ),
                ft.TextButton(
                    content=ft.Text("Send text-only"),
                    on_click=lambda _: (_close(), _send_text_only()),
                ),
                ft.FilledButton(
                    content=ft.Text(f"Send anyway ({n_images} img)"),
                    on_click=lambda _: _do_override(),
                ),
            ],
        )

        def _close() -> None:
            dlg.open = False
            try:
                page.update()
            except Exception:
                pass

        def _send_text_only() -> None:
            try:
                for a in list(attachments):
                    if a.data_url:
                        attachments.remove(a)
                refresh_chips()
            except Exception:
                pass
            status.value = "Images removed — sending text + docs only."
            page.run_task(on_send, None)

        def _do_override() -> None:
            try:
                store.set("vision", key, "true")
            except Exception as e:  # noqa: BLE001
                show_snack(f"Could not remember override: {e}")
            try:
                refresh_model_button()
            except Exception:
                pass
            _close()
            show_snack(f"Vision override on for {pid} / {model}.")
            page.run_task(on_send, None)

        status.value = f"'{model}' is marked text-only — choose how to proceed."
        _safe_update()
        page.show_dialog(dlg)

    def _open_source(label: str) -> None:
        """RAG source viewer (v0.5 R4): chunk text + highlighted excerpt + pager."""
        if chats is None or state.get("conv_id") is None:
            show_snack("Open a saved chat first.")
            return
        fname, idx = parse_citation_label(label)
        try:
            indexed = chats.get_doc_chunks(state["conv_id"])
        except Exception as e:  # noqa: BLE001
            show_snack(f"Could not load index: {e}")
            return
        chunks = indexed.get(fname)
        if chunks is None:
            for name, ch in indexed.items():
                if name == fname or name.endswith(fname) or fname.endswith(name):
                    fname, chunks = name, ch
                    break
        if not chunks:
            show_snack(f"No indexed chunks for '{fname}'.")
            return
        pos = {"i": idx if idx is not None and 0 <= idx < len(chunks) else 0}
        try:
            terms = [t for t in rag_mod.tokenize(state.get("last_prompt", ""))]
        except Exception:
            terms = []
        body = ft.Text("", size=12, selectable=True)
        title = ft.Text("", size=14, weight=ft.FontWeight.BOLD)

        def _render() -> None:
            i = pos["i"]
            chunk = chunks[i]
            s, e = find_excerpt_span(chunk, terms)
            try:
                if e > s:
                    body.value = ""
                    body.spans = [
                        ft.TextSpan(chunk[:s]),
                        ft.TextSpan(chunk[s:e], style=ft.TextStyle(bgcolor=ft.Colors.YELLOW, color=ft.Colors.BLACK)),
                        ft.TextSpan(chunk[e:e + 1200]),
                    ]
                else:
                    body.spans = None
                    body.value = chunk[:1500]
                title.value = f"{fname} §{i + 1} ({i + 1}/{len(chunks)})"
            except Exception:
                try:
                    body.spans = None
                    body.value = chunk[:1500]
                    title.value = f"{fname} §{i + 1}"
                except Exception:
                    pass
            try:
                page.update()
            except Exception:
                pass

        def _step(d: int):
            def _h(_: ft.ControlEvent | None = None) -> None:
                pos["i"] = (pos["i"] + d) % len(chunks)
                _render()
            return _h

        dlg = ft.AlertDialog(
            modal=False,
            title=title,
            content=ft.Container(
                content=ft.Column([body], scroll=ft.ScrollMode.AUTO, tight=True),
                width=360,
                height=320,
            ),
            actions=[
                ft.TextButton(content=ft.Text("‹ Prev"), on_click=_step(-1)),
                ft.TextButton(content=ft.Text("Next ›"), on_click=_step(1)),
            ],
        )
        _render()
        page.show_dialog(dlg)

    def _open_doc_index(_: ft.ControlEvent | None = None) -> None:
        """Per-chat RAG index: per-file View/Delete + Clear all."""
        if chats is None or state.get("conv_id") is None:
            show_snack("Open a saved chat first, then view the doc index.")
            return
        try:
            indexed = chats.get_doc_chunks(state["conv_id"])
        except Exception as e:  # noqa: BLE001
            show_snack(f"Could not load index: {e}")
            return
        try:
            rag_on = store.get("rag", "enabled", "true").lower() != "false"
        except Exception:
            rag_on = True
        col = ft.Column(spacing=4, tight=True, scroll=ft.ScrollMode.AUTO)

        def _refresh_list() -> None:
            try:
                data = chats.get_doc_chunks(state["conv_id"])
            except Exception:
                data = {}
            rows: list[ft.Control] = [
                ft.Text(
                    f"Smart doc search: {'on' if rag_on else 'off'} (Settings → Documents)",
                    size=11,
                )
            ]
            if not data:
                rows.append(ft.Text("No documents indexed in this chat yet.", size=12))
            for name, ch in sorted(data.items()):
                def _view(_: ft.ControlEvent | None = None, _n=name) -> None:
                    _open_source(f"{_n} §1")

                def _del(_: ft.ControlEvent | None = None, _n=name) -> None:
                    try:
                        removed = chats.delete_doc_chunks(state["conv_id"], _n)
                        show_snack(f"Removed '{_n}' ({removed} chunk(s)).")
                    except Exception as e:  # noqa: BLE001
                        show_snack(f"Delete failed: {e}")
                    _refresh_list()
                    try:
                        page.update()
                    except Exception:
                        pass

                rows.append(
                    ft.Row(
                        [
                            ft.Text(f"{name}: {len(ch)} chunk(s)", size=12,
                                    expand=True, selectable=True),
                            ft.IconButton(icon=ft.Icons.VISIBILITY_OUTLINED,
                                          tooltip=f"View {name}",
                                          icon_size=18, on_click=_view),
                            ft.IconButton(icon=ft.Icons.DELETE_OUTLINE,
                                          tooltip=f"Remove {name}",
                                          icon_size=18, on_click=_del),
                        ],
                        spacing=4,
                        tight=True,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    )
                )
            col.controls = rows

        _refresh_list()

        def _clear(_: ft.ControlEvent | None = None) -> None:
            try:
                removed = chats.clear_doc_chunks(state["conv_id"])
                show_snack(f"Cleared {removed} indexed chunk(s).")
            except Exception as e:  # noqa: BLE001
                show_snack(f"Clear failed: {e}")
            dlg.open = False
            try:
                page.update()
            except Exception:
                pass

        dlg = ft.AlertDialog(
            modal=False,
            title=ft.Text("Doc index", size=14, weight=ft.FontWeight.BOLD),
            content=ft.Container(content=col, width=340, height=260),
            actions=[
                ft.TextButton(content=ft.Text("Close"),
                              on_click=lambda _: (setattr(dlg, "open", False), page.update())),
                ft.TextButton(content=ft.Text("Clear index"), on_click=_clear),
            ],
        )
        page.show_dialog(dlg)

    async def stream_reply(prompt: str) -> None:
        """Stream assistant reply for prompt + staged attachments."""
        if state.get("streaming"):
            show_snack("Already streaming — tap Stop to interrupt.")
            return
        # Claim the streaming flag BEFORE any await so a second Send tap
        # during resolve/compaction can't start a concurrent stream.
        state["streaming"] = True
        state["stop"] = False
        update_send_stop()
        staged = list(attachments)
        attachments.clear()
        state["last_prompt"] = prompt  # v0.5 R4: source-viewer highlight terms
        try:
            refresh_chips()
        except Exception:
            pass
        try:
            provider_id, model, base_url, api_key = resolve_chat_target(store)
            try:
                override_raw = store.get("vision", vision_override_key(provider_id, model), "false")
                override = override_raw == "true" if isinstance(override_raw, str) else False
            except Exception:
                override = False
            messages, provider_id, model = build_multimodal_messages(
                store, history, prompt, staged, vision_override=override
            )
        except ValueError as e:
            if "no vision support" in str(e):
                state["streaming"] = False
                update_send_stop()
                _ask_vision_override(prompt, staged)
                return
            attachments.extend(staged)  # keep files so user can fix model/key
            try:
                refresh_chips()
            except Exception:
                pass
            # Roll back the optimistic user bubble so UI/history stay in sync,
            # and restore the prompt into the input so nothing is lost.
            _pop_ui_bubbles(1)
            if not (input_box.value or "").strip():
                input_box.value = prompt
            chat.controls.append(error_bubble(str(e)))
            refresh_empty()
            show_snack("Setup needed — add a key under Keys.")
            try:
                status.value = "Setup needed — add a key under Keys."
            except Exception:
                pass
            _safe_update()
            _scroll_to_end()
            state["streaming"] = False
            update_send_stop()
            return
        try:
            provider = get_provider(provider_id, api_key, base_url)
        except ValueError as e:
            _pop_ui_bubbles(1)
            if not (input_box.value or "").strip():
                input_box.value = prompt
            chat.controls.append(error_bubble(str(e)))
            refresh_empty()
            _safe_update()
            state["streaming"] = False
            update_send_stop()
            return

        if chats is not None:
            try:
                ensure_conv(prompt, provider_id, model)
            except Exception as e:  # noqa: BLE001 — never strand streaming=True
                show_snack(f"Could not open chat history: {e}")
                state["streaming"] = False
                update_send_stop()
                return

        # Auto-compact BEFORE building the outgoing payload, so the current
        # turn actually sends the compacted history (previously compaction
        # rewrote `history` after `messages` was already built, helping only
        # the *next* turn). Measured with the real multimodal builder plus
        # the pinned preamble, so big attachments trip it too.
        compacted = False
        try:
            auto_raw = store.get("chat", "auto_compact", "false")
            auto_compact = auto_raw.lower() == "true" if isinstance(auto_raw, str) else False
        except Exception:
            auto_compact = False
        if auto_compact:
            try:
                probe = build_chat_messages(
                    history, prompt, staged, provider_id, model,
                    vision_override=True,
                )
                try:
                    pin_probe = _pinned_block()
                    if pin_probe:
                        probe = [Message("system", pin_probe), *probe]
                except Exception:
                    pass
                do_compact = should_compact(probe, model)
            except Exception:
                do_compact = False
            if do_compact:
                keep_from = compaction_target_count(history, model)
                older = history[:keep_from]
                recent = [m for m in history[keep_from:] if m.role != "system"]
                # Fold any earlier compaction summary into the new one so
                # repeated compactions keep a single system preamble.
                prior = "\n\n".join(
                    m.content for m in history
                    if m.role == "system" and isinstance(m.content, str)
                )
                if older or prior:
                    bits = []
                    if prior:
                        bits.append(prior)
                    bits.append(
                        "\n\n".join(
                            f"{m.role.upper()}: {m.content if isinstance(m.content, str) else m.content}"
                            for m in older
                        )
                    )
                    transcript = "\n\n".join(b for b in bits if b.strip())
                    try:
                        summary = await provider.acomplete(
                            [
                                Message(
                                    "user",
                                    "Summarize this conversation for future continuation. "
                                    "Keep decisions, facts, constraints, unresolved questions, "
                                    "and user preferences. Be concise and do not invent details.\n\n"
                                    + transcript,
                                )
                            ],
                            model,
                            max_tokens=700,
                        )
                    except Exception as e:  # noqa: BLE001 — never drop the reply
                        show_snack(f"Compaction skipped ({e}); sending full context.")
                        summary = ""
                    if summary.strip():
                        history[:] = [
                            Message(
                                "system",
                                "Earlier conversation summary:\n" + summary.strip(),
                            ),
                            *recent,
                        ]
                        compacted = True
                        if chats is not None and state["conv_id"] is not None:
                            try:
                                chats.replace_messages(state["conv_id"], history)
                            except Exception as e:  # noqa: BLE001 — keep chatting even if persist fails
                                show_snack(f"Compacted locally — save failed: {e}")

        try:
            try:
                ov2_raw = store.get("vision", vision_override_key(provider_id, model), "false")
                override2 = ov2_raw == "true" if isinstance(ov2_raw, str) else False
            except Exception:
                override2 = False
            if compacted:
                # History changed — rebuild the payload from compacted history.
                messages, _, _ = build_multimodal_messages(
                    store, history, prompt, staged, vision_override=(override or override2)
                )
            # else: reuse `messages` built above (identical inputs).
        except ValueError as e:
            if "no vision support" in str(e):
                state["streaming"] = False
                update_send_stop()
                _ask_vision_override(prompt, staged)
                return
            attachments.extend(staged)
            try:
                refresh_chips()
            except Exception:
                pass
            _pop_ui_bubbles(1)
            if not (input_box.value or "").strip():
                input_box.value = prompt
            chat.controls.append(error_bubble(str(e)))
            refresh_empty()
            show_snack("Setup needed — add a key under Keys.")
            try:
                status.value = "Setup needed — add a key under Keys."
            except Exception:
                pass
            _safe_update()
            _scroll_to_end()
            state["streaming"] = False
            update_send_stop()
            return

        # v0.4.0 RAG: swap long-doc injection for retrieved excerpts.
        rag_sources: list[str] = []
        rag_scores: list[float] = []
        try:
            rebuilt, rag_sources, rag_scores = _maybe_apply_rag(prompt, staged, messages)
            if rebuilt is not None:
                messages = rebuilt
        except Exception:
            rag_sources = []
            rag_scores = []

        # Pinned user messages ride along as a USER block with explicit
        # untrusted provenance (never system — avoids privilege elevation).
        try:
            pin_block = _pinned_block()
            if pin_block and not any(
                isinstance(m.content, str) and "Pinned context" in m.content
                for m in messages
            ):
                messages = [Message("user", "<pinned-context-untrusted>\n" + pin_block), *messages]
        except Exception:
            pass
        # INF ai: study-tutor preamble so replies teach, not just answer.
        try:
            if not any(
                isinstance(m.content, str) and "You are INF ai" in m.content
                for m in messages
                if m.role == "system"
            ):
                messages = [Message("system", STUDY_PREAMBLE), *messages]
        except Exception:
            pass

        # NOTE: auto-compact already ran above (before the payload was
        # built), so `messages` reflects the compacted history here.

        # v0.5 R1: isolated streaming row — live flushes update only this
        # control (self.update) instead of the whole page. Any failure
        # falls back to the legacy page.update() path.
        # v0.6: "Thinking…" indicator until the first token arrives, then a
        # readable word-paced reveal (StreamRevealPacer) instead of burst
        # chunks — the reply streams at a pace the user can read along with.
        try:
            assistant_row = StreamingBubble(lambda: _markdown(""), timestamp=now_hhmm())
            md = assistant_row.md
            iso = {"on": True}
        except Exception:
            md = _markdown("")
            assistant_row = assistant_bubble(
                md,
                on_copy=None,  # wired after completion with full text
                on_retry=None,
                timestamp=now_hhmm(),
            )
            iso = {"on": False}
        indicator = typing_indicator()
        first_token = {"seen": False}

        def _render_frame(frame: str) -> None:
            # First frame: dismiss the typing indicator (robust remove —
            # the rest is a no-op if it was never mounted).
            if not first_token["seen"]:
                first_token["seen"] = True
                try:
                    if indicator in chat.controls:
                        chat.controls.remove(indicator)
                except Exception:
                    pass
            frame = _tex(frame)
            if iso["on"]:
                try:
                    if assistant_row.set_stream_text(frame):
                        _refresh_fab_count()
                        return
                except Exception:
                    pass
                iso["on"] = False
            md.value = frame
            try:
                page.update()
            except Exception:
                pass
            _refresh_fab_count()

        chat.controls.append(indicator)
        chat.controls.append(assistant_row)
        refresh_empty()
        # streaming flag was claimed before the awaits above; just refresh
        # the stop handle + button state here.
        try:
            # Handle for Stop: cancelling unblocks the stream even during
            # server silence (the flag alone only fires between chunks).
            # Stale handles are safe — on_stop_send skips done tasks.
            state["stream_task"] = asyncio.current_task()
        except Exception:
            pass
        update_send_stop()
        try:
            in_tokens = estimate_tokens(prompt) + sum(
                estimate_tokens(getattr(a, "text", "")) for a in staged
            )
        except Exception:
            in_tokens = estimate_tokens(prompt)
        try:
            trunc = sum(1 for a in staged if isinstance(getattr(a, "extra", None), dict) and a.extra.get("truncated"))
        except Exception:
            trunc = 0
        try:
            status.value = (
                f"{provider_id} / {model} • ~{in_tokens} tokens in"
                + (f" • {len(staged)} file(s)" if staged else "")
                + (" • truncated" if (trunc and not rag_sources) else "")
                + (f" • RAG {len(rag_sources)} excerpt(s): " + ", ".join(rag_sources[:2]) if rag_sources else "")
                + (" • context compacted" if compacted else "")
                + " • streaming…"
            )
        except Exception:
            pass
        # v0.5 R4: "why these" relevance tooltip on the RAG status.
        try:
            status.tooltip = bands_tooltip(score_bands(rag_scores)) if rag_scores else None
        except Exception:
            pass
        page.update()

        acc = StreamAccumulator(last_flush=time.monotonic())
        pacer = StreamRevealPacer()
        stream_error: str | None = None
        try:
            gen_max = _gen_max_for(store, provider_id, model)
            async for chunk in provider.chat_stream(messages, model, max_tokens=gen_max):
                if state["stop"]:
                    break
                acc.push(chunk, time.monotonic())
                pacer.push(chunk)
                frame = pacer.poll()
                if frame is None:
                    continue  # nothing new to reveal this tick
                _render_frame(frame)
            # Drain the reveal buffer at reading pace — a fast provider
            # never dumps whole paragraphs at once; the pacer's catch-up
            # keeps long replies from lagging "done" absurdly.
            while not state["stop"]:
                frame = pacer.poll(force=True)
                if frame is None:
                    break
                _render_frame(frame)
                await asyncio.sleep(pacer.tick_s)
            _scroll_to_end()
        except asyncio.CancelledError:
            # Stop tapped during server silence: treat as a normal stop so
            # the partial reply finalizes instead of killing the task.
            state["stop"] = True
        except ProviderError as e:
            stream_error = f"Failed: {e.friendly()}"
        except Exception as e:  # noqa: BLE001 — surface unexpected as bubble
            stream_error = f"Failed: {e}"
        finally:
            # The indicator never lingers (error before first token / stop).
            try:
                if indicator in chat.controls:
                    chat.controls.remove(indicator)
            except Exception:
                pass
            state["streaming"] = False
            try:
                state.pop("stream_task", None)
            except Exception:
                pass
            update_send_stop()
            try:
                page.update()
            except Exception:
                pass

        text = "".join(acc.acc).strip()
        if stream_error is not None:
            # Finalize the partial bubble (no dangling cursor), then explain.
            md.value = _tex(text) if text else "_(reply failed)_"
            chat.controls.append(error_bubble(stream_error))
            refresh_empty()
            # Still persist partial progress so history/UI stay consistent.
            if text:
                _wire_assistant_actions(assistant_row, text)
                history.append(messages[-1])
                history.append(Message("assistant", text))
                try:
                    assistant_row.key = row_key(len(history) - 1)
                except Exception:
                    pass
                state["last_assistant"] = text
                if chats is not None:
                    try:
                        ensure_conv(prompt, provider_id, model)
                        if state.get("conv_id") is None:
                            raise ValueError("No conversation open.")
                        chats.add_message(state["conv_id"], "user", messages[-1].content)
                        chats.add_message(state["conv_id"], "assistant", text)
                        refresh_drawer()
                    except Exception:
                        pass
            else:
                # No tokens at all — drop the empty streaming bubble.
                try:
                    if assistant_row in chat.controls:
                        chat.controls.remove(assistant_row)
                except Exception:
                    pass
            status.value = stream_error
            refresh_empty()
            _safe_update()
            _scroll_to_end()
            return

        text = "".join(acc.acc).strip()
        if state["stop"] and not text:
            md.value = "_(stopped)_"
        else:
            md.value = _tex(text) or "_(empty reply)_"
        # Wire per-bubble actions now that full text is known.
        # assistant_bubble stores its actions Row in row.data (no fragile indexing).
        full = text
        try:
            reply_tokens = estimate_tokens(text)
        except Exception:
            reply_tokens = None
        # Refresh footer with token count (assistant_bubble baked the
        # pre-stream footer; update the actions-row label in place).
        try:
            actions_row = assistant_row.data
            if isinstance(actions_row, ft.Row) and actions_row.controls:
                from app.ui.widgets.message_bubble import token_footer as _tf
                label = _tf(reply_tokens, now_hhmm())
                if label and isinstance(actions_row.controls[0], ft.Text):
                    actions_row.controls[0].value = label
        except Exception:
            pass
        _wire_assistant_actions(assistant_row, full)
        # v0.4.0 artifacts + citations (Flet-only, zero-config fallback):
        # fenced ```table/json/card blocks render as cards below the reply.
        try:
            for lang, body in extract_artifacts(text):
                chat.controls.append(artifact_control(lang, body))
                if lang == "chart":
                    payload = parse_chart_payload(body)
                    if payload:
                        chat.controls.append(chart_control(payload))
                try:
                    artifacts.add(state.get("conv_id"), lang, body)
                except Exception:
                    pass
            for label in extract_citations(text):
                try:
                    chat.controls.append(citation_card(label, on_tap=lambda _, lab=label: _open_source(lab)))
                except Exception:
                    chat.controls.append(citation_card(label))
        except Exception:
            pass
        history.append(messages[-1])  # built user msg (keeps file context)
        history.append(Message("assistant", text))
        # Bound in-memory history: very long sessions grew chat.controls +
        # history without limit (per-frame Markdown re-parse O(n), OOM).
        MAX_HISTORY = 500
        if len(history) > MAX_HISTORY:
            del history[: len(history) - MAX_HISTORY]
        try:
            assistant_row.key = row_key(len(history) - 1)
        except Exception:
            pass
        state["last_assistant"] = text
        if chats is not None and text:
            try:
                ensure_conv(prompt, provider_id, model)
                if state.get("conv_id") is None:
                    raise ValueError("No conversation open.")
                chats.add_message(state["conv_id"], "user", messages[-1].content)
                chats.add_message(state["conv_id"], "assistant", text)
                # v0.5 R7: accumulate per-conversation token estimates.
                try:
                    chats.add_token_usage(state["conv_id"], context_used(messages), estimate_tokens(text))
                except Exception:
                    pass
                refresh_drawer()
            except Exception as e:  # noqa: BLE001 — never break chat on DB error
                show_snack(f"Reply done, but history save failed: {e}")
                try:
                    status.value = f"Reply done, but history save failed: {e}"
                except Exception:
                    pass
                try:
                    page.update()
                except Exception:
                    pass
                return
        status.value = (
            f"{provider_id} / {model} • reply ~{estimate_tokens(text)} tokens"
            + (" • context compacted" if compacted else "")
            + (" • stopped" if state["stop"] else " • done")
        )
        # v0.5 R4: keep the relevance explainer on the final status too.
        try:
            if rag_scores:
                status.tooltip = bands_tooltip(score_bands(rag_scores))
        except Exception:
            pass
        # v0.5 R6: keep an open find index fresh after each reply.
        try:
            if find_ui.get("open"):
                find_ui["matches"] = build_match_index(find_texts(), find_ui.get("query", ""))
                total = len(find_ui["matches"])
                pos = min(find_ui.get("pos", 0), max(0, total - 1)) if total else 0
                find_ui["pos"] = pos
                find_count.value = format_counter(pos, total)
        except Exception:
            pass
        try:
            _refresh_meter()
        except Exception:
            pass
        refresh_empty()
        page.update()

    async def on_send(_: ft.ControlEvent | None) -> None:
        if state.get("streaming"):
            show_snack("Already streaming — tap Stop to interrupt.")
            return
        # Ownership: the "+" button path (on_stop_send) claims send_queued
        # synchronously before scheduling us, so a second tap sees the flag
        # and never schedules. Direct callers (keyboard submit) claim here.
        # Either way the flag is cleared in `finally` below.
        if not state.get("send_queued"):
            state["send_queued"] = True
        try:
            text = (input_box.value or "").strip() if isinstance(input_box.value, str) else ""
            if not text and not attachments:
                return
            if not text:
                text = "(see attached files)"
            text = text[:20000]
            # v0.6 image output: "/image a sunset" opens the image dialog with
            # the prompt prefilled (same flow as the "+" menu item).
            if text.lower().startswith("/image ") or text.lower() == "/image":
                img_prompt = text[6:].strip()
                input_box.value = ""
                _safe_update()
                _open_image_dialog(img_prompt)
                return
            # v0.5 R2: compare mode diverts to the side-by-side path.
            if compare_ui.get("active"):
                input_box.value = ""
                hist_ui["shown"] = None  # v0.5 R1: live chat always shows all
                await _compare_send(text)
                return
            # Pre-validate target so a missing key/model never eats the draft.
            try:
                resolve_chat_target(store)
            except ValueError as e:
                chat.controls.append(error_bubble(str(e)))
                refresh_empty()
                show_snack("Setup needed — add a key under Study keys.")
                try:
                    status.value = "Setup needed — add a key under Study keys."
                except Exception:
                    pass
                _safe_update()
                _scroll_to_end()
                return
            input_box.value = ""
            suffix = f"  +{len(attachments)} file(s)" if attachments else ""
            hist_ui["shown"] = None  # v0.5 R1: live chat always shows all
            _append_user(text + suffix)
            _safe_update()
            await stream_reply(text)
        finally:
            try:
                state.pop("send_queued", None)
            except Exception:
                pass

    def _show_mic_soon() -> None:
        """Explain the MIC placeholder — wired action, not dead code.

        Voice needs RECORD_AUDIO permission + a speech-to-text plugin
        (not bundled). Keep the MIC affordance so the send morph stays
        discoverable, but be honest about what's missing.
        """
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Voice input — not yet"),
            content=ft.Text(
                "Tap-to-talk needs microphone permission + on-device "
                "speech recognition, which isn't bundled in this build. "
                "Type for now — voice is tracked for a later release. "
                "Your draft is kept.",
                size=12,
                selectable=True,
            ),
            actions=[
                ft.TextButton(
                    content=ft.Text("Got it"),
                    on_click=lambda _: (setattr(dlg, "open", False), page.update()),
                ),
            ],
        )
        page.show_dialog(dlg)

    def on_stop_send(_: ft.ControlEvent) -> None:
        if state.get("streaming"):
            state["stop"] = True
            try:
                status.value = "Stopping…"
            except Exception:
                pass
            _safe_update()
            # Unblock the stream even mid-silence: cancelling lands in the
            # loop's CancelledError branch, which finalizes normally.
            try:
                t = state.get("stream_task")
                if t is not None and not t.done():
                    t.cancel()
            except Exception:
                pass
            return
        if state.get("send_queued"):
            return  # a send is already scheduled — don't queue a second
        try:
            has_text = bool((input_box.value or "").strip()) if isinstance(input_box.value, str) else False
            st = InputState(
                streaming=False,
                has_text=has_text,
                has_attachments=bool(attachments),
            )
            kind, _tip = send_button_mode(st)
        except Exception:
            kind = "SEND"
        if kind == "MIC":
            show_snack("Type a study question first.")
            return
        state["send_queued"] = True  # claim synchronously — closes double-tap race
        try:
            page.run_task(on_send, _)
        except Exception:
            try:
                state.pop("send_queued", None)
            except Exception:
                pass

    def on_clear(_: ft.ControlEvent | None) -> None:
        if state["streaming"]:
            show_snack("Wait for the current reply to finish (or tap Stop).")
            return
        history.clear()
        attachments.clear()
        refresh_chips()
        chat.controls.clear()
        try:
            artifacts.clear(state.get("conv_id"))
            artifacts.clear(None)
        except Exception:
            pass
        state["conv_id"] = None
        state["last_assistant"] = ""
        status.value = "Chat cleared (new unsaved chat)."
        refresh_drawer()
        refresh_empty()
        try:
            _refresh_meter()
        except Exception:
            pass
        page.update()

    send_stop_btn.on_click = on_stop_send

    def _submit_send(_: ft.ControlEvent | None = None) -> None:
        # TextField.on_submit may not await coroutines across Flet versions —
        # schedule explicitly like every other async entry point.
        try:
            page.run_task(on_send, None)
        except Exception:
            pass

    input_box.on_submit = _submit_send

    def _on_input_change(_: ft.ControlEvent | None = None) -> None:
        if not state["streaming"]:
            update_send_stop()

    try:
        input_box.on_change = _on_input_change
    except Exception:
        pass

    # ---- history drawer + theme (P4) ----
    # v0.2.0: user_text_of lives in app.core.history_utils (tested); keep
    # local name as alias so per-bubble closures keep working.
    def _show_earlier(_: ft.ControlEvent | None = None) -> None:
        # v0.5 R1: expand the render window, then restore position at the
        # previously-first message so reading isn't lost.
        try:
            first_key = chat.controls[1].key if len(chat.controls) > 1 else None
        except Exception:
            first_key = None
        try:
            cur = hist_ui.get("shown") or HISTORY_WINDOW
            hist_ui["shown"] = cur + HISTORY_WINDOW
        except Exception:
            hist_ui["shown"] = None
        render_history_to_ui()
        if first_key:
            try:
                chat.scroll_to(key=first_key, duration=200)
            except Exception:
                pass
        try:
            page.update()
        except Exception:
            pass

    def render_history_to_ui() -> None:
        state["bulk_render"] = True
        try:
            chat.controls.clear()
            n = len(history)
            # v0.5 R1: windowed render — trailing HISTORY_WINDOW messages plus
            # a "Show earlier" header instead of rebuilding huge threads.
            try:
                start, show_header, header_label = window_slice(n, hist_ui.get("shown"))
            except Exception:
                start, show_header, header_label = 0, False, ""
            if show_header:
                chat.controls.append(
                    ft.Row(
                        [ft.TextButton(content=ft.Text(header_label, size=12),
                                       on_click=_show_earlier)],
                        alignment=ft.MainAxisAlignment.CENTER,
                        key="show-earlier",
                    )
                )
            for gi in range(start, n):
                try:
                    m = history[gi]
                except (IndexError, TypeError):
                    continue
                if getattr(m, "role", "") == "user":
                    try:
                        text, has_images = user_text_of(m.content)
                    except Exception:
                        text, has_images = "", False
                    _append_user(text + ("  (+images)" if has_images else ""), key_idx=gi)
                elif getattr(m, "role", "") == "assistant":
                    try:
                        body = assistant_text_of(m.content)
                    except Exception:
                        body = ""
                    # v0.6: generated-image notes rebuild the card from the
                    # saved file when it still exists; otherwise the note text
                    # shows like any other reply.
                    try:
                        shown = _append_saved_image(body, key_idx=gi)
                    except Exception:
                        shown = False
                    if not shown:
                        _append_assistant(body, key_idx=gi)
                    # Reloaded chats must show the same inline artifact cards
                    # as live replies (old code only showed bubbles).
                    try:
                        for lang, abody in extract_artifacts(body):
                            chat.controls.append(artifact_control(lang, abody))
                            if lang == "chart":
                                payload = parse_chart_payload(abody)
                                if payload:
                                    chat.controls.append(chart_control(payload))
                    except Exception:
                        pass
                elif getattr(m, "role", "") == "system":
                    # Compaction summary — show as a compact info row so context
                    # isn't silently dropped when reopening a compacted chat.
                    try:
                        body = m.content if isinstance(m.content, str) else str(m.content)
                    except Exception:
                        body = ""
                    chat.controls.append(
                        ft.Row(
                            [
                                ft.Icon(ft.Icons.HISTORY, size=14),
                                ft.Text(
                                    f"Earlier summary: {body[:300]}{'…' if len(body) > 300 else ''}",
                                    size=11,
                                    selectable=True,
                                    expand=True,
                                ),
                            ],
                            spacing=6,
                            tight=True,
                        )
                    )
            refresh_empty()
        finally:
            try:
                state.pop("bulk_render", None)
            except Exception:
                pass
        _scroll_to_end()

    def ensure_conv(first_prompt: str, provider_id: str, model: str) -> None:
        if chats is None or state.get("conv_id") is not None:
            return
        try:
            title = short_title(first_prompt if isinstance(first_prompt, str) else "New chat")
        except Exception:
            title = "New chat"
        try:
            pid = provider_id if isinstance(provider_id, str) else ""
            mod = model if isinstance(model, str) else ""
            state["conv_id"] = chats.create_conversation(title, pid, mod)
        except Exception as e:  # noqa: BLE001 — caller decides whether to strand
            state["conv_id"] = None
            raise

    drawer_list = ft.Column(spacing=2, scroll=ft.ScrollMode.AUTO, expand=True)
    drawer_search = ft.TextField(label="Search chats", prefix_icon=ft.Icons.SEARCH, dense=True)

    def _set_hist_filter(filt: str) -> None:
        def _h(_: ft.ControlEvent | None = None) -> None:
            hist_ui["filter"] = filt
            refresh_drawer()
            try:
                page.update()
            except Exception:
                pass
        return _h

    hist_filter_row = ft.Row(
        [ft.Chip(label=ft.Text(f, size=12), data=f, on_click=_set_hist_filter(f))
         for f in HISTORY_FILTERS],
        spacing=6, tight=True, scroll=ft.ScrollMode.AUTO,
    )
    hist_provider_dd = ft.Dropdown(label="Provider", dense=True,
                                   options=[ft.dropdown.Option("")] + [
                                       ft.dropdown.Option(pid) for pid in PROVIDER_IDS],
                                   value="")

    def _on_hist_provider(_: ft.ControlEvent | None = None) -> None:
        try:
            hist_ui["provider"] = (hist_provider_dd.value or "").strip() if isinstance(hist_provider_dd.value, str) else ""
        except Exception:
            hist_ui["provider"] = ""
        refresh_drawer()
        try:
            page.update()
        except Exception:
            pass

    hist_provider_dd.on_change = _on_hist_provider
    bulk_bar = ft.Row(tight=True, spacing=6, visible=False)

    def _toggle_bulk(_: ft.ControlEvent | None = None) -> None:
        hist_ui["bulk"] = not hist_ui.get("bulk")
        if not hist_ui["bulk"]:
            hist_ui["checked"] = set()
        refresh_drawer()
        try:
            page.update()
        except Exception:
            pass

    def _bulk_delete(_: ft.ControlEvent | None = None) -> None:
        ids = sorted(hist_ui.get("checked", set()))
        if not ids:
            show_snack("Select chats first.")
            return
        if state.get("streaming"):
            show_snack("Wait for the reply to finish.")
            return
        fails = 0
        for cid in ids:
            try:
                chats.delete_conversation(int(cid))
            except Exception:
                fails += 1
        if state.get("conv_id") in ids:
            new_chat(None)
            hist_ui["checked"] = set()
            hist_ui["bulk"] = False
            return
        hist_ui["checked"] = set()
        hist_ui["bulk"] = False
        refresh_drawer()
        show_snack(f"Deleted {len(ids) - fails} chat(s).")
        try:
            page.update()
        except Exception:
            pass

    def _sync_bulk_bar() -> None:
        try:
            n = len(hist_ui.get("checked", set()))
            bulk = bool(hist_ui.get("bulk"))
            bulk_bar.visible = bulk
            bulk_bar.controls = [
                ft.Text(f"{n} selected", size=12, expand=True),
                ft.TextButton(content=ft.Text("Delete"), on_click=_bulk_delete),
                ft.TextButton(content=ft.Text("Done"), on_click=_toggle_bulk),
            ]
        except Exception:
            pass

    def load_conv(conv_id: int) -> None:
        if chats is None:
            show_snack("History is unavailable.")
            return
        if state["streaming"]:
            show_snack("Wait for the current reply to finish before switching chats.")
            return
        try:
            loaded = chats.get_messages(conv_id)
            # Empty conversations are still openable (e.g. created but the
            # first reply failed before persisting). Refusing to open them
            # strands a drawer row that can never be tapped into.
            history.clear()
            history.extend(loaded or [])
            state["conv_id"] = conv_id
            # Rebuild the in-memory artifact registry so the Artifacts
            # panel works for reloaded chats (registry is not persisted).
            try:
                texts = [m.content for m in loaded
                         if m.role == "assistant" and isinstance(m.content, str)]
                artifacts.rebuild_from_texts(conv_id, texts)
            except Exception:
                pass
            # v0.5 R1: window long threads on open.
            hist_ui["shown"] = HISTORY_WINDOW if len(history) > HISTORY_WINDOW else None
            state["last_assistant"] = next(
                (
                    m.content
                    for m in reversed(history)
                    if m.role == "assistant" and isinstance(m.content, str)
                ),
                "",
            )
            attachments.clear()
            try:
                refresh_chips()
            except Exception:
                pass
            render_history_to_ui()
            try:
                _refresh_meter()
            except Exception:
                pass
            try:
                close_find()
            except Exception:
                pass
            status.value = f"Loaded chat #{conv_id} ({len(history)} messages)."
            refresh_drawer()
            try:
                page.run_task(close_history, None)
            except Exception:
                pass
            try:
                page.update()
            except Exception as e:  # noqa: BLE001 — never leave the tap looking dead
                show_snack(f"Chat loaded, but refresh failed: {e}")
        except (sqlite3.Error, ValueError, TypeError, OSError) as e:
            show_snack(f"Could not open chat: {e}")
            status.value = f"Could not open chat #{conv_id}: {e}"
            try:
                page.update()
            except Exception:
                pass

    def rename_conv(conv_id: int, current: str) -> None:
        field = ft.TextField(label="Chat title", value=current or "", autofocus=True, dense=True)
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Rename chat"),
            content=field,
            actions=[
                ft.TextButton(content=ft.Text("Cancel"), on_click=lambda _: _close()),
                ft.TextButton(content=ft.Text("Save"), on_click=lambda _: _save()),
            ],
        )

        def _close() -> None:
            dlg.open = False
            page.update()

        def _save() -> None:
            title = (field.value or "").strip() or current or "New chat"
            try:
                assert chats is not None
                chats.rename_conversation(conv_id, title[:80])
            except Exception as e:  # noqa: BLE001
                show_snack(f"Rename failed: {e}")
                return
            _close()
            refresh_drawer()
            page.update()

        page.show_dialog(dlg)

    def delete_conv(conv_id: int) -> None:
        if chats is None:
            return
        if state["streaming"]:
            show_snack("Wait for the current reply to finish before deleting.")
            return
        try:
            chats.delete_conversation(conv_id)
        except Exception as e:  # noqa: BLE001
            show_snack(f"Delete failed: {e}")
            return
        if state["conv_id"] == conv_id:
            new_chat(None)
            return
        refresh_drawer()
        _safe_update()

    def refresh_drawer() -> None:
        drawer_list.controls.clear()
        if chats is None:
            drawer_list.controls.append(
                ft.Text("History unavailable. Check the status message.", size=12)
            )
            return
        query = (drawer_search.value or "").strip()
        try:
            convs = chats.list_conversations()
        except (sqlite3.Error, OSError, ValueError) as e:
            drawer_list.controls.append(ft.Text(f"Could not load history: {e}", size=12))
            return
        # v0.2.0: content-aware search — match title/provider/model via helper,
        # plus message-body matches via ChatStore.search (FTS5 or LIKE fallback).
        if query:
            convs = filter_conversations(convs, query)
            try:
                body_hits = set(chats.search_conversations(query))
                if body_hits:
                    seen = {c["id"] for c in convs}
                    for c in chats.list_conversations():
                        if c["id"] in body_hits and c["id"] not in seen:
                            convs.append(c)
            except Exception:
                pass
        def _open(e: ft.ControlEvent) -> None:
            # Never swallow tap errors silently — a dead tap with no
            # feedback is indistinguishable from "history is broken".
            try:
                cid_raw = getattr(e.control, "data", None)
                if hist_ui.get("bulk"):
                    _bulk_toggle(int(cid_raw))
                    return
                load_conv(int(cid_raw))
            except (TypeError, ValueError):
                show_snack("Could not open that chat (bad id).")
            except Exception as ex:  # noqa: BLE001 — surface, don't strand
                show_snack(f"Could not open chat: {ex}")

        def _rename(e: ft.ControlEvent) -> None:
            try:
                cid = int(e.control.data)
                load_title = next((x.get("title", "") for x in convs if x["id"] == cid), "")
                rename_conv(cid, load_title)
            except Exception:
                pass

        def _delete(e: ft.ControlEvent) -> None:
            try:
                delete_conv(int(e.control.data))
            except Exception:
                pass

        def _pin(e: ft.ControlEvent) -> None:
            try:
                cid = int(e.control.data)
                cur = next((x for x in convs if x["id"] == cid), {})
                chats.set_pinned(cid, not cur.get("pinned"))
                refresh_drawer()
                _safe_update()
            except Exception as ex:  # noqa: BLE001
                show_snack(f"Pin failed: {ex}")

        def _archive(e: ft.ControlEvent) -> None:
            try:
                cid = int(e.control.data)
                cur = next((x for x in convs if x["id"] == cid), {})
                archiving = not cur.get("archived")
                chats.set_archived(cid, archiving)
                if state.get("conv_id") == cid and archiving:
                    # Archiving the open chat: start fresh so the user isn't
                    # stuck editing a hidden conversation.
                    new_chat(None)
                    show_snack("Archived current chat — started a new one.")
                    return
                refresh_drawer()
                _safe_update()
                show_snack(f"{'Archived' if archiving else 'Unarchived'} chat #{cid}.")
            except Exception as ex:  # noqa: BLE001
                show_snack(f"Archive failed: {ex}")

        def _bulk_toggle(cid: int) -> None:
            checked = hist_ui.setdefault("checked", set())
            if cid in checked:
                checked.discard(cid)
            else:
                checked.add(cid)
            refresh_drawer()
            try:
                page.update()
            except Exception:
                pass

        def _on_bulk(e: ft.ControlEvent) -> None:
            try:
                _bulk_toggle(int(e.control.data))
            except Exception:
                pass

        # v0.4 refinement: tab + provider filters, then grouping.
        try:
            convs = apply_history_filter(convs, hist_ui.get("filter", "all"),
                                         hist_ui.get("provider", ""))
        except Exception:
            pass
        # v0.4.0 inbox grouping (ChatInbox pattern, Flet-only). Falls back
        # to a flat list if grouping fails.
        try:
            sections = group_conversations(convs)
        except Exception:
            sections = [("", convs)]
        try:
            for label, items in sections:
                if label:
                    drawer_list.controls.append(
                        ft.Text(label, size=11, weight=ft.FontWeight.BOLD,
                                color=ft.Colors.ON_SURFACE_VARIANT)
                    )
                for c in items:
                    cid = c["id"]
                    drawer_list.controls.append(
                        # Pin lives in the ⋮ menu (archive stays off: the
                        # filter chips are hidden, so archived chats would
                        # vanish with no way back).
                        inbox_tile(c, cid == state["conv_id"], _open, _rename, _delete,
                                   on_pin=_pin, on_archive=None,
                                   bulk_mode=False, bulk_checked=False,
                                   on_bulk=_on_bulk)
                    )
        except Exception:
            for c in convs:
                cid = c["id"]
                selected = cid == state["conv_id"]
                drawer_list.controls.append(
                    ft.ListTile(
                        leading=ft.Icon(ft.Icons.FORUM_OUTLINED, size=20),
                        title=ft.Text(c["title"] or "New chat", size=13, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        subtitle=ft.Text(f"{c['provider']} / {c['model']}".strip(" /"), size=11),
                        selected=selected,
                        data=cid,
                        on_click=_open,
                    )
                )
        if not drawer_list.controls:
            drawer_list.controls.append(ft.Text(
                empty_history_message(hist_ui.get("filter", "all"), query), size=12))
        try:
            _sync_bulk_bar()
        except Exception:
            pass

    # Perf: search fields rebuild whole lists per keystroke (model rows
    # carry SVG badges; drawer rows carry popup menus). Debounce typing so
    # fast typists trigger one rebuild instead of one per character.
    _search_gen = {"sheet": 0, "drawer": 0}

    def _debounced(key: str, fn) -> None:
        _search_gen[key] = _search_gen.get(key, 0) + 1
        gen = _search_gen[key]

        async def _run() -> None:
            await asyncio.sleep(0.2)
            if gen != _search_gen.get(key, 0):
                return  # superseded by newer keystroke
            try:
                fn()
            except Exception:
                pass

        try:
            page.run_task(_run)
        except Exception:
            try:
                fn()
            except Exception:
                pass

    def _on_drawer_search(_: ft.ControlEvent) -> None:
        def _do() -> None:
            refresh_drawer()
            page.update()
        _debounced("drawer", _do)

    drawer_search.on_change = _on_drawer_search

    def new_chat(_: ft.ControlEvent | None) -> None:
        history.clear()
        attachments.clear()
        refresh_chips()
        chat.controls.clear()
        try:
            artifacts.clear(state.get("conv_id"))
            artifacts.clear(None)
        except Exception:
            pass
        state["conv_id"] = None
        state["last_assistant"] = ""
        hist_ui["shown"] = None
        close_find()
        try:
            _refresh_meter()
        except Exception:
            pass
        status.value = "New chat started."
        try:
            refresh_drawer()
        except Exception:
            pass
        refresh_empty()
        try:
            page.run_task(close_history, None)
        except Exception:
            pass
        page.update()

    async def export_conv(kind: str) -> None:
        if chats is None or state["conv_id"] is None:
            show_snack("Open a saved chat first, then export.")
            status.value = "Open a saved chat first, then export."
            page.update()
            return
        try:
            if kind == "md":
                payload = chats.export_markdown(state["conv_id"]).encode("utf-8")
                fname, exts = f"chat-{state['conv_id']}.md", ["md"]
            else:
                payload = chats.export_json(state["conv_id"]).encode("utf-8")
                fname, exts = f"chat-{state['conv_id']}.json", ["json"]
            saved = await picker.save_file(
                dialog_title=f"Export chat as {kind.upper()}",
                file_name=fname,
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=exts,
                src_bytes=payload,
            )
            msg = f"Exported {fname}." if saved else "Export cancelled."
            show_snack(msg)
            status.value = msg
        except Exception as e:  # noqa: BLE001
            show_snack(f"Export failed: {e}")
            status.value = f"Export failed: {e}"
        page.update()

    def apply_theme(mode: str) -> None:
        page.theme_mode = ft.ThemeMode.LIGHT if mode == "light" else ft.ThemeMode.DARK
        # v0.4 refinement: OLED + high-contrast + font scale from KeyStore.
        try:
            oled = store.get("ui", "oled", "false").lower() == "true"
            hc = store.get("ui", "high_contrast", "false").lower() == "true"
            page.theme = app_theme(oled=oled, high_contrast=hc)
            page.dark_theme = app_theme(oled=oled, high_contrast=hc)
        except Exception:
            pass
        try:
            theme_btn.icon = (
                ft.Icons.DARK_MODE
                if page.theme_mode == ft.ThemeMode.LIGHT
                else ft.Icons.LIGHT_MODE
            )
            page.update()
        except Exception:
            pass

    def toggle_theme(_: ft.ControlEvent) -> None:
        apply_theme("light" if page.theme_mode != ft.ThemeMode.LIGHT else "dark")
        try:
            store.set(
                "ui", "theme", "light" if page.theme_mode == ft.ThemeMode.LIGHT else "dark"
            )
        except Exception:
            pass
        page.update()

    theme_btn = ft.IconButton(
        icon=ft.Icons.LIGHT_MODE if saved_theme != "light" else ft.Icons.DARK_MODE,
        tooltip="Toggle theme",
        icon_size=24,
        on_click=toggle_theme,
    )
    # Placeholder on_click — wired to open_history() after drawer exists.
    history_btn = ft.IconButton(
        icon=ft.Icons.MENU,
        tooltip="Chat history",
        icon_size=24,
    )
    new_chat_btn = ft.IconButton(
        icon=ft.Icons.ADD,
        tooltip="New chat",
        icon_size=24,
        on_click=new_chat,
    )
    # All chat actions live in this one menu — study essentials first,
    # power tools grouped under "Advanced". Keys/Settings live here too
    # (no bottom bar in INF ai minimal).
    appbar_menu = ft.PopupMenuButton(
        tooltip="Menu",
        items=[
            ft.PopupMenuItem(icon=ft.Icons.CHAT, content=ft.Text("Chat"), on_click=lambda _: _go_tab(0)),
            ft.PopupMenuItem(icon=ft.Icons.KEY, content=ft.Text("Study keys"), on_click=lambda _: _go_tab(1)),
            ft.PopupMenuItem(icon=ft.Icons.SETTINGS, content=ft.Text("Settings"), on_click=lambda _: _go_tab(2)),
            ft.PopupMenuItem(icon=ft.Icons.REFRESH, content=ft.Text("Retry last"), on_click=lambda _: page.run_task(on_retry, None)),
            ft.PopupMenuItem(icon=ft.Icons.COPY, content=ft.Text("Copy last reply"), on_click=on_copy_last),
            ft.PopupMenuItem(icon=ft.Icons.DOWNLOAD, content=ft.Text("Export .md"), on_click=lambda _: page.run_task(export_conv, "md")),
            ft.PopupMenuItem(icon=ft.Icons.DOWNLOAD, content=ft.Text("Export .json"), on_click=lambda _: page.run_task(export_conv, "json")),
            ft.PopupMenuItem(icon=ft.Icons.DELETE_OUTLINE, content=ft.Text("Clear chat"), on_click=lambda _: on_clear(None)),
            ft.PopupMenuItem(icon=ft.Icons.LOCK, content=ft.Text("Lock now"), on_click=lambda _: lock_now()),
            ft.PopupMenuItem(icon=ft.Icons.SEARCH, content=ft.Text("Advanced: Find in chat"), on_click=lambda _: open_find()),
            ft.PopupMenuItem(icon=ft.Icons.DESCRIPTION_OUTLINED, content=ft.Text("Advanced: Doc index"), on_click=lambda _: _open_doc_index()),
            ft.PopupMenuItem(icon=ft.Icons.COMPARE_ARROWS, content=ft.Text("Advanced: Compare models"), on_click=lambda _: _toggle_compare()),
            ft.PopupMenuItem(icon=ft.Icons.VISIBILITY_OFF, content=ft.Text("Advanced: Reset vision override"), on_click=_clear_vision_override),
            ft.PopupMenuItem(icon=ft.Icons.DASHBOARD_OUTLINED, content=ft.Text("Advanced: Artifacts"), on_click=lambda _: open_artifact_panel(None)),
        ],
    )

    # ---- artifacts panel (BottomSheet list + detail dialog) ----
    artifact_list_col = ft.Column(spacing=0, tight=True, scroll=ft.ScrollMode.AUTO)
    artifact_sheet = ft.BottomSheet(
        content=ft.Container(
            content=ft.Column(
                [
                    ft.Text("Artifacts", weight=ft.FontWeight.BOLD, size=16),
                    ft.Container(content=artifact_list_col, height=320),
                ],
                spacing=8,
                tight=True,
            ),
            padding=16,
            height=420,
        ),
        show_drag_handle=True,
    )
    page.overlay.append(artifact_sheet)

    def open_artifact_panel(_: ft.ControlEvent | None = None) -> None:
        try:
            conv = state.get("conv_id")
            records = artifacts.list(conv)
            if not records:
                # Registry is in-memory: rebuild from the open history so
                # the panel is never stuck on "No artifacts yet" when the
                # reply above clearly contains a table/chart/card.
                try:
                    texts = [m.content for m in history
                             if m.role == "assistant" and isinstance(m.content, str)]
                    if texts:
                        artifacts.rebuild_from_texts(conv, texts)
                        records = artifacts.list(conv)
                except Exception:
                    pass
            artifact_list_col.controls = build_artifact_panel(
                records, _open_artifact_detail).controls
            artifact_sheet.open = True
            page.update()
            if records:
                show_snack(f"{len(records)} artifact(s) — tap one to view.")
        except Exception as e:  # noqa: BLE001
            show_snack(f"Artifacts failed: {e}")

    def _open_artifact_detail(e: ft.ControlEvent) -> None:
        try:
            idx = int(e.control.data)
            records = artifacts.list(state.get("conv_id"))
            rec = records[idx]
        except Exception:
            return
        artifact_sheet.open = False
        body_view: ft.Control
        if rec.kind == "chart":
            payload = parse_chart_payload(rec.body)
            body_view = chart_control(payload) if payload else ft.Text(rec.body[:2000], size=12)
        elif rec.kind == "table":
            body_view = artifact_control(rec.kind, rec.body)
        else:
            body_view = ft.Text(artifact_to_text(rec.kind, rec.body)[:2000],
                                size=12, selectable=True)

        def _copy(_: ft.ControlEvent | None = None) -> None:
            page.run_task(copy_to_clipboard, artifact_to_text(rec.kind, rec.body))

        async def _download(_: ft.ControlEvent | None = None) -> None:
            try:
                fname, exts = download_name(rec.kind, idx + 1)
                if rec.kind == "table":
                    payload = artifact_to_csv(rec.body).encode("utf-8")
                else:
                    payload = artifact_to_text(rec.kind, rec.body).encode("utf-8")
                saved = await picker.save_file(
                    dialog_title="Save artifact", file_name=fname,
                    file_type=ft.FilePickerFileType.CUSTOM,
                    allowed_extensions=[exts], src_bytes=payload)
                show_snack(f"Saved {fname}." if saved else "Save cancelled.")
            except Exception as ex:  # noqa: BLE001
                show_snack(f"Save failed: {ex}")

        dlg = ft.AlertDialog(
            modal=False, title=ft.Text(f"{rec.kind.title()} #{idx + 1}", size=14),
            content=ft.Container(content=body_view, width=360, height=320),
            actions=[
                ft.TextButton(content=ft.Text("Copy"), on_click=_copy),
                ft.TextButton(content=ft.Text("Save"),
                              on_click=lambda _: page.run_task(_download, None)),
            ],
        )
        page.show_dialog(dlg)

    # ---- desktop keyboard shortcuts (Ctrl+K search, Esc close, Ctrl+Enter send) ----
    def _on_keyboard(e: ft.KeyboardEvent) -> None:
        try:
            key = str(e.key or "").lower()
            ctrl = bool(e.ctrl)
            if ctrl and key == "k":
                page.run_task(open_history, None)
            elif ctrl and key == "f":
                try:
                    open_find()
                except Exception:
                    pass
            elif key == "escape":
                try:
                    if find_ui.get("open"):
                        close_find()
                        return
                except Exception:
                    pass
                for s in (sheet, artifact_sheet, feedback_sheet):
                    try:
                        if s.open:
                            s.open = False
                    except Exception:
                        pass
                page.update()
            elif ctrl and key == "enter":
                on_stop_send(None)
        except Exception:
            pass

    try:
        page.on_keyboard_event = _on_keyboard
    except Exception:
        pass

    drawer = ft.NavigationDrawer(
        controls=[
            ft.Container(
                content=ft.Row(
                    [
                        ft.Text("Chats", weight=ft.FontWeight.BOLD, expand=True),
                        ft.IconButton(
                            icon=ft.Icons.ADD, tooltip="New chat", icon_size=22, on_click=new_chat
                        ),
                    ],
                    tight=True,
                ),
                padding=_pad(12, 8),
            ),
            ft.Container(content=drawer_search, padding=_pad(12, 2)),
            # INF ai minimal: history filters + provider picker + bulk mode
            # stay functional behind Advanced (menu), hidden here.
            ft.Container(content=hist_filter_row, padding=_pad(12, 2), visible=False),
            ft.Container(content=hist_provider_dd, padding=_pad(12, 2), visible=False),
            ft.Container(content=bulk_bar, padding=_pad(12, 2), visible=False),
            ft.Container(content=drawer_list, expand=True, padding=_pad(8, 4)),
            ft.Container(
                content=ft.Row(
                    [
                        ft.TextButton(
                            content=ft.Text("Export .md"),
                            on_click=lambda _: page.run_task(export_conv, "md"),
                        ),
                        ft.TextButton(
                            content=ft.Text("Export .json"),
                            on_click=lambda _: page.run_task(export_conv, "json"),
                        ),
                    ],
                    tight=True,
                ),
                padding=_pad(12, 8),
            ),
        ]
    )
    page.drawer = drawer

    # ---- drawer open/close (Flet 0.86: NavigationDrawer has no `open`
    # flag — must `await page.show_drawer()` / `await page.close_drawer()`.
    # Handlers are async; sync callers schedule via page.run_task.) ----
    async def open_history(_: ft.ControlEvent | None = None) -> None:
        try:
            await page.show_drawer()
        except Exception as e:  # noqa: BLE001
            show_snack(f"Could not open history: {e}")

    async def close_history(_: ft.ControlEvent | None = None) -> None:
        try:
            await page.close_drawer()
        except Exception:
            pass

    history_btn.on_click = lambda _: page.run_task(open_history, None)
    try:
        refresh_drawer()
    except Exception:
        pass

    # ---- scroll-to-bottom FAB ----
    def scroll_bottom(_: ft.ControlEvent | None = None) -> None:
        try:
            if not chat.controls:
                return
            chat.scroll_to(offset=100000, duration=300)
        except Exception:
            pass

    def on_chat_scroll(e: ft.ScrollEvent) -> None:
        # Flet 0.86 ScrollEvent carries no pixel offsets — keep FAB visible
        # whenever there's enough history to scroll. auto_scroll handles live.
        # NOTE: update the FAB only when visibility actually changes —
        # page.update() per scroll event janks the whole list.
        try:
            want = len(chat.controls) > 3
            if fab.visible != want:
                fab.visible = want
                fab.update()
        except Exception:
            pass

    chat.on_scroll = on_chat_scroll
    # Jump-to-latest lives in the status strip (bottom), never as a page
    # FAB — the FAB overlapped the send button and blocked Stop taps.
    fab = ft.IconButton(icon=ft.Icons.ARROW_DOWNWARD, tooltip="Jump to latest",
                        icon_size=20, visible=False, on_click=scroll_bottom)

    def _refresh_fab_count() -> None:
        # v0.5 R1: the jump button doubles as a live "N new" pill while
        # streaming — single-control update, no full page re-layout.
        # Perf: called per stream frame — skip the round-trip when nothing
        # actually changed (unconditional fab.update() janked streaming).
        try:
            n = len(chat.controls)
            want_visible = n > 2
            want_tip = f"Jump to latest (live • {n})" if state.get("streaming") else "Jump to latest"
            if fab.visible == want_visible and fab.tooltip == want_tip:
                return
            fab.visible = want_visible
            fab.tooltip = want_tip
            fab.update()
        except Exception:
            pass

    # ---- ChatGPT-like model pill (lives in the AppBar, next to the menu) ----
    # AppBar stays minimal. Model choice opens the Model Sheet; capability
    # details (ctx/vision/docs/free) live in the sheet rows, long-press
    # inline expansion and the detail sheet — never on the chat page itself.
    model_pill = ft.Container(
        content=ft.Row(
            [
                model_button_label,
                ft.Icon(ft.Icons.EXPAND_MORE, size=18),
            ],
            spacing=6,
            tight=True,
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=_pad(14, 10),
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=18,
        bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.PRIMARY),
        on_click=open_model_sheet,
        tooltip="Change model",
        expand=True,
    )
    # Manual provider/model fields stay mounted but invisible (state only).
    advanced_box = ft.Container(content=advanced_row, padding=_pad(12, 2), visible=False)

    # ---- input "+" menu (attach / camera / prompt library / image out) ----
    plus_menu = ft.PopupMenuButton(
        icon=ft.Icons.ADD_CIRCLE_OUTLINE,
        tooltip="Attach or insert",
        icon_size=24,
        items=[
            ft.PopupMenuItem(icon=ft.Icons.ATTACH_FILE, content=ft.Text("Attach images/docs"), on_click=lambda _: page.run_task(on_attach, _)),
            ft.PopupMenuItem(icon=ft.Icons.PHOTO_CAMERA_OUTLINED, content=ft.Text("Take photo"), on_click=lambda _: page.run_task(on_camera, None)),
            ft.PopupMenuItem(icon=ft.Icons.BOOKMARK_OUTLINED, content=ft.Text("Prompt library"), on_click=open_prompt_library),
            ft.PopupMenuItem(icon=ft.Icons.IMAGE_OUTLINED, content=ft.Text("Generate image"), on_click=lambda _: _open_image_dialog("")),
        ],
    )

    # ---- model detail sheet (capability specs, ChatGPT model-info style) ----
    def _open_model_detail(pid: str, model: str) -> None:
        try:
            # Prune stale closed sheets so the overlay can't grow unbounded
            # (swipe-to-dismiss bypassed the old remove path).
            try:
                overlay = getattr(page, "overlay", None)
                if overlay is not None:
                    for existing in list(overlay):
                        try:
                            if isinstance(existing, ft.BottomSheet) and not getattr(existing, "open", True):
                                overlay.remove(existing)
                        except Exception:
                            pass
                    # Cap overlay size as a backstop.
                    while len(overlay) > 10:
                        try:
                            overlay.pop(0)
                        except Exception:
                            break
            except Exception:
                pass
            detail_sheet = build_model_detail_sheet(
                pid, model,
                on_select=lambda p, m: _pick_model(p, m),
                on_compare=lambda p, m: _compare_from_detail(p, m),
            )
            page.overlay.append(detail_sheet)
            detail_sheet.open = True
            page.update()
        except Exception as e:  # noqa: BLE001
            show_snack(f"Model detail failed: {e}")

    def _compare_from_detail(pid: str, model: str) -> None:
        if state.get("streaming"):
            show_snack("Wait for the current reply to finish.")
            return
        pid_cur, model_cur = _current_target()
        compare_ui["active"] = True
        compare_ui["pick_slot"] = None
        compare_ui["pair"] = {"a": [pid, model], "b": [pid_cur, model_cur]}
        compare_bar.visible = True
        try:
            _refresh_compare_bar()
        except Exception:
            pass
        show_snack("Compare on — Send to run both sides.")

    def _ask_custom_model() -> None:
        """Dialog for the sheet's 'Add custom model' tile (applies to the
        current provider, like the old sheet text field did)."""
        field = ft.TextField(
            label="Model ID", autofocus=True, dense=True,
            hint_text="e.g. openrouter/glm-5.2:free",
        )
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Add custom model"),
            content=ft.Container(content=ft.Column([field], spacing=8, tight=True), width=340),
            actions=[
                ft.TextButton(content=ft.Text("Cancel"),
                              on_click=lambda _: (setattr(dlg, "open", False), page.update())),
                ft.FilledButton(content=ft.Text("Add"),
                                on_click=lambda _: _do_add_custom(dlg, field)),
            ],
        )
        page.show_dialog(dlg)

    def _do_add_custom(dlg: ft.AlertDialog, field: ft.TextField) -> None:
        custom = (field.value or "").strip()
        dlg.open = False
        if not custom:
            page.update()
            return
        model_dd.value = custom
        persist_model(None)
        show_snack(f"Custom model '{custom}' added for {(provider_dd.value or 'gemini').strip()}.")

    # ---- image output (v0.6 text-to-image) ----
    def _image_capable_linked() -> list[str]:
        out: list[str] = []
        for pid in PROVIDER_IDS:
            if not supports_image_gen(pid):
                continue
            try:
                if store.get_key(pid).strip():
                    out.append(pid)
            except Exception:
                continue
        return out

    def _open_image_dialog(prefill: str = "") -> None:
        choices = _image_capable_linked()
        if not choices:
            show_snack("No image-capable provider linked — add an OpenAI or Together key under Keys.")
            try:
                _go_tab(1)
            except Exception:
                pass
            return
        try:
            cur_pid = (provider_dd.value or "").strip()
        except Exception:
            cur_pid = ""
        default_pid = cur_pid if cur_pid in choices else choices[0]
        first_models = available_image_models(default_pid) or ["gpt-image-1"]
        pid_dd = ft.Dropdown(
            label="Provider",
            options=[ft.dropdown.Option(p) for p in choices],
            value=default_pid,
            dense=True,
        )
        model_dd2 = ft.Dropdown(
            label="Image model (editable)",
            editable=True,
            enable_filter=True,
            options=[ft.dropdown.Option(m) for m in first_models],
            value=first_models[0],
            dense=True,
        )
        size_dd = ft.Dropdown(
            label="Size",
            options=[ft.dropdown.Option(s) for s in IMAGE_SIZES],
            value=IMAGE_SIZES[0],
            dense=True,
        )
        prompt_f = ft.TextField(
            label="Describe the image", value=prefill or "",
            multiline=True, min_lines=2, max_lines=4, dense=True,
            autofocus=True,
        )
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Generate image", size=14),
            content=ft.Container(
                content=ft.Column(
                    [prompt_f, pid_dd, model_dd2, size_dd],
                    spacing=8, tight=True,
                ),
                width=340,
            ),
            actions=[
                ft.TextButton(
                    content=ft.Text("Cancel"),
                    on_click=lambda _: (setattr(dlg, "open", False), page.update()),
                ),
                ft.FilledButton(
                    content=ft.Text("Generate"),
                    on_click=lambda _: _submit_image(dlg, prompt_f, pid_dd, model_dd2, size_dd),
                ),
            ],
        )

        def _on_pid(_: ft.ControlEvent | None = None) -> None:
            models = available_image_models((pid_dd.value or "").strip()) or ["gpt-image-1"]
            model_dd2.options = [ft.dropdown.Option(m) for m in models]
            model_dd2.value = models[0]
            try:
                page.update()
            except Exception:
                pass

        pid_dd.on_change = _on_pid
        page.show_dialog(dlg)

    def _submit_image(
        dlg: ft.AlertDialog,
        prompt_f: ft.TextField,
        pid_dd: ft.Dropdown,
        model_dd2: ft.Dropdown,
        size_dd: ft.Dropdown,
    ) -> None:
        prompt = (prompt_f.value or "").strip()
        if not prompt:
            show_snack("Describe the image first.")
            return
        pid = (pid_dd.value or "").strip()
        model = (model_dd2.value or "").strip()
        size = (size_dd.value or IMAGE_SIZES[0]).strip()
        if not pid or not model:
            show_snack("Pick a provider + image model.")
            return
        dlg.open = False
        try:
            page.update()
        except Exception:
            pass
        page.run_task(_run_image_gen, prompt, pid, model, size)

    def _append_image_card(prompt: str, png: bytes, filename: str) -> None:
        """Render a generated image in the chat with Save/Copy actions."""
        b64 = png_to_b64(png)

        def _preview(_: ft.ControlEvent | None = None) -> None:
            try:
                dlg = build_lightbox(
                    "Generated image", f"data:image/png;base64,{b64}", prompt
                )
                page.show_dialog(dlg)
            except Exception:
                pass

        async def _save_file(_: ft.ControlEvent | None = None) -> None:
            try:
                saved = await picker.save_file(
                    dialog_title="Save image",
                    file_name=filename,
                    file_type=ft.FilePickerFileType.CUSTOM,
                    allowed_extensions=["png"],
                    src_bytes=bytes(png),
                )
                show_snack(f"Saved {filename}." if saved else "Save cancelled.")
            except Exception as e:  # noqa: BLE001
                show_snack(f"Save failed: {e}")

        def _on_save(e: ft.ControlEvent | None = None) -> None:
            page.run_task(_save_file, e)

        def _on_copy(_: ft.ControlEvent | None = None) -> None:
            try:
                page.run_task(copy_to_clipboard, prompt)
            except Exception as e:  # noqa: BLE001
                show_snack(f"Copy failed: {e}")

        chat.controls.append(
            image_card(b64, prompt, on_save=_on_save,
                       on_copy_prompt=_on_copy, on_preview=_preview)
        )
        refresh_empty()
        _scroll_to_end()

    def _append_saved_image(body: str, key_idx: int | None = None) -> bool:
        """Rebuild a generated-image card from a persisted history note.

        Returns True when the note referenced a saved file that still
        exists (note bubble + card appended); False for normal text
        replies (caller renders the plain bubble).
        """
        try:
            parsed = parse_image_note(body)
        except Exception:
            return False
        if parsed is None:
            return False
        prompt, filename = parsed
        b64 = read_generated_b64(filename)
        if not b64:
            return False

        def _preview(_: ft.ControlEvent | None = None, _b=b64, _p=prompt) -> None:
            try:
                page.show_dialog(build_lightbox(
                    "Generated image", f"data:image/png;base64,{_b}", _p))
            except Exception:
                pass

        _append_assistant(body, key_idx=key_idx)
        chat.controls.append(image_card(b64, prompt, on_preview=_preview))
        _scroll_to_end()
        return True

    async def _run_image_gen(prompt: str, pid: str, model: str, size: str) -> None:
        if state.get("streaming"):
            show_snack("Wait for the current reply to finish.")
            return
        try:
            key = store.get_key(pid).strip()
        except Exception:
            key = ""
        if not key:
            chat.controls.append(error_bubble(
                f"Provider '{pid}' needs an API key — add it under Keys."))
            refresh_empty()
            _safe_update()
            _scroll_to_end()
            return
        state["streaming"] = True  # guard so sends/images never overlap
        state["stop"] = False
        update_send_stop()
        _append_user("🖼️ " + prompt)
        progress = shimmer_placeholder("Generating image…")
        chat.controls.append(progress)
        refresh_empty()
        _safe_update()
        _scroll_to_end()
        if chats is not None:
            ensure_conv(prompt, pid, model)
        try:
            base = store.get_base_url(pid, PROVIDERS[pid].get("base_url", ""))
            provider = get_provider(pid, key, base, timeout=IMAGE_GEN_TIMEOUT)
            if not hasattr(provider, "generate_image"):
                raise ValueError(f"Provider '{pid}' can't render images.")
            png, _revised = await provider.generate_image(prompt, model, size)
        except (ProviderError, ValueError) as e:
            try:
                if progress in chat.controls:
                    chat.controls.remove(progress)
            except Exception:
                pass
            chat.controls.append(error_bubble(f"Image failed: {e}"))
            refresh_empty()
            state["streaming"] = False
            update_send_stop()
            _safe_update()
            _scroll_to_end()
            return
        except Exception as e:  # noqa: BLE001
            try:
                if progress in chat.controls:
                    chat.controls.remove(progress)
            except Exception:
                pass
            chat.controls.append(error_bubble(f"Image failed: {e}"))
            refresh_empty()
            state["streaming"] = False
            update_send_stop()
            _safe_update()
            _scroll_to_end()
            return
        try:
            if progress in chat.controls:
                chat.controls.remove(progress)
        except Exception:
            pass
        filename = save_generated_png(bytes(png), state.get("conv_id"))
        note = image_note(prompt, filename)
        _append_image_card(prompt, bytes(png), filename)
        history.append(Message("user", "🖼️ " + prompt))
        history.append(Message("assistant", note))
        state["last_assistant"] = note
        if chats is not None:
            try:
                ensure_conv(prompt, pid, model)
                assert state["conv_id"] is not None
                chats.add_message(state["conv_id"], "user", "🖼️ " + prompt)
                chats.add_message(state["conv_id"], "assistant", note)
                refresh_drawer()
            except Exception as e:  # noqa: BLE001
                show_snack(f"Image done, but history save failed: {e}")
        status.value = f"{pid} / {model} • image generated ({len(bytes(png)) // 1024}KB)"
        try:
            _refresh_meter()
        except Exception:
            pass
        state["streaming"] = False
        update_send_stop()
        refresh_empty()
        _safe_update()
        _scroll_to_end()

    # ---- context meter (INF ai minimal: slim bar only, details in tooltip) ----
    meter_bar = ft.ProgressBar(value=0.0, expand=True)
    meter_txt = ft.Text("", size=10, color=ft.Colors.ON_SURFACE_VARIANT, visible=False)
    meter_wrap = ft.Container(
        content=ft.Row([meter_bar], spacing=8, tight=True,
                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
        padding=_pad(12, 1),
        tooltip="Estimated context use for this chat vs the model's limit.",
    )

    def _refresh_meter() -> None:
        try:
            model = (model_dd.value or "").strip()
            limit = context_limit_for(model)
            used = context_used(history)
            try:
                pin_extra = _pinned_block()
                if pin_extra:
                    used += estimate_tokens(pin_extra)
            except Exception:
                pin_extra = ""
            frac = min(1.0, used / limit) if limit > 0 else 0.0
            band = meter_band(used, limit)
            meter_bar.value = frac
            meter_bar.color = {
                "ok": ft.Colors.PRIMARY,
                "warn": ft.Colors.AMBER,
                "critical": ft.Colors.RED,
            }.get(band, ft.Colors.PRIMARY)
            meter_txt.value = meter_label(used, limit)
            auto = ""
            try:
                auto = " • auto-compact on" if store.get("chat", "auto_compact", "false").lower() == "true" else ""
            except Exception:
                pass
            try:
                n_pin = len(state.get("pinned_msgs", set()))
                pin_note = f" • {n_pin} pinned" if n_pin else ""
            except Exception:
                pin_note = ""
            meter_wrap.tooltip = (
                f"~{used:,}/{limit:,} tokens ({int(round(100 * frac))}%){auto}{pin_note}."
                " Estimates only — never billing."
            )
        except Exception:
            pass

    # ---- find-in-chat (v0.5 R6, Flet-only) ----
    find_ui = {"open": False, "query": "", "matches": [], "pos": 0, "hl_key": None}
    find_field = ft.TextField(label="Find in chat", dense=True, expand=True)
    find_count = ft.Text("0/0", size=12, color=ft.Colors.ON_SURFACE_VARIANT)

    def find_texts() -> list[str]:
        out: list[str] = []
        for m in history:
            try:
                if m.role == "user":
                    t, _ = user_text_of(m.content)
                    out.append(t)
                elif m.role == "assistant":
                    out.append(assistant_text_of(m.content))
                else:
                    out.append(m.content if isinstance(m.content, str) else str(m.content))
            except Exception:
                out.append("")
        return out

    def _find_clear_hl() -> None:
        k = find_ui.get("hl_key")
        if not k:
            return
        find_ui["hl_key"] = None
        try:
            for c in chat.controls:
                if getattr(c, "key", None) == k:
                    set_row_highlight(c, False)
                    break
        except Exception:
            pass

    def _find_recompute() -> None:
        q = (find_field.value or "")
        find_ui["query"] = q
        find_ui["matches"] = build_match_index(find_texts(), q)
        find_ui["pos"] = 0
        _find_clear_hl()
        try:
            find_count.value = format_counter(0, len(find_ui["matches"]))
        except Exception:
            pass

    def _find_goto(pos: int) -> None:
        ms = find_ui.get("matches", [])
        if not ms:
            try:
                find_count.value = "0/0"
                page.update()
            except Exception:
                pass
            return
        pos = pos % len(ms)
        find_ui["pos"] = pos
        gi = ms[pos]
        _find_clear_hl()
        # Expand the render window when the match is hidden above it.
        try:
            need = window_for_index(gi, hist_ui.get("shown"), len(history))
            if need is not None:
                hist_ui["shown"] = need
                render_history_to_ui()
        except Exception:
            pass
        key = row_key(gi)
        try:
            for c in chat.controls:
                if getattr(c, "key", None) == key:
                    if set_row_highlight(c, True):
                        find_ui["hl_key"] = key
                    break
        except Exception:
            pass
        try:
            chat.scroll_to(key=key, duration=250)
        except Exception:
            try:
                if gi >= len(history) - 1:
                    _scroll_to_end()
            except Exception:
                pass
        try:
            find_count.value = format_counter(pos, len(ms))
            page.update()
        except Exception:
            pass

    def _find_step(delta: int):
        def _h(_: ft.ControlEvent | None = None) -> None:
            ms = find_ui.get("matches", [])
            if not ms:
                _find_recompute()
                ms = find_ui.get("matches", [])
                if not ms:
                    try:
                        find_count.value = "0/0"
                        page.update()
                    except Exception:
                        pass
                    return
            _find_goto(step_index(find_ui.get("pos", 0), delta, len(ms)))
        return _h

    def _find_on_change(_: ft.ControlEvent | None = None) -> None:
        _find_recompute()
        try:
            page.update()
        except Exception:
            pass

    def open_find(_: ft.ControlEvent | None = None) -> None:
        find_ui["open"] = True
        find_bar.visible = True
        try:
            find_field.value = find_ui.get("query", "")
        except Exception:
            pass
        _find_recompute()
        try:
            page.update()
        except Exception:
            pass
        try:
            import inspect as _inspect

            _focus = getattr(find_field, "focus", None)
            if callable(_focus):
                if _inspect.iscoroutinefunction(_focus):
                    page.run_task(_focus)
                else:
                    try:
                        _res = _focus()
                    except Exception:
                        _res = None
                    if _inspect.isawaitable(_res):
                        async def _await_focus() -> None:
                            await _res

                        try:
                            page.run_task(_await_focus)
                        except Exception:
                            pass
        except Exception:
            pass

    def close_find(_: ft.ControlEvent | None = None) -> None:
        _find_clear_hl()
        find_ui["open"] = False
        try:
            find_bar.visible = False
        except Exception:
            pass
        try:
            page.update()
        except Exception:
            pass

    find_field.on_change = _find_on_change
    find_field.on_submit = _find_step(1)
    find_bar = ft.Container(
        content=ft.Row(
            [
                find_field,
                find_count,
                ft.IconButton(icon=ft.Icons.ARROW_UPWARD, tooltip="Previous match",
                              icon_size=20, on_click=_find_step(-1)),
                ft.IconButton(icon=ft.Icons.ARROW_DOWNWARD, tooltip="Next match",
                              icon_size=20, on_click=_find_step(1)),
                ft.IconButton(icon=ft.Icons.CLOSE, tooltip="Close find (Esc)",
                              icon_size=20, on_click=close_find),
            ],
            spacing=4,
            tight=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=_pad(12, 4),
        visible=False,
    )

    # ---- multi-model compare (v0.5 R2, Flet-only, max 2 slots) ----
    # Same prompt → both slots concurrently (asyncio.gather over the normal
    # provider.chat_stream path). No RAG / no auto-compaction in compare;
    # staged docs inject as plain text. Nothing is recorded until Keep.
    compare_bar = ft.Container(
        content=ft.Row(spacing=6, tight=True),
        padding=_pad(12, 4),
        visible=False,
    )

    def _current_target() -> tuple[str, str]:
        try:
            pid = (provider_dd.value or "gemini").strip() or "gemini"
            model = (model_dd.value or "").strip() or PROVIDERS.get(pid, {}).get("default_model", "")
            return pid, model
        except Exception:
            return "gemini", PROVIDERS.get("gemini", {}).get("default_model", "")

    def _refresh_compare_bar() -> None:
        pair = compare_ui.get("pair") or {}
        try:
            a = pair.get("a", ["—", "—"])
            b = pair.get("b", ["—", "—"])
            compare_bar.content.controls = [
                ft.Text("Compare", size=12, weight=ft.FontWeight.BOLD),
                ft.Chip(label=ft.Text(f"A: {a[0]} / {a[1]}", size=11),
                        data="a", on_click=_pick_compare_slot),
                ft.Chip(label=ft.Text(f"B: {b[0]} / {b[1]}", size=11),
                        data="b", on_click=_pick_compare_slot),
                ft.IconButton(icon=ft.Icons.CLOSE, tooltip="Exit compare",
                              icon_size=18, on_click=_toggle_compare),
            ]
        except Exception:
            pass

    def _pick_compare_slot(e: ft.ControlEvent) -> None:
        try:
            compare_ui["pick_slot"] = str(e.control.data or "a")
        except Exception:
            compare_ui["pick_slot"] = "a"
        open_model_sheet(None)

    def _toggle_compare(_: ft.ControlEvent | None = None) -> None:
        if state.get("streaming") or compare_ui.get("busy"):
            show_snack("Wait for the current reply to finish.")
            return
        active = not compare_ui.get("active")
        compare_ui["active"] = active
        compare_ui["pick_slot"] = None
        if active:
            try:
                stored = pair_from_json(store.get("ui", "compare", ""))
            except Exception:
                stored = None
            pid, model = _current_target()
            compare_ui["pair"] = stored or default_pair(pid, model)
            compare_bar.visible = True
            _refresh_compare_bar()
            show_snack("Compare on — tap a side to pick its model, then Send.")
        else:
            compare_bar.visible = False
        try:
            page.update()
        except Exception:
            pass

    async def _compare_send(text: str) -> None:
        if compare_ui.get("busy") or state.get("streaming"):
            show_snack("Already running — tap Stop to interrupt.")
            return
        staged = list(attachments)
        attachments.clear()
        try:
            refresh_chips()
        except Exception:
            pass
        def _has_key(pid: object) -> bool:
            try:
                if not isinstance(pid, str) or not pid:
                    return False
                raw = store.get_key(pid)
                return bool(raw.strip()) if isinstance(raw, str) else False
            except Exception:
                return False

        ok, msg = validate_pair(compare_ui.get("pair") or {}, _has_key)
        if not ok:
            attachments.extend(staged)
            try:
                refresh_chips()
            except Exception:
                pass
            if not (input_box.value or "").strip():
                input_box.value = text
            show_snack(msg)
            status.value = msg
            _safe_update()
            return
        try:
            in_est = estimate_tokens(text) + sum(
                estimate_tokens(getattr(a, "text", "") if isinstance(getattr(a, "text", ""), str) else "")
                for a in staged
            )
        except Exception:
            in_est = estimate_tokens(text)
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Compare models?"),
            content=ft.Column([
                ft.Text(guard_text(text, len(staged), in_est), size=12, selectable=True),
                ft.Checkbox(label="Send attached files to BOTH sides (default: side A only)",
                            value=False),
                ft.Text("Each side sends to a different vendor — files go to both only if checked.",
                        size=11),
            ], spacing=8, tight=True),
            actions=[
                ft.TextButton(content=ft.Text("Cancel"), on_click=lambda _: _guard_close(False, text, staged)),
                ft.FilledButton(content=ft.Text("Compare"), on_click=lambda _: _guard_close(True, text, staged)),
            ],
        )

        def _guard_close(go: bool, prompt: str, files: list) -> None:
            both = False
            try:
                both = bool(dlg.content.controls[1].value)
            except Exception:
                both = False
            dlg.open = False
            if not go:
                attachments.extend(files)
                try:
                    refresh_chips()
                except Exception:
                    pass
                if not (input_box.value or "").strip():
                    input_box.value = prompt
                try:
                    page.update()
                except Exception:
                    pass
                return
            page.run_task(_run_compare, prompt, files, both)

        page.show_dialog(dlg)

    async def _run_compare_side(side: str) -> tuple[str, str]:
        """Stream one slot. Returns (status, text_or_error)."""
        box = compare_ui.get("sides", {}).get(side, {}) if isinstance(compare_ui.get("sides"), dict) else {}
        provider, msgs, model = box.get("provider"), box.get("msgs"), box.get("model", "")
        bubble, md = box.get("bubble"), box.get("md")
        if provider is None or msgs is None or bubble is None or md is None:
            return ("error", f"Side {side.upper()} is not ready — check its key/model.")
        acc = StreamAccumulator(last_flush=time.monotonic())
        try:
            gen_max = _gen_max_for(store, str(box.get("pid", "")), model)
            async for chunk in provider.chat_stream(msgs, model, max_tokens=gen_max):
                if state.get("stop"):
                    break
                frame = acc.push(chunk, time.monotonic())
                if frame is None:
                    continue
                frame = _tex(frame)
                try:
                    if bubble.set_stream_text(frame):
                        continue
                except Exception:
                    pass
                md.value = frame
                try:
                    page.update()
                except Exception:
                    pass
            return ("ok", "".join(acc.acc).strip())
        except asyncio.CancelledError:
            return ("stopped", "")
        except ProviderError as e:
            return ("error", f"Failed: {e.friendly()}")
        except Exception as e:  # noqa: BLE001
            return ("error", f"Failed: {e}")

    async def _run_compare(prompt: str, staged: list, send_both: bool = False) -> None:
        pair = compare_ui.get("pair") or {}
        compare_ui["busy"] = True
        state["streaming"] = True
        state["stop"] = False
        try:
            state["stream_task"] = asyncio.current_task()
        except Exception:
            pass
        update_send_stop()
        hist_ui["shown"] = None
        _append_user(prompt + (f"  +{len(staged)} file(s)" if staged else ""))
        try:
            compare_ui["user_row"] = chat.controls[-1]
        except Exception:
            compare_ui["user_row"] = None
        compare_ui["prompt"] = prompt
        compare_ui["sides"] = {}
        compare_ui["texts"] = {}
        compare_ui["msgs"] = {}
        for side in COMPARE_SLOTS:
            try:
                slot = pair.get(side) if isinstance(pair, dict) else None
                pid, model = (slot[0], slot[1]) if isinstance(slot, (list, tuple)) and len(slot) >= 2 else (None, None)
            except Exception:
                pid, model = None, None
            if not isinstance(pid, str) or not isinstance(model, str) or not pid or not model:
                continue
            label = ft.Row(
                [ft.Text(f"{side.upper()} • {pid} / {model}", size=11,
                         weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE_VARIANT)],
                tight=True,
            )
            chat.controls.append(label)
            try:
                bubble = StreamingBubble(lambda: _markdown(STREAM_CURSOR), timestamp=now_hhmm())
                md = bubble.md
            except Exception:
                md = _markdown(STREAM_CURSOR)
                bubble = assistant_bubble(md, timestamp=now_hhmm())
            chat.controls.append(bubble)
            box: dict = {"label": label, "bubble": bubble, "md": md,
                         "pid": pid, "model": model, "ok": False}
            try:
                key = store.get_key(pid).strip()
                base_raw = store.get_base_url(pid, "") or PROVIDERS[pid]["base_url"]
                provider = get_provider(pid, key, base_raw or None)
                try:
                    override = store.get("vision", vision_override_key(pid, model), "false") == "true"
                except Exception:
                    override = False
                # Per-side file consent: default files to side A only; side B
                # gets them only when the guard checkbox opted into both.
                side_files = staged if (send_both or side == "a") else []
                box["msgs"] = build_chat_messages(history, prompt, side_files, pid, model,
                                                  vision_override=override)
                box["provider"] = provider
                box["ok"] = True
                compare_ui["msgs"][side] = box["msgs"][-1]  # built user turn for Keep
            except (ProviderError, ValueError) as e:
                md.value = f"_(side {side.upper()} setup failed: {e})_"
                box["setup_error"] = str(e)
            compare_ui["sides"][side] = box
        refresh_empty()
        _safe_update()
        _scroll_to_end()
        runnable = [s for s in COMPARE_SLOTS if compare_ui["sides"][s].get("ok")]
        if runnable:
            try:
                results = await asyncio.gather(*[_run_compare_side(s) for s in runnable])
            except asyncio.CancelledError:
                # Stop during compare: sides finalize themselves as
                # "stopped"; keep the verdict row so nothing strands.
                state["stop"] = True
                results = [("stopped", "") for _ in runnable]
            except Exception as e:  # noqa: BLE001
                results = [("error", f"Failed: {e}") for _ in runnable]
            for side, (status_, out) in zip(runnable, results):
                box = compare_ui["sides"][side]
                if status_ == "ok":
                    box["md"].value = out or "_(empty reply)_"
                    compare_ui["texts"][side] = out
                elif status_ == "stopped":
                    box["md"].value = "_(stopped)_"
                    compare_ui["texts"][side] = ""
                else:
                    box["md"].value = box["md"].value if "setup failed" in str(box["md"].value) else "_(reply failed)_"
                    chat.controls.append(error_bubble(out))
                    compare_ui["texts"][side] = ""
        verdict = ft.Row(
            [
                ft.FilledButton(content=ft.Text("Keep A"), on_click=lambda _: _compare_keep("a")),
                ft.FilledButton(content=ft.Text("Keep B"), on_click=lambda _: _compare_keep("b")),
                ft.TextButton(content=ft.Text("Retry A"), on_click=lambda _: page.run_task(_compare_rerun, "a")),
                ft.TextButton(content=ft.Text("Retry B"), on_click=lambda _: page.run_task(_compare_rerun, "b")),
                ft.TextButton(content=ft.Text("Dismiss"), on_click=lambda _: _compare_dismiss()),
            ],
            wrap=True,
            spacing=6,
            tight=True,
        )
        compare_ui["verdict"] = verdict
        chat.controls.append(verdict)
        compare_ui["busy"] = False
        state["streaming"] = False
        update_send_stop()
        status.value = "Compare done — Keep a side to save it, or Dismiss."
        refresh_empty()
        try:
            page.update()
        except Exception:
            pass
        _scroll_to_end()

    async def _compare_rerun(side: str) -> None:
        if compare_ui.get("busy") or state.get("streaming"):
            show_snack("Wait for the current run to finish.")
            return
        box = compare_ui.get("sides", {}).get(side)
        if not box or not box.get("ok"):
            show_snack(f"Side {side.upper()} is not runnable — check its key/model.")
            return
        prompt = compare_ui.get("prompt", "")
        if not prompt:
            return
        compare_ui["busy"] = True
        state["streaming"] = True
        state["stop"] = False
        try:
            state["stream_task"] = asyncio.current_task()
        except Exception:
            pass
        update_send_stop()
        try:
            box["md"].value = STREAM_CURSOR
            page.update()
        except Exception:
            pass
        status_, out = await _run_compare_side(side)
        if status_ == "ok":
            box["md"].value = out or "_(empty reply)_"
            compare_ui["texts"][side] = out
        elif status_ == "stopped":
            box["md"].value = "_(stopped)_"
            compare_ui["texts"][side] = ""
        else:
            box["md"].value = "_(reply failed)_"
            chat.controls.append(error_bubble(out))
            compare_ui["texts"][side] = ""
        compare_ui["busy"] = False
        state["streaming"] = False
        update_send_stop()
        try:
            page.update()
        except Exception:
            pass
        _scroll_to_end()

    def _compare_keep(side: str) -> None:
        other = "b" if side == "a" else "a"
        if side not in COMPARE_SLOTS or other not in COMPARE_SLOTS:
            return
        texts = compare_ui.get("texts", {}) if isinstance(compare_ui.get("texts"), dict) else {}
        text = (texts.get(side) or "").strip() if isinstance(texts.get(side), str) else ""
        if not text:
            show_snack(f"Side {side.upper()} has no reply to keep.")
            return
        pair = compare_ui.get("pair") or {}
        try:
            slot = pair.get(side) if isinstance(pair, dict) else None
            pid, model = (slot[0], slot[1]) if isinstance(slot, (list, tuple)) and len(slot) >= 2 else ("", "")
        except Exception:
            pid, model = "", ""
        if not isinstance(pid, str) or not isinstance(model, str):
            show_snack("Compare data is corrupt — nothing kept.")
            return
        msgs = compare_ui.get("msgs", {}) if isinstance(compare_ui.get("msgs"), dict) else {}
        user_msg = msgs.get(side)
        sides = compare_ui.get("sides", {}) if isinstance(compare_ui.get("sides"), dict) else {}
        try:
            if user_msg is not None:
                history.append(user_msg)
            history.append(Message("assistant", text))
            bubble = sides.get(side, {}).get("bubble") if isinstance(sides.get(side), dict) else None
            if bubble is not None:
                _wire_assistant_actions(bubble, text)
        except Exception:
            pass
        state["last_assistant"] = text
        if chats is not None and text:
            try:
                ensure_conv(compare_ui.get("prompt", text[:40]), pid, model)
                if state.get("conv_id") is None:
                    raise ValueError("No conversation open.")
                if user_msg is not None:
                    chats.add_message(state["conv_id"], "user", user_msg.content)
                chats.add_message(state["conv_id"], "assistant", text)
                try:
                    box_msgs = sides[side].get("msgs", [])
                    chats.add_token_usage(state["conv_id"], context_used(box_msgs),
                                          estimate_tokens(text))
                except Exception:
                    pass
                refresh_drawer()
            except Exception as e:  # noqa: BLE001
                show_snack(f"Kept, but history save failed: {e}")
        # Collapse the loser: remove its rows, leave a one-line note.
        try:
            loser_controls = []
            if isinstance(sides.get(other), dict):
                loser_controls += [sides[other].get("label"), sides[other].get("bubble")]
            loser_controls.append(compare_ui.get("verdict"))
            for ctrl in loser_controls:
                if ctrl is not None and ctrl in chat.controls:
                    chat.controls.remove(ctrl)
        except Exception:
            pass
        try:
            other_slot = pair.get(other) if isinstance(pair, dict) else None
            o_pid = other_slot[0] if isinstance(other_slot, (list, tuple)) and len(other_slot) >= 1 else "?"
            o_model = other_slot[1] if isinstance(other_slot, (list, tuple)) and len(other_slot) >= 2 else "?"
            chat.controls.append(
                ft.Row([ft.Text(loser_note(side, o_pid, o_model),
                                size=11, color=ft.Colors.ON_SURFACE_VARIANT,
                                selectable=True, expand=True)],
                       spacing=6, tight=True)
            )
        except Exception:
            pass
        compare_ui["busy"] = False
        try:
            _refresh_meter()
        except Exception:
            pass
        status.value = f"Kept side {side.upper()} ({pid} / {model})."
        refresh_empty()
        try:
            page.update()
        except Exception:
            pass
        _scroll_to_end()

    def _compare_dismiss(_: ft.ControlEvent | None = None) -> None:
        sides = compare_ui.get("sides", {})
        try:
            for ctrl in (compare_ui.get("user_row"),
                         sides.get("a", {}).get("label"), sides.get("a", {}).get("bubble"),
                         sides.get("b", {}).get("label"), sides.get("b", {}).get("bubble"),
                         compare_ui.get("verdict")):
                if ctrl is not None and ctrl in chat.controls:
                    chat.controls.remove(ctrl)
        except Exception:
            pass
        compare_ui["sides"] = {}
        compare_ui["texts"] = {}
        show_snack("Compare discarded — nothing saved.")
        refresh_empty()
        try:
            page.update()
        except Exception:
            pass

    chat_wrap = ft.Container(content=chat, expand=True, padding=_pad(12, 6))
    empty_wrap = ft.Container(content=empty_state, expand=True, padding=_pad(12, 6))
    _wrappers["chat_wrap"] = chat_wrap
    _wrappers["empty_wrap"] = empty_wrap

    chat_view = ft.Column(
        [
            meter_wrap,
            advanced_box,
            find_bar,
            compare_bar,
            chat_wrap,
            empty_wrap,
            ft.Container(
                content=ft.Column([chips_row], spacing=2, tight=True),
                padding=_pad(12, 2),
            ),
            ft.Container(
                # ChatGPT-like composer: just + | input | send. Attach,
                # camera and prompt library live in the "+" menu; all chat
                # actions live in the AppBar overflow menu.
                content=ft.Row(
                    [plus_menu, input_box, send_stop_btn],
                    tight=True,
                    spacing=4,
                    vertical_alignment=ft.CrossAxisAlignment.END,
                ),
                padding=_pad(8, 6),
            ),
            ft.Container(
                # Status strip doubles as the jump-to-latest anchor (right).
                content=ft.Row(
                    [
                        ft.Container(content=status, padding=_pad(12, 4), expand=True),
                        fab,
                    ],
                    spacing=0,
                    tight=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ),
        ],
        expand=True,
        spacing=0,
    )

    def sync_from_providers(pid: str, model: str) -> None:
        # Direct set — avoids the old double-refresh race where refresh_models
        # overwrote the picked model with the stale saved value + live reload.
        provider_dd.value = pid
        if model and model not in available_models(pid):
            model_dd.options = [ft.dropdown.Option(model), *model_dd.options]
        model_dd.value = model
        persist_model(None)
        try:
            _go_tab(0)
        except Exception:
            pass
        show_snack(f"{pid} / {model} active — back to Chat.")

    providers_view = ft.Container(
        content=build_providers_view(page, store, on_use_provider=sync_from_providers),
        padding=_pad(12, 8),
        expand=True,
    )
    settings_view = ft.Container(
        content=build_settings_view(page, store, chats, on_theme_changed=apply_theme,
                                    on_replay_tour=lambda: (_go_tab(0), open_tour())),
        padding=_pad(12, 8),
        expand=True,
    )
    body = ft.Container(content=chat_view, expand=True)
    appbar = ft.AppBar(
        # ChatGPT-minimal: menu | model pill | actions. The pill sits right
        # next to the menu so the whole chat area below stays for messages.
        # App identity lives in the OS launcher icon + window title only.
        title=model_pill,
        leading=history_btn,
        actions=[
            new_chat_btn,
            theme_btn,
            appbar_menu,
        ],
    )

    def _sync_settings_theme() -> None:
        # Keep Settings dropdown in sync when AppBar toggle is used.
        try:
            mode = "light" if page.theme_mode == ft.ThemeMode.LIGHT else "dark"

            def _walk(c: object) -> None:
                if isinstance(c, ft.Dropdown) and getattr(c, "label", "") == "Theme":
                    c.value = mode
                    return
                for attr in ("content", "controls", "actions"):
                    v = getattr(c, attr, None)
                    if isinstance(v, list):
                        for ch in v:
                            _walk(ch)
                    elif v is not None and hasattr(v, "__class__"):
                        try:
                            _walk(v)
                        except Exception:
                            pass

            _walk(settings_view)
        except Exception:
            pass

    _orig_apply_theme = apply_theme

    def apply_theme(mode: str) -> None:  # noqa: F811 — wrap to sync settings UI
        _orig_apply_theme(mode)
        _sync_settings_theme()

    _orig_toggle_theme = toggle_theme

    def toggle_theme(e: ft.ControlEvent) -> None:  # noqa: F811
        _orig_toggle_theme(e)
        _sync_settings_theme()

    theme_btn.on_click = toggle_theme

    def _go_tab(idx: int) -> None:
        """Single place for tab switches (menu-driven, no bottom bar)."""
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            idx = 0
        idx = max(0, min(2, idx))
        body.content = [chat_view, providers_view, settings_view][idx]
        on_chat_tab = idx == 0
        try:
            history_btn.visible = on_chat_tab
            new_chat_btn.visible = on_chat_tab
            # Menu stays visible on every tab — it's the only navigator.
            appbar_menu.visible = True
            appbar.leading = history_btn if on_chat_tab else None
            # Model pill belongs to the chat tab only — hide it on the
            # Keys/Settings tabs so it can't open the sheet there.
            # Show a plain INF ai title instead.
            appbar.title = model_pill if on_chat_tab else ft.Text(
                "INF ai" if idx == 0 else ("Study keys" if idx == 1 else "Settings"),
                size=16, weight=ft.FontWeight.BOLD,
            )
            if hasattr(appbar, "update"):
                try:
                    appbar.update()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            fab.visible = on_chat_tab and len(chat.controls) > 2
        except Exception:
            pass
        if not on_chat_tab:
            try:
                page.run_task(close_history, None)
            except Exception:
                pass
        else:
            try:
                _refresh_fab_count()
            except Exception:
                pass
        if idx == 2:
            _sync_settings_theme()
        try:
            store.set("ui", "tab", str(idx))
        except Exception:
            pass
        try:
            page.update()
        except Exception:
            pass

    # INF ai minimal: no bottom NavigationBar — Chat / Study keys /
    # Settings all live under the AppBar three-dot menu (_go_tab).

    # Init AFTER page.add — calling page.update before controls are mounted
    # was a no-op / error source on startup.
    page.add(appbar, body)
    try:
        refresh_models(None)
    except Exception:
        pass
    try:
        refresh_drawer()
    except Exception:
        pass
    refresh_empty()
    try:
        _refresh_meter()
    except Exception:
        pass
    # Restore last tab (default Chat). _go_tab also syncs FAB.
    try:
        saved_tab = int(store.get("ui", "tab", "0") or 0)
    except Exception:
        saved_tab = 0
    try:
        if saved_tab in (1, 2):
            _go_tab(saved_tab)
        else:
            _go_tab(0)
    except Exception:
        pass
    try:
        page.update()
    except Exception:
        pass
    # v0.4.0: async KEK preload (rekeys KeyStore to hardware-backed KEK),
    # then show app lock if enabled.
    try:
        page.run_task(_preload_kek)
    except Exception:
        pass
    try:
        if lock_prefs(store)["enabled"]:
            lock_now()
    except Exception:
        pass

    # ---- onboarding tour (v0.5 R5, first-run BottomSheet wizard) ----
    tour = {"step": "provider", "pid": "gemini", "model": ""}
    tour_body = ft.Column(spacing=8, tight=True, scroll=ft.ScrollMode.AUTO)
    tour_sheet = ft.BottomSheet(
        content=ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("Welcome to INF ai", weight=ft.FontWeight.BOLD, size=16, expand=True),
                            ft.TextButton(content=ft.Text("Skip"), on_click=lambda _: _close_tour(False)),
                        ]
                    ),
                    ft.Text("", size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                    tour_body,
                ],
                spacing=8,
                tight=True,
            ),
            padding=16,
            height=520,
        ),
        show_drag_handle=True,
    )
    page.overlay.append(tour_sheet)
    tour_dots = tour_sheet.content.content.controls[1]

    def _close_tour(done: bool = False) -> None:
        # Once per install: ANY exit (done, Skip, swipe-down) counts as
        # seen. Previously only done=True marked it, so Skip (or a swipe
        # dismiss, which bypasses this entirely) left the first-run gate
        # true and the tour nagged on every launch. Manual replay via
        # Settings → "Replay setup tour" still works (open_tour bypasses).
        _ = done
        try:
            mark_onboarded(store)
        except Exception:
            pass
        try:
            tour_sheet.open = False
            page.update()
        except Exception:
            pass

    try:
        tour_sheet.on_dismiss = lambda _: _close_tour(False)
    except Exception:
        pass

    def _tour_nav_row(back_to: str | None, next_to: str | None, next_label: str = "Next") -> ft.Row:
        items: list[ft.Control] = []
        if back_to is not None:
            items.append(ft.TextButton(content=ft.Text("Back"),
                                       on_click=lambda _: _go_tour(back_to)))
        items.append(ft.Container(expand=True))
        if next_to is not None:
            items.append(ft.FilledButton(content=ft.Text(next_label),
                                         on_click=lambda _: _go_tour(next_to)))
        return ft.Row(items, tight=True)

    def _go_tour(step: str) -> None:
        # Validate before leaving key/model steps.
        cur = tour.get("step", "provider")
        if cur == "key" and step != "provider":
            if not (tour_key_field.value or "").strip():
                show_snack("Paste an API key first — or Skip the tour.")
                return
            store.set_key(tour.get("pid", "gemini"), (tour_key_field.value or "").strip())
        if cur == "model" and step == "start":
            pid = tour.get("pid", "gemini")
            model = (tour_model_dd.value or "").strip()
            if not model:
                show_snack("Pick a model first — or Skip the tour.")
                return
            tour["model"] = model
            try:
                provider_dd.value = pid
                refresh_models(None)
                model_dd.value = model
                persist_model(None)
            except Exception:
                pass
        tour["step"] = step
        _render_tour()

    async def _tour_test(_: ft.ControlEvent | None = None) -> None:
        key = (tour_key_field.value or "").strip()
        if not key:
            tour_test_result.value = "Paste an API key first."
            tour_test_result.color = ft.Colors.AMBER
            page.update()
            return
        pid = tour.get("pid", "gemini")
        tour_test_result.value = "Testing…"
        tour_test_result.color = None
        page.update()
        try:
            base = PROVIDERS.get(pid, {}).get("base_url", "") or None
            provider = get_provider(pid, key, base)
            try:
                picked_model = (tour_model_dd.value or "").strip()
            except Exception:
                picked_model = ""
            reply = await provider.acomplete([Message("user", "Reply with exactly: ok")],
                                             picked_model or PROVIDERS.get(pid, {}).get("default_model", ""),
                                             max_tokens=8)
            tour_test_result.value = f"OK — connected ({(reply or '').strip()[:60] or 'reachable'})."
            tour_test_result.color = ft.Colors.GREEN
        except ProviderError as e:
            tour_test_result.value = f"Failed: {e.friendly()}"
            tour_test_result.color = ft.Colors.RED
        except Exception as e:  # noqa: BLE001
            tour_test_result.value = f"Failed: {e}"
            tour_test_result.color = ft.Colors.RED
        try:
            page.update()
        except Exception:
            pass

    tour_pid_dd = ft.Dropdown(
        label="Provider",
        options=[ft.dropdown.Option(pid) for pid in PROVIDER_IDS],
        value="gemini",
        dense=True,
    )
    tour_key_field = ft.TextField(label="API key (stored on-device only)", password=True,
                                  can_reveal_password=True, dense=True)
    tour_test_result = ft.Text("", size=12, selectable=True)
    tour_model_dd = ft.Dropdown(label="Model", editable=True, dense=True)

    def _tour_pid(_: ft.ControlEvent | None = None) -> None:
        tour["pid"] = (tour_pid_dd.value or "gemini").strip() or "gemini"
        try:
            models = available_models(tour["pid"])
            tour_model_dd.options = [ft.dropdown.Option(m) for m in models]
            tour_model_dd.value = PROVIDERS.get(tour["pid"], {}).get("default_model", "") or None
        except Exception:
            pass
        try:
            page.update()
        except Exception:
            pass

    tour_pid_dd.on_change = _tour_pid

    def _render_tour() -> None:
        step = tour.get("step", "provider")
        tour_dots.value = step_dots(step)
        if step == "provider":
            tour_body.controls = [
                ft.Text("Pick a free study model provider. Keys stay on this device.", size=12),
                tour_pid_dd,
                _tour_nav_row(None, "key"),
            ]
        elif step == "key":
            tour_body.controls = [
                ft.Text(f"Create a key for {PROVIDERS.get(tour.get('pid', ''), {}).get('display_name', tour.get('pid', ''))}, then paste it here.", size=12),
                tour_key_field,
                ft.Row([ft.OutlinedButton(content=ft.Text("Test"), on_click=_tour_test),
                        tour_test_result], spacing=8, tight=True, wrap=True),
                _tour_nav_row("provider", "model"),
            ]
        elif step == "model":
            _tour_pid(None)
            tour_body.controls = [
                ft.Text("Pick a free study model to start with.", size=12),
                tour_model_dd,
                _tour_nav_row("key", "start"),
            ]
        else:
            starters = coerce_starters(None)[:2]
            chips = [
                ft.Chip(label=ft.Text(s.title, size=12),
                        on_click=lambda _, _s=s: _tour_start(_s))
                for s in starters
            ]
            tour_body.controls = [
                ft.Text("You're set! Try a study starter — it sends right away.", size=12),
                ft.Row(chips, wrap=True, spacing=8),
                _tour_nav_row("model", None),
                ft.FilledButton(content=ft.Text("Start studying"),
                                on_click=lambda _: _close_tour(True)),
            ]
        try:
            tour_sheet.open = True
            page.update()
        except Exception:
            pass

    def _tour_start(s) -> None:
        _close_tour(True)
        try:
            on_starter(s)
        except Exception:
            pass

    def open_tour(_: ft.ControlEvent | None = None) -> None:
        tour["step"] = "provider"
        tour["pid"] = (provider_dd.value or "gemini").strip() or "gemini"
        try:
            tour_pid_dd.value = tour["pid"]
        except Exception:
            pass
        _render_tour()

    # First-run gate (non-blocking: sheet dismisses freely, Skip always visible).
    try:
        if needs_onboarding(store):
            open_tour()
    except Exception:
        pass


if __name__ == "__main__":
    ft.run(main)
