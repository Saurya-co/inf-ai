"""v0.5 R7+R3+R4 tests (stdlib unittest — no new deps, APK-safe).

Covers token metering helpers + totals migration, provider health/
capability helpers, and RAG source-viewer helpers.
Run: python -m unittest discover -s tests -v
"""
import os
import tempfile
import unittest

from app.core.types import Message
from app.data.chat_store import ChatStore
from app.ui.controllers.metering import (
    context_limit_for,
    context_used,
    conversation_tokens,
    format_tokens,
    meter_band,
    meter_label,
)
from app.ui.screens.providers_screen import (
    capability_line,
    format_latency,
    health_line,
    health_state,
    provider_meta_section,
    record_live_models,
    record_test_result,
)
from app.ui.widgets.history_row import history_subtitle
from app.ui.widgets.source_viewer import (
    bands_tooltip,
    find_excerpt_span,
    parse_citation_label,
    score_bands,
)


class TestMetering(unittest.TestCase):
    def test_format_tokens(self):
        self.assertEqual(format_tokens(0), "~0")
        self.assertEqual(format_tokens(950), "~950")
        self.assertEqual(format_tokens(12300), "~12.3k")
        self.assertEqual(format_tokens(12000), "~12k")
        self.assertEqual(format_tokens(2_500_000), "~2.5M")
        self.assertEqual(format_tokens(-5), "~0")
        self.assertEqual(format_tokens("nope"), "~0")

    def test_conversation_tokens(self):
        self.assertEqual(conversation_tokens({"input_tokens": 100, "output_tokens": 50}), 150)
        self.assertEqual(conversation_tokens({}), 0)

    def test_meter_band(self):
        self.assertEqual(meter_band(100, 1000), "ok")
        self.assertEqual(meter_band(699, 1000), "ok")
        self.assertEqual(meter_band(700, 1000), "warn")
        self.assertEqual(meter_band(899, 1000), "warn")
        self.assertEqual(meter_band(900, 1000), "critical")
        self.assertEqual(meter_band(5000, 1000), "critical")
        self.assertEqual(meter_band(5, 0), "ok")

    def test_meter_label(self):
        label = meter_label(3200, 131072)
        self.assertIn("3.2k", label)
        self.assertIn("131", label)
        self.assertIn("%", label)

    def test_context_used(self):
        msgs = [Message("user", "hello world"), Message("assistant", "hi there friend")]
        self.assertGreater(context_used(msgs), 0)
        self.assertEqual(context_used([]), 0)

    def test_context_limit_for(self):
        self.assertGreaterEqual(context_limit_for("openai/gpt-oss-20b"), 100_000)
        self.assertGreaterEqual(context_limit_for("unknown-model-xyz"), 1000)

    def test_totals_migration_and_accumulation(self):
        store = ChatStore(db_path=":memory:")
        cid = store.create_conversation("T", "gemini", "m")
        store.add_token_usage(cid, 100, 50)
        store.add_token_usage(cid, 25, 25)
        row = next(c for c in store.list_conversations() if c["id"] == cid)
        self.assertEqual(row["input_tokens"], 125)
        self.assertEqual(row["output_tokens"], 75)
        store.close()

    def test_history_subtitle(self):
        sub = history_subtitle({"title": "t", "provider": "gemini", "model": "flash",
                                "input_tokens": 12000, "output_tokens": 300})
        self.assertIn("gemini", sub)
        self.assertIn("12.3k", sub)
        plain = history_subtitle({"title": "t", "provider": "gemini", "model": "flash"})
        self.assertNotIn("tok", plain)


class TestProvidersPolish(unittest.TestCase):
    def test_format_latency(self):
        self.assertEqual(format_latency(12.4), "12 ms")
        self.assertEqual(format_latency(1500), "1.5 s")
        self.assertEqual(format_latency(None), "—")
        self.assertEqual(format_latency("junk"), "—")
        self.assertEqual(format_latency(-3), "—")

    def test_health_state(self):
        self.assertEqual(health_state(True), "ok")
        self.assertEqual(health_state(False), "fail")
        self.assertEqual(health_state(None), "untested")

    def test_meta_section(self):
        self.assertEqual(provider_meta_section("groq"), "prov_groq")

    def test_health_line_untested(self):
        from app.data.key_store import KeyStore

        with tempfile.TemporaryDirectory() as d:
            old = os.getcwd()
            os.chdir(d)
            try:
                self.assertIn("Not tested", health_line("groq", KeyStore()))
            finally:
                os.chdir(old)

    def test_record_roundtrip(self):
        from app.data.key_store import KeyStore

        with tempfile.TemporaryDirectory() as d:
            old = os.getcwd()
            os.chdir(d)
            try:
                store = KeyStore()
                record_test_result(store, "groq", True, 123.6)
                line = health_line("groq", store)
                self.assertIn("OK", line)
                self.assertIn("124 ms", line)
                record_test_result(store, "groq", False, None)
                self.assertIn("Failed", health_line("groq", store))
                record_live_models(store, "groq", 7)
                self.assertEqual(store.get("prov_groq", "live_count", ""), "7")
            finally:
                os.chdir(old)

    def test_capability_line(self):
        line = capability_line("groq")
        self.assertIn("model(s)", line)
        self.assertIn("vision", line)
        self.assertIn("docs", line)
        self.assertIn("No models", capability_line("custom"))


class TestSourceViewer(unittest.TestCase):
    def test_parse_label(self):
        self.assertEqual(parse_citation_label("report.pdf §1"), ("report.pdf", 0))
        self.assertEqual(parse_citation_label("my doc §12"), ("my doc", 11))
        self.assertEqual(parse_citation_label("plain"), ("plain", None))
        self.assertEqual(parse_citation_label("a §0"), ("a", 0))

    def test_excerpt_span(self):
        chunk = "The server budgetAlloc is fifty thousand dollars for March."
        s, e = find_excerpt_span(chunk, ["the", "budgetalloc", "zzz"])
        self.assertGreater(e, s)
        self.assertEqual(chunk[s:e].lower(), "budgetalloc")
        self.assertEqual(find_excerpt_span(chunk, ["the", "is"]), (0, 0))
        self.assertEqual(find_excerpt_span("", ["hello world"]), (0, 0))

    def test_score_bands(self):
        bands = score_bands([1.0, 0.7, 0.4, 0.1])
        self.assertEqual(bands, {"high": 2, "med": 1, "low": 1})
        self.assertEqual(score_bands([]), {"high": 0, "med": 0, "low": 0})
        self.assertEqual(score_bands([0.0, 0.0])["low"], 2)
        self.assertEqual(score_bands(["x"]), {"high": 0, "med": 0, "low": 0})

    def test_bands_tooltip(self):
        tip = bands_tooltip({"high": 2, "med": 1, "low": 0})
        self.assertIn("2 strong", tip)
        self.assertIn("TF-IDF", tip)
        self.assertIn("TF-IDF", bands_tooltip({"high": 0, "med": 0, "low": 0}))

    def test_clear_chunks(self):
        store = ChatStore(db_path=":memory:")
        cid = store.create_conversation("T", "gemini", "m")
        store.index_doc_chunks(cid, "r.pdf", ["aaa", "bbb"])
        self.assertEqual(store.clear_doc_chunks(cid), 2)
        self.assertEqual(store.get_doc_chunks(cid), {})
        self.assertEqual(store.clear_doc_chunks(99999), 0)
        store.close()


if __name__ == "__main__":
    unittest.main()
