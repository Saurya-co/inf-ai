"""v0.4 refinement tests (stdlib unittest — no new deps, APK-safe).

Covers Phase A–F pure helpers: message lifecycle, attach states,
artifact panel parse/convert/registry, model recents/presets/matrix,
history filters, theme scaling.
Run: python -m unittest discover -s tests -v
"""
import unittest

from app.data.chat_store import ChatStore
from app.ui.theme import align_for_direction, ts
from app.ui.widgets.artifact_panel import (
    ArtifactRegistry,
    artifact_to_csv,
    artifact_to_text,
    download_name,
    parse_chart_payload,
)
from app.ui.widgets.history_row import apply_history_filter, empty_history_message
from app.ui.widgets.input_bar import (
    AttachmentState,
    attach_status_line,
    is_attach_blocked,
)
from app.ui.widgets.message_bubble import (
    FEEDBACK_REASONS,
    fork_history,
    parse_code_blocks,
    token_footer,
)
from app.ui.widgets.model_sheet import (
    apply_preset_filter,
    capability_matrix,
    parse_recents,
    push_recent,
)


class TestMessageLifecycle(unittest.TestCase):
    def test_parse_code_blocks(self):
        txt = "a\n```python\nx=1\n```\nmid\n```js\ny=2\n```"
        blocks = parse_code_blocks(txt)
        self.assertEqual([b[0] for b in blocks], ["python", "js"])
        self.assertIn("x=1", blocks[0][1])

    def test_parse_code_blocks_none(self):
        self.assertEqual(parse_code_blocks("plain text"), [])

    def test_fork_truncates(self):
        self.assertEqual(fork_history(["a", "b", "c"], 1), ["a", "b"])

    def test_fork_oob(self):
        self.assertEqual(fork_history(["a"], 9), ["a"])
        self.assertEqual(fork_history([], 0), [])

    def test_token_footer(self):
        self.assertIn("~12 tokens", token_footer(12, "10:00"))
        self.assertEqual(token_footer(None, None), "")

    def test_feedback_reasons(self):
        self.assertEqual(len(FEEDBACK_REASONS), 4)


class TestAttachStates(unittest.TestCase):
    def test_status_lines(self):
        self.assertIn("reading", attach_status_line(AttachmentState("a.png", 2048, "reading")))
        self.assertIn("too large", attach_status_line(AttachmentState("b.pdf", 10**7, "too-large")))
        self.assertIn("failed", attach_status_line(AttachmentState("c.txt", 10, "failed", "no data")))

    def test_blocked(self):
        self.assertTrue(is_attach_blocked(AttachmentState("x", 1, "failed")))
        self.assertFalse(is_attach_blocked(AttachmentState("x", 1, "ready")))


class TestArtifactPanel(unittest.TestCase):
    def test_chart_valid(self):
        p = parse_chart_payload('{"labels":["a","b"],"values":[1,2]}')
        self.assertIsNotNone(p)
        assert p is not None
        self.assertEqual(p["labels"], ["a", "b"])

    def test_chart_invalid(self):
        self.assertIsNone(parse_chart_payload('{"labels":["a"],"values":[1,2]}'))
        self.assertIsNone(parse_chart_payload("not json"))
        self.assertIsNone(parse_chart_payload('{"labels":[],"values":[]}'))

    def test_csv(self):
        csv_text = artifact_to_csv("| a | b |\n| 1 | 2 |")
        self.assertIn("a,b", csv_text.replace(" ", "").splitlines()[0] if csv_text else "")

    def test_text_fallback(self):
        self.assertIn("hello", artifact_to_text("card", "hello"))

    def test_registry_cap(self):
        reg = ArtifactRegistry()
        for i in range(25):
            reg.add(1, "json", f'{{"i":{i}}}')
        self.assertEqual(len(reg.list(1)), 20)
        self.assertEqual(reg.list(999), [])
        reg.clear(1)
        self.assertEqual(reg.list(1), [])

    def test_download_names(self):
        fname, ext = download_name("table", 1)
        self.assertTrue(fname.endswith(".csv"))
        self.assertEqual(ext, "csv")


class TestModelPicker(unittest.TestCase):
    def test_push_recent_dedup(self):
        r = push_recent([], "gemini", "flash")
        r = push_recent(r, "groq", "m")
        r = push_recent(r, "gemini", "flash")
        self.assertEqual(r[0], ("gemini", "flash"))
        self.assertEqual(len(r), 2)

    def test_push_recent_cap(self):
        r: list = []
        for i in range(10):
            r = push_recent(r, "p", f"m{i}")
        self.assertEqual(len(r), 5)

    def test_parse_recents(self):
        self.assertEqual(parse_recents('[["a","b"]]'), [("a", "b")])
        self.assertEqual(parse_recents("garbage"), [])

    def test_preset_all(self):
        rows = [("p", "m", True), ("p", "m2", False)]
        self.assertEqual(len(apply_preset_filter(rows, "all")), 2)
        self.assertEqual(apply_preset_filter(rows, "free"), [("p", "m", True)])

    def test_matrix_shape(self):
        m = capability_matrix()
        self.assertTrue(m)
        self.assertEqual(len(m[0]), 4)


class TestHistoryRefine(unittest.TestCase):
    CONVS = [
        {"id": 1, "pinned": 1, "archived": 0, "provider": "gemini"},
        {"id": 2, "pinned": 0, "archived": 1, "provider": "groq"},
        {"id": 3, "pinned": 0, "archived": 0, "provider": "gemini"},
    ]

    def test_pinned_filter(self):
        self.assertEqual([c["id"] for c in apply_history_filter(self.CONVS, "pinned")], [1])

    def test_archived_filter(self):
        self.assertEqual([c["id"] for c in apply_history_filter(self.CONVS, "archived")], [2])

    def test_all_hides_archived(self):
        self.assertEqual({c["id"] for c in apply_history_filter(self.CONVS, "all")}, {1, 3})

    def test_provider_filter(self):
        out = apply_history_filter(self.CONVS, "all", "gemini")
        self.assertEqual([c["id"] for c in out], [1, 3])

    def test_empty_messages(self):
        self.assertIn("pinned", empty_history_message("pinned", "").lower())
        self.assertIn("search", empty_history_message("all", "xyz").lower())

    def test_store_flags(self):
        store = ChatStore(db_path=":memory:")
        cid = store.create_conversation("T", "gemini", "m")
        store.set_pinned(cid, True)
        store.set_archived(cid, True)
        convs = store.list_conversations()
        row = next(c for c in convs if c["id"] == cid)
        self.assertEqual(row["pinned"], 1)
        self.assertEqual(row["archived"], 1)
        store.close()


class TestThemeRefine(unittest.TestCase):
    def test_ts(self):
        self.assertEqual(ts(10, "standard"), 10.0)
        self.assertAlmostEqual(ts(10, "large"), 11.5)
        self.assertEqual(ts(10, "bogus"), 10.0)

    def test_align(self):
        import flet as ft

        self.assertEqual(align_for_direction("rtl", default_end=True),
                         ft.MainAxisAlignment.START)
        self.assertEqual(align_for_direction("ltr", default_end=True),
                         ft.MainAxisAlignment.END)


if __name__ == "__main__":
    unittest.main()
