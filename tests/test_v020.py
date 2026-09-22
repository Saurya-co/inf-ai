"""v0.2.0 regression tests (stdlib unittest — no new deps, APK-safe).

Run: python -m unittest discover -s tests -v
"""
import os
import tempfile
import unittest

from app.config import available_models, context_limit, supports_vision
from app.core.attachment_service import build_chat_messages, classify, validate_file
from app.core.chat_service import (
    compaction_target_count,
    estimate_tokens,
    message_tokens,
    should_compact,
)
from app.core.errors import ProviderError, map_http_status
from app.core.history_utils import (
    assistant_text_of,
    filter_conversations,
    short_title,
    user_text_of,
)
from app.core.provider_base import parse_sse_line
from app.core.provider_factory import normalize_base_url
from app.core.types import Attachment, Message
from app.data.chat_store import ChatStore
from app.data.key_store import KeyStore


class TestSSE(unittest.TestCase):
    def test_data_line(self):
        line = 'data: {"choices":[{"delta":{"content":"hi"}}]}'
        self.assertEqual(parse_sse_line(line), "hi")

    def test_done(self):
        self.assertIsNone(parse_sse_line("data: [DONE]"))

    def test_keepalive(self):
        self.assertEqual(parse_sse_line(": ping"), "")
        self.assertEqual(parse_sse_line(""), "")


class TestAttachments(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(classify("a.png"), "image")
        self.assertEqual(classify("b.PDF"), "doc")
        self.assertIsNone(classify("c.exe"))

    def test_vision_block(self):
        imgs = [Attachment(name="a.png", mime="image/png", size=10, data_url="data:image/png;base64,x")]
        with self.assertRaises(ValueError):
            build_chat_messages([], "hi", imgs, "groq", "openai/gpt-oss-20b")

    def test_docs_injected(self):
        docs = [Attachment(name="a.txt", mime="text/plain", size=5, text="hello")]
        msgs = build_chat_messages([], "hi", docs, "groq", "openai/gpt-oss-20b")
        self.assertIn("hello", str(msgs[-1].content))


class TestConfig020(unittest.TestCase):
    def test_groq_defaults_current(self):
        models = available_models("groq")
        self.assertIn("openai/gpt-oss-20b", models)
        self.assertNotIn("llama-3.1-8b-instant", models)

    def test_together_free_suffix(self):
        models = available_models("together")
        self.assertTrue(any(m.endswith("-Free") or m.endswith("-free") for m in models))

    def test_groq_text_only(self):
        self.assertFalse(supports_vision("groq", "openai/gpt-oss-20b"))
        # v0.3.0: llama-4-scout retired 07/17/26; groq vision only on
        # *vision*/llava IDs now.
        self.assertTrue(supports_vision("groq", "meta-llama/llama-4-scout-vision"))

    def test_context_limits(self):
        self.assertGreaterEqual(context_limit("openai/gpt-oss-20b"), 100_000)
        self.assertGreaterEqual(context_limit("gemini-2.5-flash"), 500_000)


class TestHistoryUtils(unittest.TestCase):
    def test_user_text_str(self):
        self.assertEqual(user_text_of("hi"), ("hi", False))

    def test_user_text_multimodal(self):
        content = [
            {"type": "text", "text": "see"},
            {"type": "image_url", "image_url": {"url": "data:x"}},
        ]
        text, has = user_text_of(content)
        self.assertEqual(text, "see")
        self.assertTrue(has)

    def test_assistant(self):
        self.assertEqual(assistant_text_of("yo"), "yo")

    def test_short_title(self):
        self.assertEqual(short_title("  hello\nworld  "), "hello world")
        self.assertEqual(short_title(""), "New chat")

    def test_filter(self):
        convs = [
            {"id": 1, "title": "Shopping", "provider": "groq", "model": "m"},
            {"id": 2, "title": "Code", "provider": "gemini", "model": "m"},
        ]
        self.assertEqual(len(filter_conversations(convs, "")), 2)
        self.assertEqual(filter_conversations(convs, "shop")[0]["id"], 1)


class TestChatStore(unittest.TestCase):
    def test_roundtrip_and_search(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "t.db")
            store = ChatStore(db_path=db)
            cid = store.create_conversation("T", "groq", "m")
            store.add_message(cid, "user", "unique zebra phrase 12345")
            store.add_message(cid, "assistant", "reply")
            msgs = store.get_messages(cid)
            self.assertEqual(len(msgs), 2)
            hits = store.search_conversations("zebra")
            self.assertIn(cid, hits)
            store.rename_conversation(cid, "Renamed")
            self.assertEqual(store.list_conversations()[0]["title"], "Renamed")
            store.close()


class TestKeyStore(unittest.TestCase):
    def test_set_get_roundtrip_tmpcwd(self):
        with tempfile.TemporaryDirectory() as d:
            old = os.getcwd()
            os.chdir(d)
            try:
                ks = KeyStore()
                ks.set_key("groq", "sk-test-1234")
                self.assertEqual(ks.get_key("groq"), "sk-test-1234")
                self.assertTrue(ks.mask("sk-test-1234").endswith("1234"))
            finally:
                os.chdir(old)

    def test_errors(self):
        self.assertEqual(map_http_status(401), "auth")
        self.assertEqual(map_http_status(429), "rate_limit")
        self.assertIn("Invalid API key", ProviderError("auth").friendly())
        self.assertTrue(normalize_base_url("api.example.com").startswith("https://"))
        self.assertGreater(estimate_tokens("abcd"), 0)


if __name__ == "__main__":
    unittest.main()
