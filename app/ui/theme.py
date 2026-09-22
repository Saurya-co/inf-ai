"""Shared M3 theme + chat styling constants (Flet built-ins only, APK-safe)."""

from __future__ import annotations

import flet as ft

COLOR_SEED = "indigo"

# Example prompts for the empty state (INF ai student toolkit).
EXAMPLE_PROMPTS: list[str] = [
    "Explain photosynthesis like I'm in Class 10",
    "Solve this maths problem step by step",
    "Summarise my chapter into key points",
    "Quiz me on this topic — 5 questions",
]

# Streaming throttle: max one page.update() per interval while tokens arrive.
STREAM_THROTTLE_MS = 120
STREAM_CURSOR = "▍"

# Badge colors (light/dark agnostic via opacity over semantic colors).
FREE_BADGE_BG = ft.Colors.with_opacity(0.2, ft.Colors.GREEN)
USER_BUBBLE_BG = ft.Colors.with_opacity(0.16, ft.Colors.PRIMARY)
ASSISTANT_BUBBLE_BG = ft.Colors.with_opacity(0.05, ft.Colors.ON_SURFACE)

# v0.4.0 UI pack tokens (Flet-only, M3 seed stays single-source).
STARTER_CARD_WIDTH = 220
ARTIFACT_MAX_PER_REPLY = 3
LIGHTBOX_SIZE = 340

# v0.4 refinement tokens: font scale, OLED, high-contrast, RTL.
FONT_SCALES: dict[str, float] = {"standard": 1.0, "large": 1.15, "xl": 1.3}
OLED_BLACK = "#000000"
TOUCH_MIN = 48  # minimum hit-area target (glyph stays 14, padding makes up the rest)


def ts(base: int | float, scale: str | float = "standard") -> float:
    """Scaled text size: ts(13, 'large') -> 14.95. Unknown scale -> base."""
    try:
        factor = float(scale) if isinstance(scale, (int, float)) else FONT_SCALES.get(str(scale), 1.0)
    except Exception:
        factor = 1.0
    return round(float(base) * factor, 2)


def align_for_direction(direction: str, default_end: bool = False) -> ft.MainAxisAlignment:
    """Mirror Row alignment for RTL threads (bidi support)."""
    is_rtl = str(direction or "").lower() == "rtl"
    if is_rtl:
        return ft.MainAxisAlignment.START if default_end else ft.MainAxisAlignment.END
    return ft.MainAxisAlignment.END if default_end else ft.MainAxisAlignment.START


def accessible_tooltip(base: str, hint: str = "") -> str:
    """Combine label + hint for screen-reader-friendly tooltips."""
    base = (base or "").strip()
    hint = (hint or "").strip()
    return f"{base} — {hint}" if hint else base


def app_theme(oled: bool = False, high_contrast: bool = False) -> ft.Theme:
    """Material 3 theme from a single seed — applied to page.theme.

    oled: true-black surfaces in dark mode. high_contrast: stronger outlines.
    Both are optional and default off (backward compatible).
    """
    _ = high_contrast  # documented for future outline tuning; seed carries contrast today
    theme = ft.Theme(color_scheme_seed=COLOR_SEED)
    if oled:
        try:
            theme.color_scheme = ft.ColorScheme(
                primary="indigo",
                surface=OLED_BLACK,
                background=OLED_BLACK,
            )
        except Exception:
            pass
    return theme


def now_hhmm() -> str:
    import datetime

    return datetime.datetime.now().strftime("%H:%M")
