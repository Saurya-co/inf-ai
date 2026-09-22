"""Starter cards (v0.4.0 UI pack, Flet-only, MIT).

LibreChat-inspired homepage starters: configurable cards bound to an
optional provider/model or a plain prompt. Stored via KeyStore so
deployments can brand without code changes (config-driven theming lite).
"""

from __future__ import annotations

from dataclasses import dataclass

import flet as ft

DEFAULT_STARTERS: list[dict] = [
    {"icon": "sparkle", "title": "Explain simply", "prompt": "Explain this topic in simple steps with one example", "provider": "", "model": ""},
    {"icon": "code", "title": "Solve step-by-step", "prompt": "Solve this maths/science problem step by step and check the answer", "provider": "", "model": ""},
    {"icon": "doc", "title": "Summarise chapter", "prompt": "Summarise my pasted notes into key points + 3 likely exam questions", "provider": "", "model": ""},
    {"icon": "quiz", "title": "Quiz me", "prompt": "Quiz me on this topic — ask one question at a time and give feedback", "provider": "", "model": ""},
    {"icon": "mail", "title": "Essay outline", "prompt": "Make an outline for my essay/assignment on this topic", "provider": "", "model": ""},
    {"icon": "plan", "title": "Study plan", "prompt": "Make a 7-day study plan for my exam with daily tasks", "provider": "", "model": ""},
]


@dataclass(frozen=True)
class Starter:
    icon: str
    title: str
    prompt: str
    provider: str = ""
    model: str = ""


def coerce_starters(raw: object) -> list[Starter]:
    if not isinstance(raw, list):
        return [Starter(**d) for d in DEFAULT_STARTERS]
    out: list[Starter] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()[:40]
        prompt = str(item.get("prompt", "")).strip()[:300]
        if not title or not prompt:
            continue
        out.append(
            Starter(
                icon=str(item.get("icon", "sparkle"))[:20],
                title=title,
                prompt=prompt,
                provider=str(item.get("provider", ""))[:40],
                model=str(item.get("model", ""))[:80],
            )
        )
    return out[:8] or [Starter(**d) for d in DEFAULT_STARTERS]


def starter_grid(
    starters: list[Starter], on_pick, on_use_model=None
) -> ft.Row:
    """2x2-ish wrapping grid of starter cards."""
    cards: list[ft.Control] = []
    for s in starters:
        async def _noop(_e, _s=s):
            pass
        cards.append(
            ft.Container(
                content=ft.Column(
                    [
                        ft.Text(s.title, size=13, weight=ft.FontWeight.BOLD,
                                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Text(s.prompt, size=11, color=ft.Colors.ON_SURFACE_VARIANT,
                                max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                    ],
                    spacing=2,
                    tight=True,
                ),
                border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                border_radius=12,
                padding=10,
                width=220,
                on_click=lambda e, _s=s: on_pick(_s),
                tooltip=f"Start: {s.prompt[:60]}",
            )
        )
    return ft.Row(cards, wrap=True, spacing=8, run_spacing=8,
                  alignment=ft.MainAxisAlignment.CENTER)
