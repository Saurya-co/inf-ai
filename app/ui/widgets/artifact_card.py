"""Artifacts + citations (v0.4.0 UI pack, Flet-only, MIT).

Ports flutter_gen_ai_chat_ui ChatMessage.rich() + LibreChat artifacts
ideas: fenced ```table / ```chart / ```card / ```json blocks render as
full-width cards below the Markdown; [file §n] citations render as
tappable source cards. Zero-config fallback: unknown content stays text.
"""

from __future__ import annotations

import json
import re

import flet as ft

FENCE_RE = re.compile(r"```[ \t]*(\w+)?[ \t]*\r?\n?(.*?)```", re.DOTALL)
CITE_RE = re.compile(r"\[([^\]]+? §\d+)\]")
KNOWN_ARTIFACT_LANGS = frozenset({"table", "chart", "card", "json"})


def extract_artifacts(text: str) -> list[tuple[str, str]]:
    """Return [(lang, body)] for known artifact fences in order.

    Tolerant: language may be upper-case, may have trailing spaces, and
    the body may start on the same line (```json {...}```) — the old
    regex required a newline and silently dropped those replies.
    """
    out: list[tuple[str, str]] = []
    for m in FENCE_RE.finditer(text or ""):
        lang = (m.group(1) or "").strip().lower()
        if lang in KNOWN_ARTIFACT_LANGS:
            body = (m.group(2) or "").strip()
            # Strip a leading language echo like "json\n{...}" when the
            # fence had no newline (body starts with the lang itself).
            if body.lower().startswith(lang + "\n"):
                body = body[len(lang) + 1:].strip()
            if body:
                out.append((lang, body))
    return out[:3]  # cap: max 3 inline artifacts per reply


def extract_citations(text: str) -> list[str]:
    """Return ordered unique [file §n] citation labels."""
    seen: list[str] = []
    for m in CITE_RE.finditer(text or ""):
        label = m.group(1).strip()
        if label not in seen:
            seen.append(label)
    return seen[:8]


def _table_card(body: str) -> ft.Control:
    rows: list[ft.DataRow] = []
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    # Support markdown tables (| a | b |) and CSV-ish lines.
    cells_grid: list[list[str]] = []
    for ln in lines:
        if set(ln) <= set("|-: "):
            continue
        cells_grid.append([c.strip() for c in ln.strip("|").split("|")])
    if not cells_grid:
        return ft.Text(body[:1000], size=12, selectable=True)
    header, *data = cells_grid
    cols = [ft.DataColumn(ft.Text(h[:24], size=12, weight=ft.FontWeight.BOLD)) for h in header]
    for r in data[:12]:
        padded = (r + [""] * len(header))[: len(header)]
        rows.append(ft.DataRow(cells=[ft.DataCell(ft.Text(c[:40], size=12)) for c in padded]))
    return ft.Container(
        content=ft.Column(
            [ft.DataTable(columns=cols, rows=rows)],
            scroll=ft.ScrollMode.AUTO,
            tight=True,
        ),
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=12,
        padding=8,
    )


def _json_card(body: str) -> ft.Control:
    try:
        parsed = json.loads(body)
        pretty = json.dumps(parsed, indent=2, ensure_ascii=False)[:2000]
    except Exception:
        pretty = body[:2000]
    return ft.Container(
        content=ft.Text(pretty, size=11, selectable=True, font_family="monospace"),
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=12,
        padding=8,
        bgcolor=ft.Colors.with_opacity(0.04, ft.Colors.ON_SURFACE),
    )


def artifact_control(lang: str, body: str) -> ft.Control:
    """Build one inline artifact card with title + body."""
    title = {"table": "Table", "chart": "Data", "card": "Card", "json": "JSON"}.get(lang, lang.title())
    inner: ft.Control
    if lang == "table":
        inner = _table_card(body)
    elif lang in ("json", "chart", "card"):
        inner = _json_card(body)
    else:
        inner = ft.Text(body[:2000], size=12, selectable=True)
    return ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    [ft.Icon(ft.Icons.DASHBOARD_OUTLINED, size=14), ft.Text(title, size=12, weight=ft.FontWeight.BOLD)],
                    spacing=6,
                    tight=True,
                ),
                inner,
            ],
            spacing=6,
            tight=True,
        ),
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=12,
        padding=8,
    )


def citation_card(label: str, excerpt: str = "", on_tap=None) -> ft.Container:
    """Tappable source card for a [file §n] citation.

    ``on_tap`` receives the click event (v0.5 R4 opens the source viewer);
    without it the card is a static label as before.
    """
    return ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.DESCRIPTION_OUTLINED, size=14),
                ft.Column(
                    [
                        ft.Text(label, size=12, weight=ft.FontWeight.BOLD,
                                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Text(excerpt[:160] if excerpt else "Tap to view source in history.",
                                size=11, color=ft.Colors.ON_SURFACE_VARIANT,
                                max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                    ],
                    spacing=0,
                    tight=True,
                    expand=True,
                ),
            ],
            spacing=8,
            tight=True,
        ),
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=10,
        padding=8,
        on_click=on_tap,
        tooltip="View source excerpt" if on_tap else None,
    )
