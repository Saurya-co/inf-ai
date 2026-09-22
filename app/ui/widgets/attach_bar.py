"""Attachment chips with image thumbnails (offline, built-ins only)."""

from __future__ import annotations

from typing import Callable

import flet as ft

from app.core.types import Attachment
from app.ui.phosphor import ph


def _thumb(att: Attachment) -> ft.Control:
    if att.data_url:
        try:
            return ft.Container(
                content=ft.Image(
                    src=att.data_url,
                    width=40,
                    height=40,
                    fit=ft.BoxFit.COVER,
                    border_radius=8,
                ),
                border_radius=8,
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
            )
        except Exception:
            pass
        return ph("image", 16)
    return ph("file-text", 16)


def build_attachment_chip(
    att: Attachment, index: int, on_remove: Callable
) -> ft.Container:
    label = f"{att.name} ({max(att.size, 1) // 1024}KB)"
    row_items: list[ft.Control] = [
        _thumb(att),
        ft.Text(label, size=12, expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
    ]
    if att.extra.get("truncated"):
        row_items.append(ph("scissors", 12, tooltip="Truncated to fit context"))
    row_items.append(
        ft.IconButton(
            icon=ft.Icons.CLOSE,
            tooltip="Remove",
            icon_size=16,
            style=ft.ButtonStyle(padding=6),
            data=index,
            on_click=on_remove,
        )
    )
    return ft.Container(
        content=ft.Row(row_items, spacing=8, tight=True),
        border=ft.Border.all(1, ft.Colors.OUTLINE),
        border_radius=12,
        padding=ft.padding.Padding(left=8, top=4, right=4, bottom=4),
        width=340,
    )
