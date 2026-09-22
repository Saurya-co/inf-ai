"""Providers screen — collapsible + searchable BYOK cards.

Research-backed (Flet ExpansionTile docs; BYOKit/JetBrains/TanStack BYOK UX):
- One collapsible card per provider (ExpansionTile, maintain_state=True so
  typed keys survive collapse). No nested scrollables inside tiles.
- Search field + filter chips (All / Configured / Free / Active).
- Per-card status: masked key (••••abcd), model, FREE/ACTIVE badges,
  green check vs grey key leading icon.
- Key row: paste-from-clipboard, clear, reveal; masked "In use" helper.
- Base URL row with reset-to-default. Model dropdown editable (custom ok).
- Actions: Use as active, Test connection (minimal 8-token ping), Get key
  deep link, copy-error button. Keys stay on-device, never logged.
"""

from __future__ import annotations

import flet as ft
import time

from app.config import (
    PROVIDER_IDS,
    PROVIDERS,
    available_models,
    set_live_models,
    supports_docs,
    supports_vision,
)
from app.core.errors import ProviderError
from app.core.provider_factory import get_provider
from app.core.provider_factory import normalize_base_url
from app.core.types import Message
from app.data.key_store import KeyStore
from app.ui.phosphor import ph


def provider_meta_section(provider_id: str) -> str:
    """KeyStore section for R3 health/latency meta (plain, not secrets)."""
    return f"prov_{provider_id}"


def format_latency(ms: int | float | None) -> str:
    """'12 ms' / '1.2 s' / '—' for test round-trips."""
    try:
        ms = float(ms)  # type: ignore[arg-type]
    except Exception:
        return "—"
    if ms < 0:
        return "—"
    if ms < 1000:
        return f"{int(round(ms))} ms"
    return f"{ms / 1000:.1f} s"


def health_state(ok: bool | None) -> str:
    """'ok' | 'fail' | 'untested' from the last Test outcome."""
    if ok is True:
        return "ok"
    if ok is False:
        return "fail"
    return "untested"


def health_line(provider_id: str, store: KeyStore) -> str:
    """One-line health summary for a provider tile."""
    sec = provider_meta_section(provider_id)
    try:
        ok_raw = store.get(sec, "health", "")
        ok = {"ok": True, "fail": False}.get(ok_raw.strip().lower())
    except Exception:
        ok = None
    state = health_state(ok)
    if state == "untested":
        return "Not tested yet"
    try:
        lat = format_latency(float(store.get(sec, "latency_ms", "")))
    except Exception:
        lat = "—"
    try:
        at = store.get(sec, "tested_at", "").strip() or "?"
    except Exception:
        at = "?"
    word = "OK" if state == "ok" else "Failed"
    return f"{word} • {lat} • {at}"


def capability_line(provider_id: str) -> str:
    """'5 models • vision 1/5 • docs 5/5' from the offline registry."""
    try:
        models = available_models(provider_id)
    except Exception:
        models = []
    n = len(models)
    if not n:
        return "No models listed — type a custom one"
    vision_n = docs_n = 0
    for m in models:
        try:
            if supports_vision(provider_id, m):
                vision_n += 1
        except Exception:
            pass
        try:
            if supports_docs(provider_id, m):
                docs_n += 1
        except Exception:
            pass
    return f"{n} model(s) • vision {vision_n}/{n} • docs {docs_n}/{n}"


def record_test_result(store: KeyStore, provider_id: str, ok: bool, latency_ms: float | None) -> None:
    """Persist last-Test outcome (R3 latency/health badges)."""
    import datetime as _dt

    sec = provider_meta_section(provider_id)
    try:
        store.set(sec, "health", "ok" if ok else "fail")
        if latency_ms is not None:
            store.set(sec, "latency_ms", str(int(round(float(latency_ms)))))
        store.set(sec, "tested_at", _dt.datetime.now().strftime("%H:%M"))
    except Exception:
        pass


def record_live_models(store: KeyStore, provider_id: str, count: int) -> None:
    """Persist live-model refresh stamp (R3 model-count badge)."""
    import datetime as _dt

    sec = provider_meta_section(provider_id)
    try:
        store.set(sec, "live_count", str(max(0, int(count))))
        store.set(sec, "live_at", _dt.datetime.now().strftime("%H:%M"))
    except Exception:
        pass

# Deep links — where to create a key (BYOK onboarding pattern).
PROVIDER_LINKS: dict[str, str] = {
    "gemini": "https://aistudio.google.com/app/apikey",
    "groq": "https://console.groq.com/keys",
    "openrouter": "https://openrouter.ai/keys",
    "together": "https://api.together.xyz/settings/api-keys",
    "huggingface": "https://huggingface.co/settings/tokens",
    "deepseek": "https://platform.deepseek.com/api_keys",
    "openai": "https://platform.openai.com/api-keys",
    "anthropic": "https://console.anthropic.com/settings/keys",
    "custom": "",
}


def _pad(h: int, v: int) -> ft.padding.Padding:
    """Flet >=0.86 removed padding.symmetric/all helpers — build Padding directly."""
    return ft.padding.Padding(left=h, top=v, right=h, bottom=v)


def _safe_str(value: object, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _current_model(provider_id: str, store: KeyStore) -> str:
    try:
        reg = PROVIDERS.get(provider_id, {})
        if not isinstance(reg, dict):
            return ""
        saved = _safe_str(store.get_model(provider_id, "")).strip()
        if saved:
            return saved[:200]
        default = reg.get("default_model", "")
        return default if isinstance(default, str) else ""
    except Exception:
        return ""


def _current_base_url(provider_id: str, store: KeyStore) -> str:
    try:
        saved = _safe_str(store.get_base_url(provider_id, "")).strip()
        reg = PROVIDERS.get(provider_id, {})
        base = reg.get("base_url", "") if isinstance(reg, dict) else ""
        value = saved or (base if isinstance(base, str) else "")
        if value and "://" not in value:
            value = "https://" + value
        return value[:500]
    except Exception:
        return ""


def _active_target(store: KeyStore) -> tuple[str, str]:
    try:
        pid = _safe_str(store.get("chat", "provider", "gemini"), "gemini").strip() or "gemini"
    except Exception:
        pid = "gemini"
    try:
        model = _safe_str(store.get("chat", "model", "")).strip()
    except Exception:
        model = ""
    if pid not in PROVIDERS:
        pid = "gemini"
    if not model:
        try:
            default = PROVIDERS[pid].get("default_model", "")
            model = default if isinstance(default, str) else ""
        except Exception:
            model = ""
    return pid, model


def _provider_tile(
    page: ft.Page,
    store: KeyStore,
    provider_id: str,
    expanded: bool,
    on_use_provider,
    notify,
) -> ft.ExpansionTile:
    reg = PROVIDERS[provider_id]
    result = ft.Text("", size=12, selectable=True)
    # v0.5 R3: health/latency + capability summary, refreshed after Test.
    health_dot = ft.Icon(ft.Icons.HELP_OUTLINE, size=14)
    health_txt = ft.Text(health_line(provider_id, store), size=11,
                         color=ft.Colors.ON_SURFACE_VARIANT)
    caps_txt = ft.Text("", size=11, color=ft.Colors.ON_SURFACE_VARIANT)

    def refresh_meta_lines() -> None:
        try:
            health_txt.value = health_line(provider_id, store)
            sec = provider_meta_section(provider_id)
            ok_raw = store.get(sec, "health", "").strip().lower()
            if ok_raw == "ok":
                health_dot.name = ft.Icons.CHECK_CIRCLE
                health_dot.color = ft.Colors.GREEN
            elif ok_raw == "fail":
                health_dot.name = ft.Icons.ERROR_OUTLINE
                health_dot.color = ft.Colors.RED
            else:
                health_dot.name = ft.Icons.HELP_OUTLINE
                health_dot.color = None
        except Exception:
            pass
        try:
            sec = provider_meta_section(provider_id)
            lc = store.get(sec, "live_count", "").strip()
            la = store.get(sec, "live_at", "").strip()
            base = capability_line(provider_id)
            caps_txt.value = f"{base} • live {lc} @ {la}" if lc else base
        except Exception:
            pass

    refresh_meta_lines()
    active_pid, active_model = _active_target(store)
    is_active = active_pid == provider_id

    def _header_texts() -> tuple[str, str]:
        key = store.get_key(provider_id).strip()
        masked = KeyStore.mask(key)
        model = _current_model(provider_id, store) or "no model set"
        sub = f"{masked} • {model}"
        return reg["display_name"], sub

    title_text, sub_text = _header_texts()
    has_key = bool(store.get_key(provider_id).strip())

    title = ft.Text(title_text, weight=ft.FontWeight.BOLD if is_active else ft.FontWeight.NORMAL)
    subtitle = ft.Text(sub_text, size=11)
    leading = ft.Icon(
        ft.Icons.CHECK_CIRCLE if has_key else ft.Icons.KEY_OFF_OUTLINED,
        size=22,
        color=ft.Colors.GREEN if has_key else None,
    )
    badges = [ft.Container(width=0)]
    if reg.get("free"):
        badges.append(
            ft.Container(
                content=ft.Row([ph("seal-check", 11), ft.Text("FREE", size=10, weight=ft.FontWeight.BOLD)], spacing=4, tight=True),
                bgcolor=ft.Colors.with_opacity(0.2, ft.Colors.GREEN),
                border_radius=8,
                padding=_pad(8, 4),
            )
        )
    if is_active:
        badges.append(
            ft.Container(
                content=ft.Text("ACTIVE", size=10, weight=ft.FontWeight.BOLD),
                bgcolor=ft.Colors.with_opacity(0.18, ft.Colors.PRIMARY),
                border_radius=8,
                padding=_pad(8, 4),
            )
        )
    trailing = ft.Row(badges, spacing=4, tight=True)

    def refresh_header() -> None:
        t, s = _header_texts()
        title.value = t
        subtitle.value = s
        hk = bool(store.get_key(provider_id).strip())
        leading.icon = ft.Icons.CHECK_CIRCLE if hk else ft.Icons.KEY_OFF_OUTLINED
        leading.color = ft.Colors.GREEN if hk else None
        apid, _ = _active_target(store)
        title.weight = ft.FontWeight.BOLD if apid == provider_id else ft.FontWeight.NORMAL

    key_field = ft.TextField(
        label="API key (stored on-device only)",
        password=True,
        can_reveal_password=True,
        value=store.get_key(provider_id),
        expand=True,
        dense=True,
    )
    key_helper = ft.Text(f"In use: {KeyStore.mask(store.get_key(provider_id))}", size=11)
    base_field = ft.TextField(
        label="Base URL",
        value=_current_base_url(provider_id, store),
        helper=ft.Text(f"Default: {reg['base_url'] or '— set required —'}", size=11),
        expand=True,
        dense=True,
    )
    current_model = _current_model(provider_id, store)
    model_values = available_models(provider_id)
    if current_model and current_model not in model_values:
        model_values = [current_model, *model_values]
    model_options = [ft.dropdown.Option(m) for m in model_values]
    model_status = ft.Text("Using saved/default models. Refresh to query the provider.", size=11)
    model_field = ft.Dropdown(
        label="Model (type a custom one too)",
        editable=True,
        enable_filter=True,
        options=model_options,
        value=current_model or None,
        helper_text="Custom names allowed, e.g. OpenRouter ':free' models.",
        expand=True,
        dense=True,
    )

    async def refresh_models(_: ft.ControlEvent | None = None) -> None:
        # Prefer the typed key, fall back to the saved one — refreshing must
        # never force a retype when a key is already stored on-device.
        try:
            typed_key = (key_field.value or "").strip() if isinstance(key_field.value, str) else ""
        except Exception:
            typed_key = ""
        try:
            saved_key = store.get_key(provider_id)
            saved_key = saved_key.strip() if isinstance(saved_key, str) else ""
        except Exception:
            saved_key = ""
        api_key = typed_key or saved_key
        base_url = (base_field.value or "").strip() or _current_base_url(provider_id, store).strip()
        if not api_key:
            model_status.value = "Add an API key before refreshing models."
            model_status.color = ft.Colors.AMBER
            page.update()
            return
        try:
            provider = get_provider(provider_id, api_key, base_url or None)
            model_status.value = "Loading live models…"
            model_status.color = None
            refresh_models_btn.disabled = True
            page.update()
            models = await provider.list_models()
            set_live_models(provider_id, models)
            current = (model_field.value or "").strip()
            model_field.options = [ft.dropdown.Option(m) for m in models]
            if current:
                model_field.value = current
            record_live_models(store, provider_id, len(models))
            try:
                la = store.get(provider_meta_section(provider_id), "live_at", "").strip()
                at = f" @ {la}" if la else ""
            except Exception:
                at = ""
            model_status.value = f"{len(models)} live model(s) loaded from {reg['display_name']}{at}."
            refresh_meta_lines()
            model_status.color = ft.Colors.GREEN
            if not typed_key:
                # Refreshed with the saved key: restore it into the field so
                # the trailing persist() can't wipe it with an empty value.
                key_field.value = api_key
            persist(None)
        except (ProviderError, ValueError) as e:
            model_status.value = f"Live model lookup failed: {e.friendly() if isinstance(e, ProviderError) else e}"
            model_status.color = ft.Colors.AMBER
            notify("Could not load live models; saved/default models are still available.")
        finally:
            refresh_models_btn.disabled = False
            page.update()

    def persist(_: ft.ControlEvent | None = None) -> None:
        store.set_key(provider_id, (key_field.value or "").strip())
        custom_base = (base_field.value or "").strip()
        try:
            normalized_base = normalize_base_url(custom_base) if custom_base else ""
        except ValueError:
            normalized_base = custom_base
        store.set_base_url(
            provider_id,
            "" if normalized_base == reg["base_url"].rstrip("/") else normalized_base,
        )
        store.set_model(provider_id, (model_field.value or "").strip())
        key_helper.value = f"In use: {KeyStore.mask(store.get_key(provider_id))}"
        refresh_header()
        try:
            page.update()
        except Exception:
            pass

    key_field.on_change = persist
    base_field.on_change = persist
    model_field.on_change = persist

    async def paste_key(_: ft.ControlEvent) -> None:
        try:
            clip = await page.clipboard.get()
            clip = (clip or "").strip()
            if clip:
                key_field.value = clip
                persist(None)
                notify("Key pasted — saved on-device. Clear clipboard after use.")
                # Best-effort clipboard hygiene: auto-clear pasted secret.
                try:
                    import asyncio as _aio

                    async def _autoclear(secret: str) -> None:
                        try:
                            await _aio.sleep(60)
                            cur = await page.clipboard.get()
                            if (cur or "").strip() == secret:
                                await page.clipboard.set("")
                        except Exception:
                            pass
                    _pasted = clip
                    page.run_task(_autoclear, _pasted)
                except Exception:
                    pass
            else:
                notify("Clipboard is empty.")
        except Exception:
            notify("Paste failed.")

    def clear_key(_: ft.ControlEvent) -> None:
        key_field.value = ""
        persist(None)
        notify(f"{reg['display_name']} key cleared.")

    def reset_base(_: ft.ControlEvent) -> None:
        base_field.value = reg["base_url"]
        persist(None)
        notify("Base URL reset to default.")

    def use_provider(_: ft.ControlEvent) -> None:
        model = (model_field.value or "").strip() or reg.get("default_model", "")
        store.set("chat", "provider", provider_id)
        store.set("chat", "model", model)
        refresh_header()
        notify(f"Active: {reg['display_name']} / {model or '—'}")
        if on_use_provider:
            on_use_provider(provider_id, model)

    test_btn = ft.FilledButton(content=ft.Text("Test"))
    refresh_models_btn = ft.OutlinedButton(
        content=ft.Text("Refresh live models"),
        icon=ft.Icons.REFRESH,
        on_click=lambda _: page.run_task(refresh_models, None),
    )
    use_btn = ft.OutlinedButton(content=ft.Text("Use as active"), on_click=use_provider)
    spinner = ft.ProgressRing(visible=False, width=16, height=16)
    copy_err_btn = ft.IconButton(icon=ft.Icons.COPY, tooltip="Copy result", icon_size=18, visible=False)

    async def copy_result(_: ft.ControlEvent) -> None:
        try:
            await page.clipboard.set(result.value or "")
            notify("Result copied.")
        except Exception as e:  # noqa: BLE001
            notify(f"Copy failed: {e}")

    copy_err_btn.on_click = copy_result
    link = PROVIDER_LINKS.get(provider_id, "")
    if link:
        get_key_btn = ft.TextButton(
            content=ft.Text("Get key"),
            icon=ft.Icons.OPEN_IN_NEW,
            on_click=lambda _: page.launch_url(link),
        )
    else:
        get_key_btn = ft.Container()

    async def on_test(_: ft.ControlEvent) -> None:
        try:
            persist(None)
        except Exception:
            pass
        try:
            raw_key = store.get_key(provider_id)
            api_key = raw_key.strip() if isinstance(raw_key, str) else ""
        except Exception:
            api_key = ""
        model = _current_model(provider_id, store).strip()
        base_url = _current_base_url(provider_id, store).strip()
        if not api_key:
            result.value = "Add an API key first (BYOK). Nothing was sent."
            result.color = ft.Colors.AMBER
            copy_err_btn.visible = False
            page.update()
            return
        if not model:
            result.value = "Pick or type a model first."
            result.color = ft.Colors.AMBER
            copy_err_btn.visible = False
            page.update()
            return
        test_btn.disabled = True
        spinner.visible = True
        copy_err_btn.visible = False
        result.value = f"Testing {reg['display_name']} / {model} …"
        result.color = None
        page.update()
        t0 = time.perf_counter()
        try:
            provider = get_provider(provider_id, api_key, base_url or None)
            reply = await provider.acomplete(
                [Message("user", "Reply with exactly: ok")], model, max_tokens=8
            )
            latency_ms = (time.perf_counter() - t0) * 1000
            record_test_result(store, provider_id, True, latency_ms)
            result.value = (
                f"OK ({format_latency(latency_ms)}) — connected. "
                f"Model replied: {reply.strip()[:120] or '(empty, but reachable)'}"
            )
            result.color = ft.Colors.GREEN
        except ProviderError as e:
            record_test_result(store, provider_id, False, None)
            result.value = f"Failed: {e.friendly()}"
            result.color = ft.Colors.RED
            copy_err_btn.visible = True
        except Exception as e:  # config errors and transport failures
            record_test_result(store, provider_id, False, None)
            result.value = f"Failed: {e}"
            result.color = ft.Colors.RED
            copy_err_btn.visible = True
        finally:
            refresh_meta_lines()
            test_btn.disabled = False
            spinner.visible = False
            page.update()

    test_btn.on_click = lambda _: page.run_task(on_test, None)

    body = ft.Column(
        [
            ft.Row(
                [key_field, ft.IconButton(icon=ft.Icons.PASTE_OUTLINED, tooltip="Paste from clipboard", icon_size=22, on_click=paste_key),
                 ft.IconButton(icon=ft.Icons.CLEAR, tooltip="Clear key", icon_size=22, on_click=clear_key)],
                spacing=4,
                tight=True,
            ),
            key_helper,
            ft.Row(
                [base_field, ft.IconButton(icon=ft.Icons.RESTORE, tooltip="Reset to default", icon_size=22, on_click=reset_base)],
                spacing=4,
                tight=True,
            ),
            ft.Row([model_field, refresh_models_btn], spacing=8, tight=True),
            model_status,
            ft.Row([use_btn, test_btn, spinner, get_key_btn], spacing=8, tight=True, wrap=True),
            ft.Row([result, copy_err_btn], spacing=4, tight=True),
            ft.Row([health_dot, health_txt], spacing=4, tight=True),
            caps_txt,
            ft.Text("Keys never leave your device — requests go straight to the provider.", size=11),
        ],
        spacing=8,
        tight=True,
    )
    tile = ft.ExpansionTile(
        title=title,
        subtitle=subtitle,
        leading=leading,
        trailing=trailing,
        controls=[ft.Container(content=body, padding=_pad(4, 4))],
        expanded=expanded,
        maintain_state=True,
    )
    return tile


def build_providers_view(page: ft.Page, store: KeyStore, on_use_provider=None) -> ft.Column:
    """Collapsible + searchable provider list with summary + filters."""
    snack = ft.SnackBar(content=ft.Text(""), behavior=ft.SnackBarBehavior.FLOATING)
    page.overlay.append(snack)

    def notify(text: str) -> None:
        try:
            snack.content.value = text  # type: ignore[union-attr]
            snack.open = True
            page.update()
        except Exception:
            pass

    ui_state = {"query": "", "filter": "all", "expand_all": None}  # None = smart default
    search = ft.TextField(label="Search providers or models", prefix_icon=ft.Icons.SEARCH, dense=True)
    summary = ft.Text("", size=12)
    tiles_box = ft.Column(spacing=8, tight=True, scroll=ft.ScrollMode.AUTO, expand=True)
    chips_row = ft.Row(spacing=6, tight=True, wrap=True)

    def matches(pid: str) -> bool:
        q = ui_state["query"].strip().lower()
        f = ui_state["filter"]
        reg = PROVIDERS[pid]
        has_key = bool(store.get_key(pid).strip())
        apid, _ = _active_target(store)
        if f == "configured" and not has_key:
            return False
        if f == "free" and not reg.get("free"):
            return False
        if f == "active" and pid != apid:
            return False
        if q:
            hay = f"{pid} {reg.get('display_name','')} {' '.join(available_models(pid))}".lower()
            if q not in hay:
                return False
        return True

    def refresh_summary() -> None:
        n_cfg = sum(1 for pid in PROVIDER_IDS if store.get_key(pid).strip())
        apid, amodel = _active_target(store)
        aname = PROVIDERS.get(apid, {}).get("display_name", apid)
        summary.value = f"{n_cfg}/{len(PROVIDER_IDS)} API keys saved • Active: {aname} / {amodel or '—'}"

    def rebuild() -> None:
        apid, _ = _active_target(store)
        tiles_box.controls.clear()
        for pid in PROVIDER_IDS:
            if not matches(pid):
                continue
            has_key = bool(store.get_key(pid).strip())
            if ui_state["expand_all"] is True:
                exp = True
            elif ui_state["expand_all"] is False:
                exp = False
            else:
                exp = pid == apid or has_key  # smart default
            tiles_box.controls.append(
                _provider_tile(page, store, pid, exp, _on_use_from_tile, notify)
            )
        if not tiles_box.controls:
            tiles_box.controls.append(ft.Text("No providers match — clear search or filters.", size=12))
        refresh_summary()

    def _on_use_from_tile(pid: str, model: str) -> None:
        ui_state["expand_all"] = None
        rebuild()
        page.update()
        if on_use_provider:
            on_use_provider(pid, model)

    def on_search(_: ft.ControlEvent) -> None:
        ui_state["query"] = search.value or ""
        rebuild()
        page.update()

    search.on_change = on_search

    def make_chip(name: str, label: str) -> ft.Chip:
        return ft.Chip(
            label=ft.Text(label, size=12),
            selected=ui_state["filter"] == name,
            show_checkmark=False,
            data=name,
            on_select=lambda e: _on_filter(str(e.control.data)),
        )

    def _on_filter(name: str) -> None:
        ui_state["filter"] = name
        for c in chips_row.controls:
            if isinstance(c, ft.Chip):
                c.selected = c.data == name
        rebuild()
        page.update()

    def expand_all(_: ft.ControlEvent | None = None) -> None:
        ui_state["expand_all"] = True
        rebuild()
        page.update()

    def collapse_all(_: ft.ControlEvent | None = None) -> None:
        ui_state["expand_all"] = False
        rebuild()
        page.update()

    chips_row.controls = [make_chip("all", "All"), make_chip("configured", "Configured"), make_chip("free", "Free tier"), make_chip("active", "Active")]

    rebuild()
    return ft.Column(
        [
            ft.Text(
                "Keys never leave your device — each request goes straight to the provider. "
                "Start with a free tier: Gemini, Groq, or OpenRouter :free.",
                size=12,
            ),
            search,
            chips_row,
            ft.Row(
                [summary, ft.TextButton(content=ft.Text("Expand all"), on_click=expand_all),
                 ft.TextButton(content=ft.Text("Collapse all"), on_click=collapse_all)],
                spacing=4,
                tight=True,
            ),
            tiles_box,
        ],
        spacing=10,
        expand=True,
    )
