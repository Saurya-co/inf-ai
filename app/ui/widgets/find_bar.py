"""Find-in-chat helpers (v0.5 R6, Flet-only, MIT).

Pure match-index / navigation logic is unit-tested; the bar itself is
thin Flet built in main.py. Navigation scrolls the ListView to the
matching message row via control keys (``msg-{history_index}``); the
current match gets a highlight ring on its bubble container.
"""

from __future__ import annotations

import flet as ft


def row_key(idx: object) -> str:
    """Control key for the rendered row of history message ``idx``."""
    try:
        return f"msg-{int(idx)}"  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "msg-0"


def build_match_index(texts: object, query: object) -> list[int]:
    """Return history indices whose text contains ``query`` (case-insensitive)."""
    if not isinstance(query, str):
        return []
    q = query.casefold().strip()[:200]
    if not q:
        return []
    if not isinstance(texts, list):
        return []
    out: list[int] = []
    for i, t in enumerate(texts):
        if not isinstance(t, str):
            continue
        if q in t.casefold():
            out.append(i)
    return out[:1000]


def format_counter(pos: object, total: object) -> str:
    """'3/12' style counter; '0/0' when no matches."""
    try:
        t = int(total)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "0/0"
    if t <= 0:
        return "0/0"
    try:
        p = int(pos)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        p = 0
    p = max(0, min(t - 1, p))
    return f"{p + 1}/{t}"


def step_index(pos: object, delta: object, total: object) -> int:
    """Move selection with wrap-around; 0 when empty."""
    try:
        t = int(total)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    if t <= 0:
        return 0
    try:
        p = int(pos)  # type: ignore[arg-type]
        d = int(delta)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return (p + d) % t


def set_row_highlight(row: ft.Control, on: bool) -> bool:
    """Toggle a highlight ring on a message row's bubble container.

    Works structurally: user rows are Row[spacer, bubble], assistant rows
    are Row[body]. Anything else (system rows, headers) is skipped.
    Returns True when a ring was applied or cleared.
    """
    try:
        if not isinstance(row, ft.Row) or not row.controls:
            return False
        target = row.controls[-1]
        if not isinstance(target, ft.Container):
            return False
        if on:
            target.border = ft.Border.all(2, ft.Colors.PRIMARY)
        else:
            target.border = None
        # Best-effort live refresh: unmounted rows (unit tests, offscreen)
        # still count as highlighted — the border is set above and renders
        # on next mount. A failed update must not flip the result to False.
        try:
            if getattr(row, "page", None) is not None:
                row.update()
        except Exception:
            pass
        return True
    except Exception:
        return False
