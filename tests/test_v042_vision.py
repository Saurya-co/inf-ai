"""Vision-capability fix tests (stdlib unittest — no new deps, APK-safe).

The substring allowlist used to wrongly stop users sending images to
vision-capable models (OpenRouter :free/VLMs, Together VLMs, Groq -vl/
maverick/scout IDs, live /models entries). Fix: default-allow unknown
IDs + broader markers + per-model Send-anyway override.
Run: python -m unittest discover -s tests -v
"""
import unittest

from app.config import (
    is_known_text_only,
    supports_vision,
    vision_override_key,
)
from app.core.attachment_service import build_chat_messages
from app.core.types import Attachment

IMGS = [Attachment(name="a.png", mime="image/png", size=10, data_url="data:image/png;base64,x")]


class TestVisionDefaultAllow(unittest.TestCase):
    def test_openrouter_router_allowed(self):
        self.assertTrue(supports_vision("openrouter", "openrouter/free"))

    def test_openrouter_free_models_allowed(self):
        for m in ("z-ai/glm-5.2:free", "minimax/minimax-m3:free",
                  "moonshotai/kimi-k2.6:free", "qwen/qwen2.5-vl-32b:free",
                  "google/gemma-3-27b:free", "anthropic/claude-haiku-4-5:free"):
            self.assertTrue(supports_vision("openrouter", m), m)

    def test_openrouter_known_text_only_still_blocked(self):
        self.assertTrue(is_known_text_only("openrouter", "qwen/qwen3-coder-480b:free"))
        self.assertFalse(supports_vision("openrouter", "qwen/qwen3-coder-480b:free"))

    def test_groq_text_only_still_blocked(self):
        self.assertFalse(supports_vision("groq", "openai/gpt-oss-20b"))
        self.assertFalse(supports_vision("groq", "qwen/qwen3.6-27b"))

    def test_groq_vision_markers(self):
        for m in ("meta-llama/llama-4-scout-vision",
                  "meta-llama/llama-4-maverick-17b-128e-instruct",
                  "qwen/qwen3-vl-32b", "qwen/qwen2.5-vl-72b"):
            self.assertTrue(supports_vision("groq", m), m)

    def test_together_vision_markers(self):
        for m in ("meta-llama/Llama-Vision-Free",
                  "Qwen/Qwen2.5-VL-72B-Instruct",
                  "meta-llama/Llama-4-Maverick-17B-128E-Instruct"):
            self.assertTrue(supports_vision("together", m), m)

    def test_deepseek_still_blocked(self):
        self.assertFalse(supports_vision("deepseek", "deepseek-chat"))


class TestVisionOverride(unittest.TestCase):
    def test_override_key(self):
        self.assertEqual(vision_override_key("groq", "m"), "groq||m")

    def test_allow_param_bypasses(self):
        key = vision_override_key("groq", "openai/gpt-oss-20b")
        self.assertTrue(supports_vision("groq", "openai/gpt-oss-20b", allow=(key,)))
        self.assertTrue(supports_vision("groq", "openai/gpt-oss-20b",
                                        allow=frozenset({key})))
        # wrong key does not bypass
        self.assertFalse(supports_vision("groq", "openai/gpt-oss-20b",
                                         allow=("groq||other",)))

    def test_build_blocked_by_default(self):
        with self.assertRaises(ValueError) as ctx:
            build_chat_messages([], "hi", IMGS, "groq", "openai/gpt-oss-20b")
        self.assertIn("no vision support", str(ctx.exception))

    def test_build_override_sends(self):
        msgs = build_chat_messages([], "hi", IMGS, "groq", "openai/gpt-oss-20b",
                                   vision_override=True)
        self.assertIsInstance(msgs[-1].content, list)
        self.assertTrue(any(isinstance(p, dict) and p.get("type") == "image_url"
                            for p in msgs[-1].content))

    def test_build_allowed_model_untouched(self):
        msgs = build_chat_messages([], "hi", IMGS, "openrouter", "openrouter/free")
        self.assertIsInstance(msgs[-1].content, list)


if __name__ == "__main__":
    unittest.main()
