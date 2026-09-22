"""Model capability detail bottom sheet (ChatGPT-like model info)."""

from __future__ import annotations

import flet as ft

from app.config import PROVIDERS, get_model_metadata

# Flet >=0.86 removed padding.symmetric/all helpers — build Padding directly.
def _pad(h: int, v: int) -> ft.padding.Padding:
    return ft.padding.Padding(left=h, top=v, right=h, bottom=v)

def _pad_only(left: int = 0, top: int = 0, right: int = 0, bottom: int = 0) -> ft.padding.Padding:
    return ft.padding.Padding(left=left, top=top, right=right, bottom=bottom)


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
    "image": "Image output",
    "function_calling": "Function Calling",
    "json_mode": "JSON Mode",
    "reasoning": "Reasoning",
    "code_execution": "Code Execution",
    "code_specialist": "Code Specialist",
    "long_context": "Long Context",
}


def _format_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n // 1_000_000}M"
    if n >= 1_000:
        return f"{n // 1_000}K"
    return str(n)


def _close_sheet(sheet: ft.BottomSheet) -> None:
    """Close + detach (fresh sheets are appended per open — no overlay leak)."""
    try:
        sheet.open = False
        pg = getattr(sheet, "page", None)
        if pg is not None:
            try:
                pg.overlay.remove(sheet)
            except Exception:
                pass
            pg.update()
    except Exception:
        pass


def build_model_detail_sheet(
    provider_id: str,
    model: str,
    on_select: callable | None = None,
    on_compare: callable | None = None,
) -> ft.BottomSheet:
    """Build a bottom sheet showing detailed model capabilities."""
    reg = PROVIDERS.get(provider_id, {})
    meta = get_model_metadata(provider_id, model)
    display_name = reg.get("display_name", provider_id)
    is_free = reg.get("free", False)

    # Capability chips
    capability_chips: list[ft.Control] = []
    for cap in meta.get("capabilities", []):
        icon_path = CAPABILITY_ICONS.get(cap)
        label = CAPABILITY_LABELS.get(cap, cap.replace("_", " ").title())
        if icon_path:
            capability_chips.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Image(src=icon_path, width=16, height=16),
                            ft.Text(label, size=12),
                        ],
                        spacing=6,
                        tight=True,
                    ),
                    padding=_pad(10, 6),
                    border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                    border_radius=20,
                )
            )
        else:
            capability_chips.append(
                ft.Chip(label=ft.Text(label, size=12), padding=_pad(8, 4))
            )

    # Specs grid
    specs = [
        ("Context Window", _format_tokens(meta.get("context_window", 0))),
        ("Max Output", _format_tokens(meta.get("max_output", 0))),
        ("Knowledge Cutoff", meta.get("knowledge_cutoff", "unknown")),
        ("Pricing", meta.get("pricing_tier", "unknown").title()),
    ]

    spec_rows: list[ft.Control] = []
    for label, value in specs:
        spec_rows.append(
            ft.Row(
                [
                    ft.Text(label, size=12, color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
                    ft.Text(value, size=12, weight=ft.FontWeight.W_500),
                ],
                spacing=12,
            )
        )

    # Actions
    actions: list[ft.Control] = []
    if on_compare:
        actions.append(
            ft.TextButton(
                content=ft.Text("Compare"),
                on_click=lambda _: (on_compare(provider_id, model), _close_sheet(sheet)),
            )
        )
    if on_select:
        actions.append(
            ft.FilledButton(
                content=ft.Text("Select"),
                on_click=lambda _: (on_select(provider_id, model), _close_sheet(sheet)),
            )
        )
    actions.append(
        ft.TextButton(
            content=ft.Text("Close"),
            on_click=lambda _: _close_sheet(sheet),
        )
    )

    sheet = ft.BottomSheet(
        content=ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text(model, weight=ft.FontWeight.BOLD, size=16, expand=True),
                            ft.Container(
                                content=ft.Row(
                                    [
                                        ft.Text(display_name, size=11),
                                        ft.Container(
                                            content=ft.Text("FREE", size=10, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN),
                                            padding=_pad(6, 2),
                                            bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.GREEN),
                                            border_radius=4,
                                        ) if is_free else ft.Container(),
                                    ],
                                    spacing=8,
                                    tight=True,
                                ),
                                padding=_pad_only(right=8),
                            ),
                            ft.IconButton(icon=ft.Icons.CLOSE, icon_size=20, on_click=lambda _: _close_sheet(sheet)),
                        ],
                    ),
                    ft.Divider(height=1),
                    ft.Text("Capabilities", size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Container(
                        content=ft.Row(capability_chips, spacing=8, wrap=True, tight=True),
                        padding=_pad_only(top=4, bottom=8),
                    ),
                    ft.Divider(height=1),
                    ft.Text("Specifications", size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Container(
                        content=ft.Column(spec_rows, spacing=10, tight=True),
                        padding=_pad_only(top=8, bottom=8),
                    ),
                    ft.Divider(height=1),
                    ft.Row(actions, alignment=ft.MainAxisAlignment.END, spacing=8, tight=True),
                ],
                spacing=0,
                tight=True,
            ),
            padding=16,
        ),
        show_drag_handle=True,
    )
    return sheet