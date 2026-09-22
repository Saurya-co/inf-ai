"""Streaming bubble helpers (v0.4.0 UI pack, Flet-only).

MIT — our own code. UX inspired by flutter_gen_ai_chat_ui (MIT) and
LibreChat (MIT): no vendored code, patterns re-implemented with Flet
built-ins (Apache-2.0).

Pure helpers here are unit-tested (see tests/test_v040_ui.py); thin
Flet builders live alongside so main.py stays small.
"""

from __future__ import annotations

import flet as ft

STREAM_CURSOR = "▍"


def is_code_fence_open(text: str) -> bool:
    """True when an odd number of ``` fences are open (partial code block)."""
    return text.count("```") % 2 == 1


def split_stream_safe(text: str) -> tuple[str, str]:
    """Split streamed markdown into (safe_to_render, buffered_tail).

    While a fence/code block is incomplete we hold back from the last
    fence opener so the renderer never shows a half-open block. Callers
    render ``safe`` and keep ``tail`` until the fence closes.
    """
    if is_code_fence_open(text):
        idx = text.rfind("```")
        return text[:idx], text[idx:]
    # Hold back a trailing half-open bold/italic marker (**, *, `) — tiny
    # anti-flicker port of the flutter_gen_ai_chat_ui buffering idea.
    for marker in ("**", "__", "`"):
        if text.endswith(marker) and text.count(marker) % 2 == 1:
            return text[: -len(marker)], text[-len(marker):]
    return text, ""


def detect_text_direction(text: str) -> str:
    """Return 'rtl' when the text is predominantly RTL script, else 'ltr'.

    Heuristic: any Hebrew/Arabic/Persian/Urdu block char present →
    check ratio; >30% RTL chars means rtl. Keeps mixed threads readable
    without per-message config (flutter_gen_ai_chat_ui RTL idea).
    """
    if not text:
        return "ltr"
    rtl = sum(1 for ch in text if "\u0590" <= ch <= "\u08FF" or "\uFB50" <= ch <= "\uFDFF" or "\uFE70" <= ch <= "\uFEFF")
    letters = sum(1 for ch in text if ch.isalpha())
    if letters and rtl / max(letters, 1) > 0.3:
        return "rtl"
    return "ltr"


def typing_indicator() -> ft.Row:
    """Three-dot typing row shown before the first token arrives."""
    return ft.Row(
        [
            ft.ProgressRing(width=14, height=14, stroke_width=2),
            ft.Text("Thinking…", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
        ],
        spacing=8,
        tight=True,
    )


def shimmer_placeholder(label: str = "Generating…") -> ft.Container:
    """Shimmer-style loading card that morphs into the final bubble."""
    return ft.Container(
        content=ft.Row(
            [
                ft.ProgressRing(width=14, height=14, stroke_width=2),
                ft.Text(label, size=12, color=ft.Colors.ON_SURFACE_VARIANT),
            ],
            spacing=8,
            tight=True,
        ),
        padding=10,
        border_radius=12,
        bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.ON_SURFACE),
    )


def streaming_text(value: str, done: bool = False) -> str:
    """Append/remove the block cursor for live updates."""
    if done:
        return value
    return f"{value}{STREAM_CURSOR}"


class StreamingBubble(ft.Row):
    """Isolated streaming row (v0.5 R1, Flet-only).

    Same visual structure as ``assistant_bubble`` (built by grafting it,
    so styling can never drift), but live token flushes call
    ``self.update()`` — updating only this control instead of the whole
    page. Every method degrades gracefully: ``set_stream_text()`` returns
    False when an isolated update is unavailable and the caller must fall
    back to ``page.update()``.
    """

    def __init__(self, md_factory, timestamp: str | None = None) -> None:
        super().__init__(
            alignment=ft.MainAxisAlignment.START,
            vertical_alignment=ft.CrossAxisAlignment.START,
            spacing=0,
        )
        from app.ui.widgets.message_bubble import assistant_bubble

        md = md_factory()
        row = assistant_bubble(md, timestamp=timestamp)
        self.controls = list(row.controls)
        self.data = row.data
        self.md = md

    def set_stream_text(self, value: str) -> bool:
        """Set live text; True when an isolated update succeeded."""
        if not isinstance(value, str):
            try:
                value = str(value)
            except Exception:
                return False
        # Cap live-render length: full-reply Markdown re-parse per frame.
        if len(value) > 100_000:
            value = value[:100_000]
        try:
            self.md.value = value
        except Exception:
            return False
        # Only isolated-update when actually mounted; otherwise the
        # exception path forces a full page.update() per frame (jank).
        try:
            if getattr(self, "page", None) is None:
                return False
            self.update()
            return True
        except Exception:
            return False
