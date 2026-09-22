"""Streaming + history-window controllers (v0.5 R0/R1, Flet-only, MIT).

R0 extract-then-extend: pure, UI-agnostic streaming orchestration logic
moved out of main.py closures so it is unit-testable. The async provider
loop stays in main.py; everything decidable without Flet lives here.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.ui.theme import STREAM_CURSOR, STREAM_THROTTLE_MS
from app.ui.widgets.streaming_bubble import split_stream_safe

# Long-chat window: render the trailing N messages + "Show earlier" header.
HISTORY_WINDOW = 50
HISTORY_WINDOW_STEP = 50


@dataclass
class StreamAccumulator:
    """Coalesces streamed chunks into throttled, flicker-free frames.

    ``push()`` returns the rendered frame (safe markdown + cursor) or
    None when no control update is needed — either throttled or the
    safe-to-render prefix is unchanged since the last flush.
    """

    throttle_ms: int = STREAM_THROTTLE_MS
    acc: list[str] = field(default_factory=list)
    # Running char counter (avoids O(n²) sum(len) per push DoS).
    acc_chars: int = 0
    # NOTE: main.py passes last_flush=time.monotonic() at stream start so
    # the first chunk obeys the same throttle as the legacy loop. Tests
    # use synthetic clocks and rely on the 0.0 default.
    last_flush: float = 0.0
    last_rendered: str | None = None

    def push(self, chunk: str, now: float) -> str | None:
        if not isinstance(chunk, str):
            chunk = str(chunk) if chunk else ""
        if not chunk:
            return None
        # Cap accumulation: a runaway provider must not OOM the phone.
        # 500k chars ≈ far beyond any displayable reply; finalize() still
        # returns what we kept.
        if self.acc_chars + len(chunk) > 500_000:
            return None
        self.acc.append(chunk)
        self.acc_chars += len(chunk)
        try:
            now_f = float(now)
        except (TypeError, ValueError):
            now_f = self.last_flush
        if (now_f - self.last_flush) * 1000 < self.throttle_ms:
            return None
        self.last_flush = now_f
        safe, _tail = split_stream_safe("".join(self.acc))
        if safe == self.last_rendered:
            return None
        self.last_rendered = safe
        return safe + STREAM_CURSOR

    def finalize(self, stopped: bool) -> str:
        text = "".join(self.acc).strip()
        # Release buffer memory promptly.
        try:
            self.acc.clear()
        except Exception:
            pass
        if stopped and not text:
            return "_(stopped)_"
        return text or "_(empty reply)_"


def window_slice(n_total: object, shown: object | None, window: int = HISTORY_WINDOW) -> tuple[int, bool, str]:
    """Compute the render window for a long chat.

    Returns (start_index, show_header, header_label). ``shown=None``
    means render everything. Otherwise render the trailing ``shown``
    messages with a "Show earlier" affordance when messages are hidden.
    """
    try:
        n = max(0, int(n_total))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        n = 0
    if shown is None:
        return (0, False, "")
    try:
        s = int(shown)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return (0, False, "")
    if s >= n:
        return (0, False, "")
    shown = max(1, s)
    start = n - shown
    return (start, True, f"Showing last {shown} of {n} — Show earlier")


def window_for_index(idx: object, shown: object | None, n_total: object, window: int = HISTORY_WINDOW) -> int | None:
    """Grow ``shown`` just enough to include message ``idx``.

    Returns the new ``shown`` value, or None when already covered / show-all.
    """
    try:
        i = int(idx)  # type: ignore[arg-type]
        n = int(n_total)  # type: ignore[arg-type]
        w = max(1, int(window))
    except (TypeError, ValueError):
        return None
    if shown is None or i < 0 or i >= n:
        return None
    try:
        s = int(shown)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    start = n - s
    if i >= start:
        return None
    # Include idx plus one extra page above it for context.
    return min(n, (n - i) + w)


class StreamRevealPacer:
    """Readable-paced stream reveal (v0.6).

    Decouples provider speed from display: provider tokens buffer and
    release at a steady, readable rate (``chars_per_tick`` per tick,
    extended to word boundaries) instead of whole chunks appearing at
    once. When the buffer runs far behind (fast provider, long reply) the
    rate scales up linearly so "done" never lags absurdly.

    Perf note: every released frame re-parses the whole reply Markdown,
    so defaults favor fewer, meatier frames (~8/s × ~20 chars ≈ same
    ~165 chars/s reading pace as the old 18/s × 9 chars) with ~2x fewer
    control updates.
    """

    def __init__(
        self,
        chars_per_tick: int = 20,
        tick_ms: int = 120,
        catchup_threshold: int = 400,
    ) -> None:
        self.buffer: str = ""
        self.shown: int = 0
        self.chars_per_tick = max(1, int(chars_per_tick))
        self.tick_ms = max(16, int(tick_ms))
        self.catchup_threshold = max(1, int(catchup_threshold))
        self._last_poll: float = 0.0

    @property
    def tick_s(self) -> float:
        return self.tick_ms / 1000.0

    def push(self, chunk: str | None) -> None:
        """Buffer a provider chunk (accumulates verbatim)."""
        if chunk is None:
            return
        if not isinstance(chunk, str):
            try:
                chunk = str(chunk)
            except Exception:
                return
        if not chunk:
            return
        # Cap buffer: runaway providers can't OOM the phone via backlog.
        if len(self.buffer) > 500_000:
            return
        # Avoid O(n²) += on huge strings: cap single append.
        if len(chunk) > 100_000:
            chunk = chunk[:100_000]
        self.buffer += chunk

    def _reveal_len(self) -> int:
        avail = len(self.buffer)
        if self.shown >= avail:
            return self.shown
        backlog = avail - self.shown
        n = self.chars_per_tick
        if backlog > self.catchup_threshold:
            # Linear speed-up: 2x at threshold, 3x at 2x threshold, …
            n = int(n * (1 + backlog / self.catchup_threshold))
        target = min(avail, self.shown + n)
        # Extend to the next word boundary for natural word-level reveal.
        while target < avail and not self.buffer[target].isspace():
            target += 1
        return target

    def poll(self, now: float | None = None, force: bool = False) -> str | None:
        """Next frame to display, or None when nothing new to show.

        Without ``force`` the tick interval gates how often text advances
        (callers poll per provider chunk). ``force=True`` bypasses the
        tick gate for the post-stream drain loop.
        """
        now = time.monotonic() if now is None else now
        if not force and (now - self._last_poll) < self.tick_s:
            return None
        self._last_poll = now
        target = self._reveal_len()
        if target <= self.shown:
            return None
        self.shown = target
        return self.buffer[: self.shown]
