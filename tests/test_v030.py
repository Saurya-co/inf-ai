"""v0.3.0 regression tests (stdlib unittest — no new deps, APK-safe).

Run: python -m unittest discover -s tests -v
Covers the Sept-2026 provider refresh + cryptography hard-dep path.
"""
import json
import os
import tempfile
import unittest

from app.config import (
    APP_VERSION,
    PROVIDERS,
    available_models,
    context_limit,
    supports_vision,
)
from app.data.key_store import KeyStore

try:
    from cryptography.fernet import Fernet  # noqa: F401
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False


class TestVersion(unittest.TestCase):
    def test_version(self):
        self.assertEqual(APP_VERSION, "0.6.0")


class TestRegistry030(unittest.TestCase):
    def test_gemini_default(self):
        self.assertEqual(PROVIDERS["gemini"]["default_model"], "gemini-3.8-flash")

    def test_groq_no_retired_ids(self):
        models = available_models("groq")
        for retired in (
            "qwen/qwen3-32b",
            "meta-llama/llama-4-scout-17b-16e-instruct",
            "llama-3.1-8b-instant",
            "llama-3.3-70b-versatile",
        ):
            self.assertNotIn(retired, models)
        for live in ("openai/gpt-oss-20b", "openai/gpt-oss-120b", "qwen/qwen3.6-27b"):
            self.assertIn(live, models)

    def test_groq_qwen_text_only(self):
        self.assertFalse(supports_vision("groq", "qwen/qwen3.6-27b"))
        self.assertFalse(supports_vision("groq", "qwen/qwen3.8-27b"))

    def test_anthropic_new_ids(self):
        models = available_models("anthropic")
        self.assertIn("claude-haiku-4-5", models)
        self.assertIn("claude-sonnet-5", models)
        self.assertNotIn("claude-3-5-haiku-20241022", models)

    def test_openrouter_resilient_default(self):
        self.assertEqual(PROVIDERS["openrouter"]["default_model"], "openrouter/free")
        models = available_models("openrouter")
        self.assertTrue(any(m.endswith(":free") for m in models))

    def test_context_limits_new(self):
        self.assertGreaterEqual(context_limit("gemini-3.8-flash"), 1_000_000)
        self.assertGreaterEqual(context_limit("claude-sonnet-5"), 1_000_000)
        self.assertGreaterEqual(context_limit("claude-haiku-4-5"), 200_000)
        self.assertGreaterEqual(context_limit("qwen/qwen3.6-27b"), 100_000)
        # retired IDs still resolve for old history
        self.assertGreater(context_limit("qwen/qwen3-32b"), 0)


@unittest.skipUnless(HAS_CRYPTO, "cryptography not installed")
class TestKeyStoreEncrypted(unittest.TestCase):
    def test_encrypted_at_rest_and_migration(self):
        with tempfile.TemporaryDirectory() as d:
            old = os.getcwd()
            os.chdir(d)
            try:
                os.makedirs("data", exist_ok=True)
                with open(os.path.join("data", "preferences.json"), "w") as fh:
                    json.dump({"multiai.groq.key": "sk-plain-1", "multiai.chat.model": "m"}, fh)
                ks = KeyStore()
                self.assertTrue(ks.encrypted)
                self.assertEqual(ks.get_key("groq"), "sk-plain-1")
                with open(ks._path, encoding="utf-8") as fh:
                    raw = fh.read()
                self.assertIn("enc:gAAAAA", raw)  # migrated
                self.assertNotIn("sk-plain-1", raw)  # not in plaintext
                ks.set_key("gemini", "sk-new-2")
                self.assertEqual(ks.get_key("gemini"), "sk-new-2")
                with open(ks._path, encoding="utf-8") as fh:
                    self.assertNotIn("sk-new-2", fh.read())
                self.assertEqual(KeyStore().get_key("groq"), "sk-plain-1")  # stable
            finally:
                os.chdir(old)


if __name__ == "__main__":
    unittest.main()
