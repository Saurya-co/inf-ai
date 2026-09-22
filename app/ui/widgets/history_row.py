"""History inbox helpers (v0.4.0 UI pack + refinement, Flet-only, MIT).

Ports flutter_chat_kits ChatInbox + LibreChat session-list ideas:
date-grouped rows, preview line, unread dot, pins/favorites, archive,
in-drawer bulk-select mode, provider/pinned filters.
Pure grouping/filter helpers are tested; builders are thin.
"""

from __future__ import annotations

import datetime as _dt

import flet as ft

HISTORY_FILTERS: tuple[str, ...] = ("all", "pinned", "archived")


def apply_history_filter(convs: list[dict], filt: str, provider: str = "") -> list[dict]:
    """Filter conv dicts by pinned/archived tab + provider chip."""
    f = (filt or "all").lower()
    out = []
    for c in convs or []:
        if f == "pinned" and not c.get("pinned"):
            continue
        if f == "archived" and not c.get("archived"):
            continue
        if f == "all" and c.get("archived"):
            continue  # archived hidden from All tab
        if provider and str(c.get("provider", "")) != provider:
            continue
        out.append(c)
    return out


def empty_history_message(filt: str, query: str) -> str:
    if (query or "").strip():
        return "No matches — try a different search."
    if filt == "pinned":
        return "No pinned chats — pin one from ⋮."
    if filt == "archived":
        return "Nothing archived."
    return "No study chats yet — ask your first question!"


def group_label(updated_at: str, today: _dt.date | None = None) -> str:
    """Bucket an ISO-ish updated_at string into a section label."""
    today = today or _dt.date.today()
    try:
        day = _dt.datetime.fromisoformat(str(updated_at)[:19]).date()
    except Exception:
        return "Older"
    delta = (today - day).days
    if delta <= 0:
        return "Today"
    if delta == 1:
        return "Yesterday"
    if delta <= 7:
        return "Previous 7 days"
    return "Older"


def group_conversations(
    convs: list[dict], today: _dt.date | None = None
) -> list[tuple[str, list[dict]]]:
    """Group conv dicts preserving order within 4 fixed buckets."""
    buckets: dict[str, list[dict]] = {
        "Today": [],
        "Yesterday": [],
        "Previous 7 days": [],
        "Older": [],
    }
    for c in convs:
        buckets[group_label(c.get("updated_at", ""), today)].append(c)
    return [(k, v) for k, v in buckets.items() if v]


def preview_of(title: str, provider: str, model: str) -> str:
    sub = f"{provider} / {model}".strip(" /")
    return sub[:60]


def history_subtitle(conv: dict) -> str:
    """Drawer subtitle: 'provider / model • ~12.3k tok' (v0.5 R7 metering)."""
    base = preview_of(conv.get("title") or "", conv.get("provider", ""), conv.get("model", ""))
    try:
        total = max(0, int(conv.get("input_tokens", 0))) + max(0, int(conv.get("output_tokens", 0)))
    except Exception:
        total = 0
    if total <= 0:
        return base
    try:
        from app.ui.controllers.metering import format_tokens
        suffix = f" • {format_tokens(total)} tok"
    except Exception:
        suffix = f" • ~{total} tok"
    return (base + suffix)[:80]


def inbox_tile(
    conv: dict,
    selected: bool,
    on_open,
    on_rename,
    on_delete,
    unread: bool = False,
    on_pin=None,
    on_archive=None,
    bulk_mode: bool = False,
    bulk_checked: bool = False,
    on_bulk=None,
) -> ft.Container:
    """ChatInbox-style row: unread dot + title + preview + popup actions.

    Bulk mode swaps the leading icon for a Checkbox (in-drawer multi-select).
    """
    cid = conv.get("id")
    title = conv.get("title") or "New chat"
    sub = history_subtitle(conv)
    pinned = bool(conv.get("pinned"))
    archived = bool(conv.get("archived"))
    if bulk_mode:
        leading: ft.Control = ft.Checkbox(value=bulk_checked, data=cid, on_change=on_bulk)
    else:
        leading = ft.Row(
            [
                ft.Container(
                    width=8, height=8, border_radius=4,
                    bgcolor=ft.Colors.PRIMARY if unread else ft.Colors.TRANSPARENT,
                ),
                ft.Icon(ft.Icons.FORUM_OUTLINED, size=20),
            ],
            spacing=6,
            tight=True,
        )
    menu_items: list[ft.Control] = [
        ft.PopupMenuItem(icon=ft.Icons.EDIT_OUTLINED, content=ft.Text("Rename"),
                         data=cid, on_click=on_rename),
        ft.PopupMenuItem(icon=ft.Icons.DELETE_OUTLINE, content=ft.Text("Delete"),
                         data=cid, on_click=on_delete),
    ]
    if on_pin is not None:
        menu_items.insert(1, ft.PopupMenuItem(
            icon=ft.Icons.PUSH_PIN if not pinned else ft.Icons.PUSH_PIN_OUTLINED,
            content=ft.Text("Unpin" if pinned else "Pin"), data=cid, on_click=on_pin))
    if on_archive is not None:
        menu_items.insert(2, ft.PopupMenuItem(
            icon=ft.Icons.UNARCHIVE if archived else ft.Icons.ARCHIVE_OUTLINED,
            content=ft.Text("Unarchive" if archived else "Archive"), data=cid, on_click=on_archive))
    title_row = ft.Row(
        [
            ft.Text(title, size=13, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True),
            ft.Icon(ft.Icons.PUSH_PIN, size=12) if pinned else ft.Container(),
        ],
        spacing=4,
        tight=True,
    )
    return ft.Container(
        content=ft.ListTile(
            leading=leading,
            title=title_row,
            subtitle=ft.Text(sub, size=11, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
            trailing=ft.PopupMenuButton(
                icon=ft.Icons.MORE_VERT,
                tooltip="Chat actions",
                items=menu_items,
            ),
            selected=selected,
            data=cid,
            on_click=on_open,
        ),
        border_radius=10,
        bgcolor=ft.Colors.with_opacity(0.06, ft.Colors.PRIMARY) if selected else None,
    )
