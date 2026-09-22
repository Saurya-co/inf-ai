"""Phosphor icons (MIT, phosphor-icons/core, regular weight) as tintable SVGs.

Vendored under assets/phosphor/*.svg so the APK works offline.
Usage: ph("eye", size=14) inside any Row/Container.
"""

import flet as ft

VALID = frozenset(
    {
        "eye", "eye-slash", "file-text", "image", "paperclip", "scissors",
        "seal-check", "mic", "stop-circle", "arrow-down", "thumbs-up",
        "thumbs-down", "pin", "sparkle", "mail", "code", "doc",
    }
)


def ph(
    name: str,
    size: int = 14,
    color: str | None = None,
    tooltip: str | None = None,
) -> ft.Image:
    if name not in VALID:
        raise ValueError(f"Unknown phosphor icon: {name}")
    return ft.Image(
        src=f"phosphor/{name}.svg",
        width=size,
        height=size,
        color=color,
        color_blend_mode=ft.BlendMode.SRC_IN if color else None,
        tooltip=tooltip,
        fit=ft.BoxFit.CONTAIN,
    )
