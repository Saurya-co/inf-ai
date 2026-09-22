"""ChatGPT-like message bubbles (Flet built-ins only).

User: right-aligned, tonal fill, no "You:" prefix.
Assistant: left-aligned, avatar + surface fill, per-bubble copy/retry.
Error: red outline, keeps chat history clean for transient errors (those
go to SnackBar instead).

v0.4 refinement: edit/fork/pin affordances, per-code-block copy data,
token footer, thumbs reason-sheet builders. Pure helpers are unit-tested.
"""

from __future__ import annotations

import re
from typing import Callable

import flet as ft

from app.ui.theme import USER_BUBBLE_BG

# Minimum touch-friendly size for per-bubble action buttons.
ACTION_ICON_SIZE = 16
ACTION_PADDING = 8

# Tier-2 feedback reasons (shown when thumbs-down tapped).
FEEDBACK_REASONS: tuple[str, ...] = (
    "Inaccurate",
    "Irrelevant",
    "Incomplete",
    "Harmful",
)

_FENCE_RE = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)


def parse_code_blocks(text: str) -> list[tuple[str, str]]:
    """Return [(lang, code)] for fenced blocks in order (max 8)."""
    out: list[tuple[str, str]] = []
    for m in _FENCE_RE.finditer(text or ""):
        out.append(((m.group(1) or "code").strip().lower() or "code", m.group(2)))
    return out[:8]


def fork_history(messages: list, idx: int) -> list:
    """Return history truncated after message index idx (fork point).

    Pure helper: works on any sequence (Message objects or dicts).
    Out-of-range idx returns a shallow copy unchanged.
    """
    try:
        i = int(idx)
    except Exception:
        return list(messages)
    if i < 0 or i >= len(messages):
        return list(messages)
    return list(messages[: i + 1])


def token_footer(tokens: int | None, timestamp: str | None = None) -> str:
    """Compact footer: '~N tokens • HH:MM'. Empty parts omitted."""
    parts: list[str] = []
    if tokens is not None:
        try:
            parts.append(f"~{int(tokens)} tokens")
        except Exception:
            pass
    if timestamp:
        parts.append(str(timestamp))
    return " • ".join(parts)


def _meta_row(timestamp: str | None, actions: list[ft.Control]) -> ft.Row:
    items: list[ft.Control] = []
    if timestamp:
        items.append(ft.Text(timestamp, size=10))
    items.extend(actions)
    return ft.Row(items, spacing=2, tight=True)


def user_bubble(
    text: str,
    on_copy: Callable | None = None,
    timestamp: str | None = None,
    on_edit: Callable | None = None,
    on_fork: Callable | None = None,
    pinned: bool = False,
    on_pin: Callable | None = None,
) -> ft.Row:
    actions: list[ft.Control] = []
    if on_copy is not None:
        actions.append(
            ft.IconButton(
                icon=ft.Icons.COPY,
                tooltip="Copy",
                icon_size=16,
                style=ft.ButtonStyle(padding=12),
                on_click=on_copy,
            )
        )
    if on_edit is not None:
        actions.append(
            ft.IconButton(
                icon=ft.Icons.EDIT_OUTLINED,
                tooltip="Edit and resubmit",
                icon_size=16,
                style=ft.ButtonStyle(padding=12),
                on_click=on_edit,
            )
        )
    if on_fork is not None:
        actions.append(
            ft.IconButton(
                icon=ft.Icons.FORK_RIGHT if hasattr(ft.Icons, "FORK_RIGHT") else ft.Icons.BRANCH,
                tooltip="Fork from here",
                icon_size=16,
                style=ft.ButtonStyle(padding=12),
                on_click=on_fork,
            )
        )
    if on_pin is not None:
        actions.append(
            ft.IconButton(
                icon=ft.Icons.PUSH_PIN if pinned else ft.Icons.PUSH_PIN_OUTLINED,
                tooltip="Unpin" if pinned else "Pin",
                icon_size=16,
                style=ft.ButtonStyle(padding=12),
                on_click=on_pin,
            )
        )
    if not actions:
        actions.append(ft.Container())
    bubble = ft.Container(
        content=ft.Column(
            [
                ft.Text(text, selectable=True),
                _meta_row(timestamp, actions),
            ],
            spacing=2,
            tight=True,
        ),
        bgcolor=USER_BUBBLE_BG,
        border_radius=ft.BorderRadius.only(top_left=16, top_right=4, bottom_left=16, bottom_right=16),
        padding=12,
        expand=4,
    )
    # Spacer flex 1 vs bubble flex 4 → bubble caps at ~80% width on phones.
    return ft.Row(
        [ft.Container(expand=1), bubble], alignment=ft.MainAxisAlignment.END
    )


def assistant_bubble(
    md: ft.Markdown,
    on_copy: Callable | None = None,
    on_retry: Callable | None = None,
    timestamp: str | None = None,
    tokens: int | None = None,
) -> ft.Row:
    """ChatGPT-style assistant row: plain full-width Markdown, no tinted bubble.

    Renders the model text verbatim — no background fill so code blocks,
    tables and headings look exactly as the Markdown specifies. The returned
    Row stores its actions Row in ``row.data`` so callers can append
    copy/retry buttons after streaming finishes without fragile indexing.
    """
    actions: list[ft.Control] = []
    if on_copy:
        actions.append(
            ft.IconButton(
                icon=ft.Icons.COPY,
                tooltip="Copy",
                icon_size=16,
                style=ft.ButtonStyle(padding=12),
                on_click=on_copy,
            )
        )
    if on_retry:
        actions.append(
            ft.IconButton(
                icon=ft.Icons.REFRESH,
                tooltip="Retry",
                icon_size=16,
                style=ft.ButtonStyle(padding=12),
                on_click=on_retry,
            )
        )
    actions_row = _meta_row(token_footer(tokens, timestamp) or timestamp, actions)
    # Subtle surface card — groups the reply visually on narrow phone
    # screens while keeping Markdown code/tables faithful (no tint).
    body = ft.Container(
        content=ft.Column([md, actions_row], spacing=4, tight=True),
        padding=10,
        border_radius=12,
        bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.ON_SURFACE),
        expand=True,
    )
    row = ft.Row(
        [body],
        alignment=ft.MainAxisAlignment.START,
        vertical_alignment=ft.CrossAxisAlignment.START,
        spacing=0,
    )
    row.data = actions_row
    return row


def feedback_row(on_good=None, on_bad=None) -> ft.Row:
    """Tier-1 thumbs feedback (always visible, zero friction)."""
    items: list[ft.Control] = []
    if on_good is not None:
        items.append(
            ft.IconButton(
                icon=ft.Icons.THUMB_UP_OUTLINED,
                tooltip="Good response",
                icon_size=16,
                style=ft.ButtonStyle(padding=12),
                on_click=on_good,
            )
        )
    if on_bad is not None:
        items.append(
            ft.IconButton(
                icon=ft.Icons.THUMB_DOWN_OUTLINED,
                tooltip="Bad response — tell us why",
                icon_size=16,
                style=ft.ButtonStyle(padding=12),
                on_click=on_bad,
            )
        )
    row = ft.Row(items, spacing=2, tight=True)
    return row


def code_copy_cards(text: str, on_copy_code) -> list[ft.Control]:
    """Compact per-code-block copy cards rendered under the Markdown.

    ``on_copy_code`` receives the code string via ``control.data``.
    ``ft.Markdown`` cannot inject per-block buttons, so these under-cards
    are the Flet-only workaround (max 8, code truncated at 2000 chars).
    """
    cards: list[ft.Control] = []
    for lang, code in parse_code_blocks(text):
        preview = code.strip().splitlines()
        head = (preview[0][:60] + "…") if preview and len(preview[0]) > 60 else (preview[0] if preview else lang)
        cards.append(
            ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.CODE, size=14),
                        ft.Text(f"{lang} • {head}", size=11, expand=True,
                                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        ft.IconButton(
                            icon=ft.Icons.COPY, tooltip=f"Copy {lang} block",
                            icon_size=16, data=code[:2000],
                            style=ft.ButtonStyle(padding=12),
                            on_click=on_copy_code,
                        ),
                    ],
                    spacing=6,
                    tight=True,
                ),
                border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                border_radius=10,
                padding=6,
            )
        )
    return cards


def build_feedback_sheet(on_submit) -> tuple[ft.BottomSheet, dict]:
    """Tier-2 reason sheet (BottomSheet + RadioGroup + note field).

    Returns (sheet, refs) where refs holds the radiogroup + note field so
    the caller can read the selection in ``on_submit``.
    """
    group = ft.RadioGroup(
        content=ft.Column(
            [ft.Radio(value=r, label=r) for r in FEEDBACK_REASONS],
            spacing=2,
            tight=True,
        ),
        value=FEEDBACK_REASONS[0],
    )
    note = ft.TextField(label="Tell us more (optional)", dense=True, max_length=300)
    refs = {"group": group, "note": note}
    sheet = ft.BottomSheet(
        content=ft.Container(
            content=ft.Column(
                [
                    ft.Text("What was wrong?", weight=ft.FontWeight.BOLD, size=14),
                    group,
                    note,
                    ft.Row(
                        [
                            ft.TextButton(content=ft.Text("Cancel"),
                                          on_click=lambda _: _close_sheet(refs, sheet)),
                            ft.FilledButton(content=ft.Text("Send"),
                                            on_click=lambda _: on_submit(refs, sheet)),
                        ],
                        alignment=ft.MainAxisAlignment.END,
                        tight=True,
                    ),
                ],
                spacing=8,
                tight=True,
            ),
            padding=16,
        ),
        show_drag_handle=True,
    )
    return sheet, refs


def _close_sheet(refs: dict, sheet: ft.BottomSheet) -> None:
    try:
        sheet.open = False
        pg = getattr(sheet, "page", None)
        if pg is not None:
            pg.update()
    except Exception:
        pass


def error_bubble(text: str) -> ft.Row:
    bubble = ft.Container(
        content=ft.Row(
            [ft.Icon(ft.Icons.ERROR_OUTLINE, size=16, color=ft.Colors.RED), ft.Text(text, color=ft.Colors.RED, selectable=True, expand=True)],
            spacing=8,
            tight=True,
        ),
        border=ft.Border.all(1, ft.Colors.RED),
        border_radius=12,
        padding=10,
        expand=True,
    )
    return ft.Row([bubble], alignment=ft.MainAxisAlignment.START)
