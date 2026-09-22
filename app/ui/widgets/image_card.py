"""Generated-image card (v0.6 image output, Flet-only).

Renders a model-produced PNG (bytes or a file under data/generated/) with
caption + Save/Copy actions. The persisted history note is plain text
(``image_note``) so the DB stays small; on reload the card is rebuilt from
the saved file when it still exists, otherwise the note text shows.
"""

from __future__ import annotations

import base64
import os
import re
import time
from typing import Callable

import flet as ft

NOTE_PREFIX = "🖼️ Generated image"
_NOTE_RE = re.compile(
    r"^\U0001f5bc\ufe0f Generated image — \"(?P<prompt>.*)\" \[file: (?P<file>[^\]]+)\]$"
)


def generated_dir() -> str:
    """App-data ``generated/`` dir (created on demand)."""
    try:
        from app.data.paths import app_data_dir

        d = os.path.join(app_data_dir(), "generated")
    except Exception:
        d = os.path.join(os.getcwd(), "data", "generated")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


def save_generated_png(png: bytes, conv_id: int | None) -> str:
    """Write PNG bytes to the generated dir. Returns the filename."""
    cid = int(conv_id) if conv_id is not None else 0
    name = f"img-{cid}-{int(time.time())}.png"
    try:
        with open(os.path.join(generated_dir(), name), "wb") as fh:
            fh.write(bytes(png))
    except OSError:
        pass
    return name


def image_note(prompt: str, filename: str) -> str:
    """Persisted history note for a generated image (plain text)."""
    clean = " ".join((prompt or "").strip().split())[:200]
    return f'{NOTE_PREFIX} — "{clean}" [file: {filename}]'


def parse_image_note(text: str) -> tuple[str, str] | None:
    """Return (prompt, filename) for a persisted image note, else None."""
    try:
        m = _NOTE_RE.match((text or "").strip())
    except Exception:
        return None
    if not m:
        return None
    return m.group("prompt"), m.group("file")


def png_to_b64(png: bytes) -> str:
    return base64.b64encode(bytes(png)).decode("ascii")


def read_generated_b64(filename: str) -> str | None:
    """Base64 of a saved generated file, or None when it is gone."""
    try:
        # Path-traversal guard: history notes are untrusted (tampered DB).
        base = os.path.basename(filename or "")
        if not base or base != filename or "/" in filename or "\\" in filename:
            # Allow only the app's own naming scheme.
            if not re.match(r"^img-\d+-\d+\.png$", base):
                return None
            filename = base
        else:
            if not re.match(r"^img-\d+-\d+\.png$", filename):
                return None
        full = os.path.abspath(os.path.join(generated_dir(), filename))
        if os.path.abspath(generated_dir()) not in os.path.dirname(full) + os.sep and \
           os.path.dirname(full) != os.path.abspath(generated_dir()):
            return None
        with open(full, "rb") as fh:
            data = fh.read(16 * 1024 * 1024 + 1)
            if len(data) > 16 * 1024 * 1024:
                return None
            return png_to_b64(data)
    except (OSError, ValueError):
        return None


def image_card(
    b64: str,
    prompt: str,
    on_save: Callable | None = None,
    on_copy_prompt: Callable | None = None,
    on_preview=None,
) -> ft.Container:
    """Generated-image card: zoomable image + caption + Save/Copy actions."""
    try:
        img = ft.Image(
            src_base64=b64,
            fit=ft.BoxFit.CONTAIN,
            border_radius=12,
            tooltip="Tap to zoom",
        )
    except Exception:
        img = ft.Text("(image unavailable)", size=12)
    actions: list[ft.Control] = []
    if on_save is not None:
        actions.append(
            ft.IconButton(
                icon=ft.Icons.DOWNLOAD,
                tooltip="Save image to device",
                icon_size=16,
                style=ft.ButtonStyle(padding=12),
                on_click=on_save,
            )
        )
    if on_copy_prompt is not None:
        actions.append(
            ft.IconButton(
                icon=ft.Icons.COPY,
                tooltip="Copy prompt",
                icon_size=16,
                style=ft.ButtonStyle(padding=12),
                on_click=on_copy_prompt,
            )
        )
    return ft.Container(
        content=ft.Column(
            [
                ft.Container(
                    content=img,
                    on_click=on_preview,
                    tooltip="Preview — tap to zoom",
                    border_radius=12,
                    clip_behavior=ft.ClipBehavior.HARD_EDGE,
                    bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.ON_SURFACE),
                ),
                ft.Row(
                    [
                        ft.Text(
                            (prompt or "")[:120],
                            size=11,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                            expand=True,
                            max_lines=2,
                            overflow=ft.TextOverflow.ELLIPSIS,
                            selectable=True,
                        ),
                        *actions,
                    ],
                    spacing=2,
                    tight=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ],
            spacing=4,
            tight=True,
        ),
        padding=10,
        border_radius=12,
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
    )
