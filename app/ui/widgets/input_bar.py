"""Input-bar helpers (v0.4.0 UI pack, Flet-only, MIT).

Ports flutter_gen_ai_chat_ui input ideas (send/stop morph, attachment
preview strip, lightbox, safe-area input) to Flet built-ins.
Pure state helpers are tested; Flet builders are thin.
"""

from __future__ import annotations

from dataclasses import dataclass

import flet as ft


@dataclass(frozen=True)
class InputState:
    streaming: bool
    has_text: bool
    has_attachments: bool


# v0.4 refinement: per-file attach states (reading → ready | too-large | failed).
ATTACH_STATUSES: tuple[str, ...] = ("reading", "ready", "too-large", "failed")


@dataclass(frozen=True)
class AttachmentState:
    name: str
    size: int
    status: str = "ready"
    detail: str = ""


def attach_status_line(st: AttachmentState) -> str:
    """Human-readable status line for a staged file."""
    kb = max(st.size, 1) // 1024
    base = f"{st.name} ({kb}KB)"
    if st.status == "reading":
        return f"{base} • reading…"
    if st.status == "too-large":
        return f"{base} • too large — will truncate"
    if st.status == "failed":
        return f"{base} • failed: {st.detail or 'unreadable'}"
    return base


def is_attach_blocked(st: AttachmentState) -> bool:
    return st.status == "failed"


def send_button_mode(state: InputState) -> tuple[str, str]:
    """Return (icon_name, tooltip) for the send/stop/mic button.

    - streaming → STOP (prominent, saves cost)
    - else if text/attachments → SEND
    - else → MIC placeholder (voice deferred; tap explains)
    """
    if state.streaming:
        return ("STOP", "Stop generating")
    if state.has_text or state.has_attachments:
        return ("SEND", "Send")
    return ("MIC", "Voice input (coming soon)")


def preview_label(name: str, size: int) -> str:
    kb = max(size, 1) // 1024
    base = name if len(name) <= 28 else name[:25] + "…"
    return f"{base} ({kb}KB)"


def build_preview_strip(
    items: list[tuple[str, str | None, int]],
    on_remove,
    on_preview,
) -> ft.Row:
    """Horizontal preview strip above the input (thumb + label + remove).

    items: list of (name, data_url_or_None, size_bytes).
    on_remove/on_preview receive the item index via control.data.
    """
    controls: list[ft.Control] = []
    for i, (name, data_url, size) in enumerate(items):
        thumb: ft.Control
        if data_url:
            thumb = ft.Image(
                src=data_url, width=40, height=40, fit=ft.BoxFit.COVER,
                border_radius=8, tooltip=f"Preview {name}",
            )
        else:
            thumb = ft.Icon(ft.Icons.DESCRIPTION_OUTLINED, size=20)
        controls.append(
            ft.Container(
                content=ft.Row(
                    [
                        ft.Container(
                            content=thumb, on_click=on_preview, data=i,
                            tooltip=f"Preview {name}",
                        ),
                        ft.Text(
                            preview_label(name, size), size=11, expand=True,
                            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.CLOSE, tooltip="Remove",
                            icon_size=14, data=i, on_click=on_remove,
                            style=ft.ButtonStyle(padding=4),
                        ),
                    ],
                    spacing=6,
                    tight=True,
                ),
                border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                border_radius=10,
                padding=6,
                width=260,
            )
        )
    return ft.Row(controls, spacing=8, tight=True, scroll=ft.ScrollMode.AUTO)


def build_lightbox(title: str, image_src: str | None, body: str = "") -> ft.AlertDialog:
    """Image/doc lightbox dialog (zoomable image via InteractiveViewer)."""
    content: ft.Control
    if image_src:
        try:
            viewer = ft.InteractiveViewer(
                content=ft.Image(src=image_src, fit=ft.BoxFit.CONTAIN, height=340),
                min_scale=0.5,
                max_scale=4.0,
            )
        except Exception:
            viewer = ft.Image(src=image_src, fit=ft.BoxFit.CONTAIN, height=320)
        content = ft.Column(
            [
                viewer,
                ft.Text(body[:500] if body else title, size=12, selectable=True),
            ],
            spacing=8,
            tight=True,
            scroll=ft.ScrollMode.AUTO,
        )
    else:
        content = ft.Column(
            [
                ft.Text(body[:2000] or title, size=12, selectable=True),
            ],
            spacing=8,
            tight=True,
            scroll=ft.ScrollMode.AUTO,
        )
    return ft.AlertDialog(
        modal=False,
        title=ft.Text(title, size=14, weight=ft.FontWeight.BOLD,
                      max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
        content=ft.Container(content=content, width=340, height=400),
    )
