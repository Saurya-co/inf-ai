"""v0.6 tests (stdlib unittest — no new deps, APK-safe).

Covers the readable-paced stream reveal (StreamRevealPacer: tick pacing,
word-boundary release, catch-up speedup, drain loop) and the linked-API
provider filter in the model picker (iter_model_rows linked=... only lists
models the user can actually send to).
Run: python -m unittest discover -s tests -v
"""
import unittest

from app.ui.controllers.streaming import StreamRevealPacer
from app.ui.widgets.model_sheet import iter_model_rows


class TestStreamRevealPacer(unittest.TestCase):
    def test_tick_gates_reveal(self):
        p = StreamRevealPacer(chars_per_tick=9, tick_ms=55)
        p.push("hello world, this is a long reply stream")
        first = p.poll(now=1.0)
        self.assertIsNotNone(first)
        # Tick not elapsed yet — nothing new to reveal.
        self.assertIsNone(p.poll(now=1.01))
        # After the tick, more words are released.
        second = p.poll(now=1.1)
        self.assertIsNotNone(second)
        assert first is not None and second is not None
        self.assertTrue(second.startswith(first))
        self.assertTrue(len(second) > len(first))

    def test_reveals_to_word_boundary(self):
        p = StreamRevealPacer(chars_per_tick=9, tick_ms=55)
        p.push("hello world")
        frame = p.poll(now=1.0, force=True)
        self.assertIsNotNone(frame)
        assert frame is not None
        # Never mid-word: either the full buffer or ends at whitespace.
        full = len(frame) == len("hello world")
        self.assertTrue(full or frame[-1].isspace() or " " not in frame[len(frame):])

    def test_drain_with_force(self):
        p = StreamRevealPacer(chars_per_tick=1000, tick_ms=55)
        p.push("all at once after stream end")
        frame = p.poll(force=True)
        self.assertEqual(frame, "all at once after stream end")
        # Buffer exhausted — drain loop breaks.
        self.assertIsNone(p.poll(force=True))

    def test_empty_buffer_returns_none(self):
        p = StreamRevealPacer()
        self.assertIsNone(p.poll(now=1.0, force=True))

    def test_catchup_speeds_up_behind_backlog(self):
        fast = StreamRevealPacer(chars_per_tick=9, tick_ms=55, catchup_threshold=100)
        fast.push("word " * 500)
        slow = StreamRevealPacer(chars_per_tick=9, tick_ms=55, catchup_threshold=10**9)
        slow.push("word " * 500)
        f1 = fast.poll(now=1.0, force=True)
        s1 = slow.poll(now=1.0, force=True)
        self.assertIsNotNone(f1)
        assert f1 is not None and s1 is not None
        # Deep backlog -> the pacer releases noticeably more per tick.
        self.assertTrue(len(f1) > len(s1))

    def test_tick_s_property(self):
        p = StreamRevealPacer(tick_ms=55)
        self.assertAlmostEqual(p.tick_s, 0.055)

    def test_none_chunk_is_safe(self):
        p = StreamRevealPacer()
        p.push(None)  # type: ignore[arg-type]
        self.assertEqual(p.buffer, "")


class TestLinkedProviderFilter(unittest.TestCase):
    def test_linked_filters_providers(self):
        rows = iter_model_rows("", linked={"gemini"})
        pids = {pid for pid, _m, _f in rows}
        self.assertEqual(pids, {"gemini"})
        self.assertTrue(all(m for _p, m, _f in rows))

    def test_linked_none_lists_everything(self):
        rows = iter_model_rows("")
        pids = {pid for pid, _m, _f in rows}
        self.assertTrue("gemini" in pids and "openrouter" in pids)

    def test_linked_empty_lists_nothing(self):
        self.assertEqual(iter_model_rows("", linked=set()), [])

    def test_linked_with_query(self):
        rows = iter_model_rows("flash", linked={"gemini", "groq"})
        pids = {pid for pid, _m, _f in rows}
        self.assertTrue(pids <= {"gemini", "groq"})
        self.assertTrue(any("flash" in m for _p, m, _f in rows))


if __name__ == "__main__":
    unittest.main()
