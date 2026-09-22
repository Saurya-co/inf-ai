"""v0.5 R1+R6 tests (stdlib unittest — no new deps, APK-safe).

Covers the R0 streaming-controller extraction (accumulator flush
coalescing, finalize, window slicing/growth) and find-in-chat helpers
(match index, counter, wrap-around stepping, row keys/highlight).
Run: python -m unittest discover -s tests -v
"""
import unittest

import flet as ft

from app.ui.controllers.streaming import (
    HISTORY_WINDOW,
    StreamAccumulator,
    window_for_index,
    window_slice,
)
from app.ui.widgets.find_bar import (
    build_match_index,
    format_counter,
    row_key,
    set_row_highlight,
    step_index,
)
from app.ui.widgets.message_bubble import assistant_bubble, user_bubble
from app.ui.widgets.streaming_bubble import StreamingBubble


class TestStreamAccumulator(unittest.TestCase):
    def test_throttle_suppresses_fast_chunks(self):
        acc = StreamAccumulator(throttle_ms=120)
        self.assertIsNone(acc.push("hello ", 0.0))
        self.assertIsNone(acc.push("world", 0.05))

    def test_flush_after_throttle(self):
        acc = StreamAccumulator(throttle_ms=120)
        self.assertIsNone(acc.push("hello ", 0.0))
        frame = acc.push("world", 0.2)
        self.assertIsNotNone(frame)
        assert frame is not None
        self.assertTrue(frame.startswith("hello world"))
        self.assertTrue(frame.endswith("▍"))

    def test_unchanged_safe_prefix_skips_update(self):
        acc = StreamAccumulator(throttle_ms=0)
        first = acc.push("```py\nx=1", 0.0)
        self.assertIsNotNone(first)
        # Next chunk is buffered behind the open fence: safe prefix
        # unchanged → no update needed.
        self.assertIsNone(acc.push("\nmore", 1.0))

    def test_changed_prefix_flushes(self):
        acc = StreamAccumulator(throttle_ms=0)
        acc.push("a", 0.0)
        self.assertIsNotNone(acc.push("b", 1.0))

    def test_finalize(self):
        acc = StreamAccumulator(throttle_ms=0)
        acc.push("hi", 0.0)
        self.assertEqual(acc.finalize(False), "hi")
        self.assertEqual(StreamAccumulator().finalize(False), "_(empty reply)_")
        self.assertEqual(StreamAccumulator().finalize(True), "_(stopped)_")
        stopped = StreamAccumulator(throttle_ms=0)
        stopped.push("partial", 0.0)
        self.assertEqual(stopped.finalize(True), "partial")


class TestWindowSlice(unittest.TestCase):
    def test_show_all(self):
        self.assertEqual(window_slice(10, None), (0, False, ""))
        self.assertEqual(window_slice(50, 50), (0, False, ""))

    def test_windowed(self):
        start, header, label = window_slice(120, 50)
        self.assertEqual(start, 70)
        self.assertTrue(header)
        self.assertIn("50", label)
        self.assertIn("120", label)

    def test_empty(self):
        self.assertEqual(window_slice(0, None), (0, False, ""))

    def test_growth(self):
        self.assertIsNone(window_for_index(119, 50, 120))  # covered
        self.assertIsNone(window_for_index(5, None, 120))  # show-all
        grown = window_for_index(10, 50, 120)
        self.assertIsNotNone(grown)
        assert grown is not None
        self.assertGreaterEqual(grown, 50)
        self.assertLessEqual(grown, 120)
        # Grown window covers the target index.
        start, _, _ = window_slice(120, grown)
        self.assertLessEqual(start, 10)


class TestFindBar(unittest.TestCase):
    TEXTS = ["Hello world", "second line here", "HELLO again", "unrelated"]

    def test_match_index(self):
        self.assertEqual(build_match_index(self.TEXTS, "hello"), [0, 2])
        self.assertEqual(build_match_index(self.TEXTS, "  "), [])
        self.assertEqual(build_match_index(self.TEXTS, ""), [])
        self.assertEqual(build_match_index(self.TEXTS, "zzz"), [])

    def test_counter(self):
        self.assertEqual(format_counter(0, 3), "1/3")
        self.assertEqual(format_counter(2, 3), "3/3")
        self.assertEqual(format_counter(0, 0), "0/0")

    def test_step_wraps(self):
        self.assertEqual(step_index(2, 1, 3), 0)
        self.assertEqual(step_index(0, -1, 3), 2)
        self.assertEqual(step_index(1, 1, 3), 2)
        self.assertEqual(step_index(0, 1, 0), 0)

    def test_row_key(self):
        self.assertEqual(row_key(7), "msg-7")

    def test_highlight_user_row(self):
        row = user_bubble("hi", timestamp="10:00")
        self.assertTrue(set_row_highlight(row, True))
        bubble = row.controls[-1]
        self.assertIsNotNone(bubble.border)
        self.assertTrue(set_row_highlight(row, False))
        self.assertIsNone(bubble.border)

    def test_highlight_skips_system_row(self):
        sys_row = ft.Row([ft.Icon(ft.Icons.HISTORY, size=14), ft.Text("x")])
        # Last control is Text, not a Container → skipped.
        self.assertFalse(set_row_highlight(sys_row, True))

    def test_streaming_bubble_grafts_assistant(self):
        md_holder: dict = {}

        def _factory():
            m = ft.Markdown("hi")
            md_holder["md"] = m
            return m

        bubble = StreamingBubble(_factory, timestamp="10:00")
        self.assertIs(bubble.md, md_holder["md"])
        self.assertIsNotNone(bubble.data)  # actions row grafted
        self.assertTrue(len(bubble.controls) > 0)

    def test_history_window_default(self):
        self.assertEqual(HISTORY_WINDOW, 50)


if __name__ == "__main__":
    unittest.main()
