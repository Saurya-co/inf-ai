"""Token/cost metering helpers (v0.5 R7, Flet-only, MIT).

Pure logic for per-conversation token totals and the context-window
meter. Estimates only (len//4 via chat_service) — always displayed
with "~", never currency. Unit-tested; thin Flet wiring lives in main.py.
"""

from __future__ import annotations

from app.config import context_limit
from app.core.chat_service import message_tokens

# Meter bands as fractions of the model's context limit.
METER_WARN_AT = 0.7
METER_CRITICAL_AT = 0.9


def format_tokens(n: int | float) -> str:
    """Compact estimate label: 950 → '~950', 12_300 → '~12.3k'."""
    try:
        n = int(n)
    except Exception:
        return "~0"
    if n < 0:
        n = 0
    if n < 1000:
        return f"~{n}"
    if n < 1_000_000:
        v = n / 1000
        return f"~{v:.1f}k".replace(".0k", "k")
    return f"~{n / 1_000_000:.1f}M".replace(".0M", "M")


def conversation_tokens(conv: dict) -> int:
    """Total (in + out) tokens recorded for a conversation row."""
    try:
        return max(0, int(conv.get("input_tokens", 0))) + max(0, int(conv.get("output_tokens", 0)))
    except Exception:
        return 0


def meter_band(used: int, limit: int) -> str:
    """'ok' | 'warn' | 'critical' for used/limit context usage."""
    try:
        limit = int(limit)
        used = int(used)
    except Exception:
        return "ok"
    if limit <= 0:
        return "ok"
    frac = used / limit
    if frac >= METER_CRITICAL_AT:
        return "critical"
    if frac >= METER_WARN_AT:
        return "warn"
    return "ok"


def meter_label(used: int, limit: int) -> str:
    """'~3.2k/131k • 2%' style label for the context meter."""
    try:
        pct = int(round(100 * int(used) / int(limit))) if int(limit) > 0 else 0
    except Exception:
        pct = 0
    return f"{format_tokens(used)}/{format_tokens(limit)} • {pct}%"


def context_used(messages: list) -> int:
    """Sum estimated tokens over live history (context pressure)."""
    total = 0
    for m in messages or []:
        try:
            total += message_tokens(m)
        except Exception:
            pass
    return total


def context_limit_for(model: str) -> int:
    try:
        return int(context_limit(model or ""))
    except Exception:
        return 8192
