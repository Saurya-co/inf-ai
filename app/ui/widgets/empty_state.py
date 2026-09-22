"""Empty-state welcome screen with example prompts (ChatGPT-like)."""

from __future__ import annotations

from typing import Callable

import flet as ft

from app.ui.theme import EXAMPLE_PROMPTS
from app.ui.widgets.starter_cards import Starter, coerce_starters, starter_grid


def build_empty_state(
    on_prompt: Callable[[str], None],
    starters: list[Starter] | None = None,
    on_starter=None,
    saved: list | None = None,
    on_saved=None,
) -> ft.Column:
    """Centered welcome: logo + name + tagline + starter cards.

    Phone-first: cards wrap on narrow screens. Falls back to legacy
    EXAMPLE_PROMPTS chips when no starters are configured.
    v0.5 R8: optional Saved section (prompt library) below the grid;
    tapping a saved prompt inserts it (no auto-send) via ``on_saved``.
    """
    if starters is None:
        starters = coerce_starters(None)

    def _pick(s: Starter) -> None:
        if on_starter is not None:
            try:
                on_starter(s)
                return
            except Exception:
                pass
        on_prompt(s.prompt)
    chips: list[ft.Control] = []
    for prompt in EXAMPLE_PROMPTS:
        chips.append(
            ft.Chip(
                label=ft.Text(prompt, size=12, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                on_click=lambda _, p=prompt: on_prompt(p),
            )
        )
    try:
        grid = starter_grid(starters, _pick)
    except Exception:
        grid = ft.Row(chips, wrap=True, spacing=8, run_spacing=8, alignment=ft.MainAxisAlignment.CENTER)
    children: list[ft.Control] = [
        ft.Container(height=12),
        ft.Image(src="icon.png", width=96, height=96, fit=ft.BoxFit.CONTAIN),
        ft.Text("INF ai", size=22, weight=ft.FontWeight.BOLD),
        ft.Text(
            "Your study toolkit.\nExplain, solve, summarise & revise — pick a free model and start.",
            size=13,
            color=ft.Colors.ON_SURFACE_VARIANT,
            text_align=ft.TextAlign.CENTER,
        ),
        ft.Container(height=4),
        grid,
    ]
    # v0.5 R8: Saved prompts section (insert-only, no auto-send).
    try:
        items = [s for s in (saved or []) if getattr(s, "title", "") and getattr(s, "prompt", "")]
    except Exception:
        items = []
    if items and callable(on_saved):
        def _pick_saved(s) -> None:
            try:
                on_saved(s)
            except Exception:
                pass
        try:
            saved_grid = starter_grid(items, _pick_saved)
        except Exception:
            saved_grid = ft.Container()
        children += [
            ft.Text("Saved", size=13, weight=ft.FontWeight.BOLD),
            saved_grid,
        ]
    return ft.Column(
        children,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        alignment=ft.MainAxisAlignment.CENTER,
        expand=True,
        spacing=10,
        scroll=ft.ScrollMode.AUTO,
    )
