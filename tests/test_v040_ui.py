"""v0.4.0 UI-pack tests (stdlib unittest — no new deps, APK-safe).

Covers pure helpers only (no Flet page needed for most asserts;
Flet builders are smoke-tested where importable).
Run: python -m unittest discover -s tests -v
"""
import datetime as dt
import unittest

from app.ui.widgets.artifact_card import extract_artifacts, extract_citations
from app.ui.widgets.history_row import group_conversations, group_label, preview_of
from app.ui.widgets.input_bar import InputState, preview_label, send_button_mode
from app.ui.widgets.starter_cards import coerce_starters
from app.ui.widgets.streaming_bubble import (
    detect_text_direction,
    is_code_fence_open,
    split_stream_safe,
)


class TestStreamingBuffer(unittest.TestCase):
    def test_closed_renders_direct(self):
        safe, tail = split_stream_safe("hello **world**")
        self.assertEqual(safe, "hello **world**")
        self.assertEqual(tail, "")

    def test_open_fence_buffered(self):
        safe, tail = split_stream_safe("text\n```python\nprint(1)")
        self.assertTrue(safe.endswith("text\n"))
        self.assertTrue(tail.startswith("```"))
        self.assertTrue(is_code_fence_open("text\n```python\nprint(1)"))

    def test_closed_fence_renders(self):
        txt = "a\n```py\nx=1\n```\ndone"
        self.assertFalse(is_code_fence_open(txt))
        safe, tail = split_stream_safe(txt)
        self.assertEqual(safe, txt)


class TestDirection(unittest.TestCase):
    def test_ltr(self):
        self.assertEqual(detect_text_direction("Hello world"), "ltr")

    def test_rtl(self):
        self.assertEqual(detect_text_direction("مرحبا بك في التطبيق"), "rtl")

    def test_empty(self):
        self.assertEqual(detect_text_direction(""), "ltr")


class TestInputMode(unittest.TestCase):
    def test_stop_wins(self):
        kind, _ = send_button_mode(InputState(True, True, True))
        self.assertEqual(kind, "STOP")

    def test_send_with_text(self):
        kind, _ = send_button_mode(InputState(False, True, False))
        self.assertEqual(kind, "SEND")

    def test_mic_when_empty(self):
        kind, tip = send_button_mode(InputState(False, False, False))
        self.assertEqual(kind, "MIC")
        self.assertIn("soon", tip)

    def test_preview_label_truncates(self):
        self.assertIn("KB", preview_label("a" * 50 + ".png", 2048))


class TestArtifacts(unittest.TestCase):
    def test_extract_table(self):
        txt = "hi\n```table\n| a | b |\n| 1 | 2 |\n```\ndone"
        arts = extract_artifacts(txt)
        self.assertEqual(len(arts), 1)
        self.assertEqual(arts[0][0], "table")

    def test_unknown_lang_ignored(self):
        self.assertEqual(extract_artifacts("```python\nx=1\n```"), [])

    def test_citations_unique(self):
        txt = "see [r.pdf §1] and [r.pdf §1] plus [q.txt §2]"
        self.assertEqual(extract_citations(txt), ["r.pdf §1", "q.txt §2"])


class TestHistoryGrouping(unittest.TestCase):
    def test_labels(self):
        today = dt.date(2026, 9, 12)
        self.assertEqual(group_label("2026-09-12T10:00:00", today), "Today")
        self.assertEqual(group_label("2026-09-11T10:00:00", today), "Yesterday")
        self.assertEqual(group_label("2026-09-05T10:00:00", today), "Previous 7 days")
        self.assertEqual(group_label("2026-01-01T00:00:00", today), "Older")
        self.assertEqual(group_label("garbage", today), "Older")

    def test_group_order(self):
        convs = [
            {"id": 1, "title": "a", "provider": "g", "model": "m", "updated_at": "2026-09-12T01:00:00"},
            {"id": 2, "title": "b", "provider": "g", "model": "m", "updated_at": "2026-01-01T00:00:00"},
        ]
        sections = group_conversations(convs, dt.date(2026, 9, 12))
        self.assertEqual([s[0] for s in sections], ["Today", "Older"])

    def test_preview(self):
        self.assertIn("gemini", preview_of("t", "gemini", "flash"))


class TestStarters(unittest.TestCase):
    def test_defaults(self):
        # INF ai student toolkit: 6 study starters by default.
        items = coerce_starters(None)
        self.assertEqual(len(items), 6)
        self.assertTrue(all(s.title and s.prompt for s in items))

    def test_filters_bad(self):
        raw = [{"title": "", "prompt": ""}, {"title": "OK", "prompt": "hi"}]
        self.assertEqual(len(coerce_starters(raw)), 1)

    def test_caps_at_8(self):
        raw = [{"title": f"t{i}", "prompt": "p"} for i in range(20)]
        self.assertEqual(len(coerce_starters(raw)), 8)


if __name__ == "__main__":
    unittest.main()
