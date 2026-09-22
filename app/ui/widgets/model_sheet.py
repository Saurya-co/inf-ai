"""Bottom-sheet model picker content (grouped by provider, searchable).

v0.5 refinement: collapsible provider groups, structured capability badges,
inline detail expand, custom model entry.
"""

from __future__ import annotations

import json
import re
from typing import Callable

import flet as ft

from app.config import PROVIDER_IDS, PROVIDERS, available_models, supports_docs, supports_vision, get_model_metadata
from app.ui.phosphor import ph

# Flet >=0.86 removed padding.symmetric/all helpers — build Padding directly.
def _pad(h: int, v: int) -> ft.padding.Padding:
    return ft.padding.Padding(left=h, top=v, right=h, bottom=v)

def _pad_h(h: int) -> ft.padding.Padding:
    return ft.padding.Padding(left=h, top=0, right=h, bottom=0)

def _pad_v(v: int) -> ft.padding.Padding:
    return ft.padding.Padding(left=0, top=v, right=0, bottom=v)

def _pad_only(left: int = 0, top: int = 0, right: int = 0, bottom: int = 0) -> ft.padding.Padding:
    return ft.padding.Padding(left=left, top=top, right=right, bottom=bottom)

RECENT_MAX = 5
PRESETS: tuple[str, ...] = ("all", "free", "vision", "docs")

CAPABILITY_ICONS: dict[str, str] = {
    "vision": "phosphor/eye.svg",
    "docs": "phosphor/file-text.svg",
    "image": "phosphor/image.svg",
    "function_calling": "phosphor/gear.svg",
    "json_mode": "phosphor/brackets-curly.svg",
    "reasoning": "phosphor/lightbulb.svg",
    "code_execution": "phosphor/terminal.svg",
    "code_specialist": "phosphor/code.svg",
    "long_context": "phosphor/infinity.svg",
}

CAPABILITY_LABELS: dict[str, str] = {
    "vision": "Vision",
    "docs": "Documents",
    "image": "Image out",
    "function_calling": "Functions",
    "json_mode": "JSON Mode",
    "reasoning": "Reasoning",
    "code_execution": "Code Exec",
    "code_specialist": "Code",
    "long_context": "Long Ctx",
}


def push_recent(recents: list, pid: str, model: str, limit: int = RECENT_MAX) -> list:
    """Most-recent-first dedup list of (pid, model) pairs."""
    out: list = [(str(pid), str(model))]
    for r in recents or []:
        try:
            pair = (str(r[0]), str(r[1]))
        except Exception:
            continue
        if pair != out[0] and pair not in out:
            out.append(pair)
    return out[: max(1, int(limit))]


def parse_recents(raw: str) -> list:
    try:
        data = json.loads(raw or "[]")
    except Exception:
        return []
    out: list = []
    for r in data if isinstance(data, list) else []:
        try:
            out.append((str(r[0]), str(r[1])))
        except Exception:
            continue
    return out[:RECENT_MAX]


def apply_preset_filter(
    rows: list[tuple[str, str, bool]], preset: str
) -> list[tuple[str, str, bool]]:
    """Filter (pid, model, free) rows by preset chip."""
    p = (preset or "all").lower()
    if p == "free":
        return [r for r in rows if r[2]]
    if p == "vision":
        kept = []
        for pid, model, free in rows:
            try:
                if supports_vision(pid, model):
                    kept.append((pid, model, free))
            except Exception:
                continue
        return kept
    if p == "docs":
        kept = []
        for pid, model, free in rows:
            try:
                if supports_docs(pid, model):
                    kept.append((pid, model, free))
            except Exception:
                continue
        return kept
    return list(rows)


def capability_matrix() -> list[tuple[str, str, str, str]]:
    """Return [(display, models_count, vision_models, docs_flag)] rows."""
    rows: list[tuple[str, str, str, str]] = []
    for pid in PROVIDER_IDS:
        reg = PROVIDERS.get(pid, {})
        models = available_models(pid)
        vision_n = 0
        docs_n = 0
        for m in models:
            try:
                if supports_vision(pid, m):
                    vision_n += 1
            except Exception:
                pass
            try:
                if supports_docs(pid, m):
                    docs_n += 1
            except Exception:
                pass
        rows.append(
            (
                str(reg.get("display_name", pid)),
                str(len(models)),
                f"{vision_n}/{len(models)}",
                f"{docs_n}/{len(models)}",
            )
        )
    return rows


def row_search_text(pid: str, model: str) -> str:
    """Lowercase search haystack for a model row: ids, provider display
    name, capabilities (vision/docs/image/…), context size (raw + 1m/128k
    shorthands), pricing tier, and family words split from the model id.

    Pure + unit-tested — this is what makes the sheet search feel smart.
    """
    reg = PROVIDERS.get(pid, {})
    meta = get_model_metadata(pid, model)
    bits: list[str] = [pid, model, str(reg.get("display_name", ""))]
    try:
        caps = [str(c) for c in (meta.get("capabilities", []) or [])]
    except Exception:
        caps = []
    try:
        if supports_vision(pid, model) and "vision" not in caps:
            caps.append("vision")
    except Exception:
        pass
    try:
        if supports_docs(pid, model) and "docs" not in caps:
            caps.append("docs")
    except Exception:
        pass
    bits.extend(caps)
    if reg.get("free"):
        bits.append("free")
    try:
        tier = str(meta.get("pricing_tier", "") or "")
        if tier and tier != "unknown":
            bits.append(tier)
    except Exception:
        pass
    try:
        ctx = int(meta.get("context_window", 0) or 0)
    except Exception:
        ctx = 0
    if ctx > 0:
        bits.append(str(ctx))
        if ctx >= 1_000_000:
            bits.append(f"{round(ctx / 1_000_000)}m")
        else:
            bits.append(f"{round(ctx / 1024)}k")
    # Family words: "qwen/qwen3-coder-480b:free" -> qwen, coder, 480b.
    try:
        for tok in re.split(r"[^a-z0-9]+", (model or "").lower()):
            if tok:
                bits.append(tok)
    except Exception:
        pass
    return " ".join(str(b) for b in bits).lower()


def iter_model_rows(
    query: str = "", linked: set[str] | frozenset[str] | None = None
) -> list[tuple[str, str, bool]]:
    """Return (provider_id, model, free) rows filtered by query.

    ``linked`` is the set of provider ids with an API key configured —
    when given, only those providers' models are listed (the sheet must
    never offer a model the user can't actually send to). The query is
    tokenized on whitespace: every word must match somewhere in the row's
    search text (ids, provider name, capabilities, context, pricing).
    """
    toks = [t for t in (query or "").strip().lower().split() if t]
    rows: list[tuple[str, str, bool]] = []
    for pid in PROVIDER_IDS:
        if linked is not None and pid not in linked:
            continue
        reg = PROVIDERS.get(pid, {})
        for m in available_models(pid):
            if toks and not all(t in row_search_text(pid, m) for t in toks):
                continue
            rows.append((pid, m, bool(reg.get("free"))))
    return rows[:200]


def _capability_badges(pid: str, model: str) -> list[ft.Control]:
    """Return list of capability badge containers for a model."""
    meta = get_model_metadata(pid, model)
    badges: list[ft.Control] = []
    for cap in meta.get("capabilities", []):
        icon_path = CAPABILITY_ICONS.get(cap)
        label = CAPABILITY_LABELS.get(cap, cap.replace("_", " ").title())
        if icon_path:
            badges.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Image(src=icon_path, width=12, height=12),
                            ft.Text(label, size=10),
                        ],
                        spacing=4,
                        tight=True,
                    ),
                    padding=_pad(6, 3),
                    border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                    border_radius=12,
                )
            )
    vision = supports_vision(pid, model)
    if vision and "vision" not in meta.get("capabilities", []):
        badges.append(
            ft.Container(
                content=ft.Row(
                    [
                        ft.Image(src="phosphor/eye.svg", width=12, height=12),
                        ft.Text("Vision", size=10),
                    ],
                    spacing=4,
                    tight=True,
                ),
                padding=_pad(6, 3),
                border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                border_radius=12,
            )
        )
    try:
        docs = supports_docs(pid, model)
        if docs and "docs" not in meta.get("capabilities", []):
            badges.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Image(src="phosphor/file-text.svg", width=12, height=12),
                            ft.Text("Docs", size=10),
                        ],
                        spacing=4,
                        tight=True,
                    ),
                    padding=_pad(6, 3),
                    border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                    border_radius=12,
                )
            )
    except Exception:
        pass
    return badges


def _build_detail_expansion(pid: str, model: str, on_detail: Callable[[str, str], None]) -> ft.Container:
    """Build an expandable detail row for a model."""
    meta = get_model_metadata(pid, model)
    specs = [
        ("Context", f"{meta.get('context_window', 0) // 1000}K" if meta.get('context_window', 0) < 1_000_000 else f"{meta.get('context_window', 0) // 1_000_000}M"),
        ("Max Output", f"{meta.get('max_output', 0) // 1000}K"),
        ("Cutoff", meta.get("knowledge_cutoff", "?")),
        ("Pricing", meta.get("pricing_tier", "?").title()),
    ]
    detail_controls = [
        ft.Text("Details", size=11, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE_VARIANT),
        ft.Row(
            [
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(label, size=10, color=ft.Colors.ON_SURFACE_VARIANT),
                            ft.Text(value, size=11, weight=ft.FontWeight.W_500),
                        ],
                        spacing=2,
                        tight=True,
                    ),
                    expand=True,
                    padding=_pad_only(right=12),
                )
                for label, value in specs
            ],
            spacing=0,
            tight=True,
            wrap=True,
        ),
        ft.Row(
            [
                ft.TextButton(
                    content=ft.Text("View full details", size=11),
                    on_click=lambda _, p=pid, m=model: on_detail(p, m),
                    style=ft.ButtonStyle(padding=_pad(8, 4)),
                ),
            ],
            alignment=ft.MainAxisAlignment.END,
        ),
    ]
    return ft.Container(
        content=ft.Column(detail_controls, spacing=6, tight=True),
        padding=_pad_only(top=8, bottom=4, left=56, right=12),
        bgcolor=ft.Colors.with_opacity(0.03, ft.Colors.ON_SURFACE),
        border_radius=ft.BorderRadius.only(bottom_left=12, bottom_right=12),
        animate_size=ft.Animation(150, ft.AnimationCurve.EASE_OUT),
    )


def build_model_list(
    query: str,
    current: tuple[str, str],
    on_pick: Callable[[str, str], None],
    on_detail: Callable[[str, str], None] | None = None,
    preset: str = "all",
    recents: list | None = None,
    linked: set[str] | frozenset[str] | None = None,
    on_add_key: Callable[[], None] | None = None,
) -> list[ft.Control]:
    controls: list[ft.Control] = []
    if recents:
        controls.append(
            ft.Text("Recent", size=11, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE_VARIANT)
        )
        for pid, model in recents[:RECENT_MAX]:
            selected = (pid, model) == current
            controls.append(
                ft.ListTile(
                    leading=ft.Icon(ft.Icons.HISTORY, size=20),
                    title=ft.Text(model, size=13, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    subtitle=ft.Text(PROVIDERS.get(pid, {}).get("display_name", pid), size=11),
                    selected=selected,
                    data=f"{pid}|||{model}",
                    on_click=lambda e: on_pick(*str(e.control.data).split("|||")),
                )
            )

    rows = apply_preset_filter(iter_model_rows(query, linked), preset)

    # No API key linked anywhere: explain before anything else — the user
    # can't send to any model until a key is added. Tapping the tile jumps
    # to Study keys when the app wires on_add_key (None in tests).
    if linked is not None and not linked:
        controls.append(
            ft.ListTile(
                leading=ft.Icon(ft.Icons.KEY_OFF_OUTLINED, size=20, color=ft.Colors.AMBER),
                title=ft.Text("No API keys linked", size=13, weight=ft.FontWeight.BOLD),
                subtitle=ft.Text(
                    "Add a key via the menu → Study keys to unlock these models.",
                    size=11,
                ),
                trailing=ft.Icon(ft.Icons.ARROW_FORWARD, size=18) if on_add_key else None,
                on_click=lambda _: on_add_key() if on_add_key else None,
            )
        )

    # Group by provider
    provider_groups: dict[str, list[tuple[str, str, bool]]] = {}
    for pid, model, free in rows:
        provider_groups.setdefault(pid, []).append((pid, model, free))

    for pid in PROVIDER_IDS:
        if pid not in provider_groups:
            continue
        reg = PROVIDERS.get(pid, {})
        provider_models = provider_groups[pid]
        display_name = reg.get("display_name", pid)
        is_free = reg.get("free", False)
        model_count = len(provider_models)

        # Provider header (collapsible)
        expanded_state = {"value": True}

        def make_header(p=pid, name=display_name, count=model_count, free=is_free):
            header = ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.KEYBOARD_ARROW_DOWN, size=18, rotate=ft.Rotate(0)),
                        ft.Text(name, size=12, weight=ft.FontWeight.BOLD, expand=True),
                        ft.Container(
                            content=ft.Text(f"{count} models", size=10, color=ft.Colors.ON_SURFACE_VARIANT),
                            padding=_pad(8, 2),
                        ),
                        ft.Container(
                            content=ft.Text("FREE", size=9, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN),
                            padding=_pad(6, 1),
                            bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.GREEN),
                            border_radius=3,
                        ) if free else ft.Container(),
                    ],
                    spacing=8,
                    tight=True,
                ),
                padding=_pad(12, 10),
                on_click=lambda _, p=p: toggle_provider(p),
            )
            return header

        provider_content = ft.Column(spacing=0, tight=True)
        provider_wrapper = ft.Column(
            [
                make_header(),
                provider_content,
            ],
            spacing=0,
            tight=True,
        )
        provider_wrapper.data = pid  # identity for the collapse toggle

        def toggle_provider(p: str):
            # Toggle only the clicked provider's section (matched by data).
            for ctrl in controls:
                if isinstance(ctrl, ft.Column) and ctrl.data == p:
                    try:
                        header = ctrl.controls[0]
                        icon = header.content.controls[0]
                        expanded = icon.rotate.angle == 0
                        icon.rotate = ft.Rotate(0 if not expanded else 3.14159 / 2)
                        if len(ctrl.controls) > 1:
                            ctrl.controls[1].visible = not expanded
                        pg = getattr(header, "page", None)
                        if pg is not None:
                            pg.update()
                    except Exception:
                        pass
                    return

        # Build model rows for this provider
        for pid_m, model, free in provider_models:
            selected = (pid_m, model) == current
            badges = _capability_badges(pid_m, model)

            # Main tile
            tile = ft.ListTile(
                leading=ft.Icon(
                    ft.Icons.CHECK if selected else ft.Icons.SMART_TOY_OUTLINED,
                    size=20,
                ),
                title=ft.Text(model, size=13, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                # Provider name lives in the section header — the row shows
                # only capability badges (ChatGPT-like decluttered list).
                subtitle=ft.Row(badges, spacing=4, tight=True, wrap=True) if badges else None,
                trailing=ph("seal-check", 14) if free else ft.Container(width=14),
                selected=selected,
                data=f"{pid_m}|||{model}",
                on_click=lambda e: on_pick(*str(e.control.data).split("|||")),
                on_long_press=lambda e: on_detail(*str(e.control.data).split("|||")) if on_detail else None,
            )

            # Expandable detail
            detail = _build_detail_expansion(pid_m, model, on_detail) if on_detail else ft.Container()
            detail.visible = False
            detail.height = 0

            # Tile with detail expansion
            model_wrapper = ft.Column([tile, detail], spacing=0, tight=True)

            def make_tile_toggle(d: ft.Control = detail):
                def _toggle(e: ft.ControlEvent | None = None):
                    d.visible = not d.visible
                    d.height = None if d.visible else 0
                    try:
                        # Use the event's page (bound to the live view), not
                        # the loop-captured `tile` which ends as the last row.
                        pg = getattr(getattr(e, "control", None), "page", None)
                        if pg is not None:
                            pg.update()
                        else:
                            d.update()
                    except Exception:
                        pass
                return _toggle

            if on_detail is not None:
                # Long-press opens the full detail sheet; single-tap toggles
                # the inline expansion. Previously the toggle overwrote
                # on_long_press so detail never opened.
                _toggle_fn = make_tile_toggle()
                _detail_cb = on_detail

                def _on_long_press(e: ft.ControlEvent, _d: ft.Control = detail,
                                   _toggle: object = _toggle_fn, _cb: object = _detail_cb):
                    try:
                        parts = str(e.control.data).split("|||")
                        _cb(*parts)  # type: ignore[operator]
                    except Exception:
                        try:
                            _toggle(None)  # type: ignore[operator]
                        except Exception:
                            pass

                tile.on_long_press = _on_long_press  # type: ignore[assignment]
            provider_content.controls.append(model_wrapper)

        controls.append(provider_wrapper)

    # No matches: hint BEFORE the custom-model tile so a failed search
    # always explains itself instead of showing only the custom row.
    if not rows and not recents:
        controls.append(
            ft.ListTile(
                title=ft.Text("No matches — try a custom model below", size=13),
                subtitle=ft.Text("e.g. OpenRouter ':free' names work as custom text", size=11),
            )
        )

    # Custom model entry
    controls.append(
        ft.Divider(height=1)
    )
    controls.append(
        ft.Text("Custom model", size=11, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE_VARIANT)
    )
    controls.append(
        ft.ListTile(
            leading=ft.Icon(ft.Icons.ADD_CIRCLE_OUTLINE, size=20, color=ft.Colors.PRIMARY),
            title=ft.Text("Add custom model", size=13, color=ft.Colors.PRIMARY),
            subtitle=ft.Text("Enter a model ID not in the list (e.g. openrouter/glm-5.2:free)", size=11),
            on_click=lambda _: on_pick("custom", "__CUSTOM__"),
        )
    )
    return controls