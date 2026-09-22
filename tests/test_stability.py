"""Stability regressions: previously-crashing paths must build cleanly."""

import os
import tempfile
import unittest

from app.config import (
    context_limit,
    get_model_metadata,
    set_live_models,
    supports_vision,
)
from app.core.attachment_service import chunk_text, classify, validate_file
from app.core.errors import ProviderError, map_http_status
from app.core.history_utils import (
    assistant_text_of,
    filter_conversations,
    short_title,
    user_text_of,
)
from app.core.provider_factory import get_provider, normalize_base_url
from app.core.rag import build_rag_block, chunk_for_rag, tokenize
from app.data.chat_store import ChatStore
from app.ui.widgets.empty_state import build_empty_state
from app.ui.widgets.find_bar import (
    build_match_index,
    format_counter,
    row_key,
    step_index,
)
from app.ui.widgets.starter_cards import coerce_starters, starter_grid


class TestStarterGridBuilds(unittest.TestCase):
    def test_grid_builds_without_name_error(self):
        # Regression: tooltip referenced undefined `_s` -> NameError ->
        # empty state silently fell back to chips, starters never showed.
        starters = coerce_starters(None)
        grid = starter_grid(starters, lambda s: None)
        self.assertEqual(len(grid.controls), len(starters))

    def test_empty_state_uses_starter_grid(self):
        es = build_empty_state(lambda p: None)
        self.assertTrue(len(es.controls) > 0)


class TestProviderMetadataIntact(unittest.TestCase):
    def test_huggingface_metadata_not_wiped(self):
        # Regression: duplicate "huggingface" dict key wiped real metadata.
        m = get_model_metadata("huggingface", "meta-llama/Llama-3.3-70B-Instruct")
        self.assertEqual(m["context_window"], 131072)
        self.assertEqual(m["pricing_tier"], "free")

    def test_unknown_model_falls_back_safely(self):
        m = get_model_metadata("custom", "some-unknown-model")
        self.assertGreater(m["context_window"], 0)


class TestDeepDiveFixes(unittest.TestCase):
    """Deep-dive hardening: every previously-crashing input is now safe."""

    def _store(self):
        d = tempfile.mkdtemp()
        return ChatStore(os.path.join(d, "t.db"))

    def test_fts_injection_safe(self):
        cs = self._store()
        try:
            self.assertEqual(cs.search_conversations('"unclosed ((('), [])
            self.assertEqual(cs.search_conversations("***", 0), [])
        finally:
            cs.close()

    def test_decode_tolerates_junk(self):
        self.assertEqual(ChatStore._decode(None), "")
        self.assertEqual(ChatStore._decode(b'"hi"'), "hi")
        self.assertEqual(ChatStore._decode(123), "")

    def test_index_doc_chunks_str_input(self):
        cs = self._store()
        try:
            cid = cs.create_conversation("t", "gemini", "m")
            n = cs.index_doc_chunks(cid, "a.txt", "one-string")
            self.assertEqual(n, 1)
        finally:
            cs.close()

    def test_export_single_query(self):
        cs = self._store()
        try:
            cid = cs.create_conversation("t", "gemini", "m")
            cs.add_message(cid, "user", "hi")
            self.assertIn("hi", cs.export_json(cid))
            self.assertIn("hi", cs.export_markdown(cid))
        finally:
            cs.close()

    def test_list_limit_clamped(self):
        cs = self._store()
        try:
            self.assertEqual(cs.list_conversations("junk"), cs.list_conversations(100))
            self.assertTrue(len(cs.list_conversations(10**9)) >= 0)
        finally:
            cs.close()

    def test_config_guards(self):
        set_live_models("x", "abc")  # single string = one model, not chars
        set_live_models("x", None)  # ignored, no crash
        self.assertFalse(supports_vision("groq", "openai/gpt-oss-20b", allow="k"))
        # Longest-substring wins regardless of dict order.
        self.assertEqual(context_limit("llama-4-scout"), 131072)

    def test_history_utils_robust(self):
        self.assertEqual(user_text_of(None), ("", False))
        self.assertEqual(user_text_of([{"type": "text", "text": 5}]), ("5", False))
        self.assertEqual(assistant_text_of(123), "")
        self.assertEqual(short_title(None), "New chat")
        self.assertEqual(filter_conversations(None, "q"), [])

    def test_errors_robust(self):
        self.assertIn("Provider error", ProviderError("unknown", None).friendly())
        self.assertEqual(map_http_status(None), "unknown")
        self.assertEqual(map_http_status("500"), "unknown")

    def test_attachment_guards(self):
        self.assertIsNone(classify(None))
        with self.assertRaises(ValueError):
            validate_file("x.png", -1)
        with self.assertRaises(ValueError):
            validate_file("x.png", "big")
        self.assertEqual(chunk_text("hello world", 0), ["hello world"])

    def test_rag_guards(self):
        self.assertEqual(tokenize(b"hi"), ["hi"])
        self.assertEqual(tokenize(None), [])
        self.assertTrue(chunk_for_rag("hi", 0, 9999))
        self.assertEqual(build_rag_block(None, "x"), ("", []))

    def test_provider_factory_guards(self):
        with self.assertRaises(ValueError):
            normalize_base_url(b"http://x")
        with self.assertRaises(ValueError):
            get_provider(["x"], "k", "https://x.test")
        with self.assertRaises(ValueError):
            get_provider("gemini", None, "https://x.test")
        # Bad timeout coerced, not crashing.
        p = get_provider("gemini", "k", "https://x.test", timeout="junk")
        self.assertEqual(p._timeout, 60.0)

    def test_find_bar_guards(self):
        self.assertEqual(row_key(None), "msg-0")
        self.assertEqual(build_match_index(None, "q"), [])
        self.assertEqual(build_match_index(["a"], None), [])
        self.assertEqual(format_counter("x", "y"), "0/0")
        self.assertEqual(step_index(None, None, None), 0)

    def test_latex_no_recursion_error(self):
        from app.core.latex import latex_to_unicode

        evil = "\\frac{" * 50 + "x" + "}" * 50
        self.assertIsInstance(latex_to_unicode(evil), str)
        self.assertIsInstance(latex_to_unicode("H_2O and CO_2"), str)
        self.assertIn("H\u2082O", latex_to_unicode("Photosynthesis needs H_2O."))


if __name__ == "__main__":
    unittest.main()
