"""v0.6 image-output + smart search tests (stdlib unittest, httpx mocks).

Covers: capability-aware model search (row_search_text / iter_model_rows),
OpenAI-compat /images/generations parsing (b64_json, url download, error
shapes), and the persisted generated-image note roundtrip.
Run: python -m unittest discover -s tests -v
"""
import asyncio
import base64
import json
import unittest

import httpx

from app.config import supports_image_gen, available_image_models
from app.core.errors import ProviderError
from app.core.provider_base import OpenAICompatProvider
from app.ui.widgets.image_card import image_note, parse_image_note
from app.ui.widgets.model_sheet import iter_model_rows, row_search_text

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        try:
            loop.close()
        except Exception:
            pass


def _provider(handler) -> OpenAICompatProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    return OpenAICompatProvider("k", "https://x.test/v1", client=client)


class TestImageGenSupport(unittest.TestCase):
    def test_supported_providers(self):
        self.assertTrue(supports_image_gen("openai"))
        self.assertTrue(supports_image_gen("together"))
        self.assertTrue(supports_image_gen("custom"))
        self.assertFalse(supports_image_gen("gemini"))
        self.assertFalse(supports_image_gen("anthropic"))
        self.assertFalse(supports_image_gen("groq"))

    def test_image_model_lists(self):
        self.assertIn("gpt-image-1", available_image_models("openai"))
        self.assertTrue(any("FLUX" in m for m in available_image_models("together")))
        self.assertEqual(available_image_models("gemini"), [])


class TestGenerateImage(unittest.TestCase):
    def test_b64_json_path(self):
        payload = base64.b64encode(PNG_1PX).decode("ascii")

        def handler(request: httpx.Request) -> httpx.Response:
            self.assertTrue(str(request.url).endswith("/images/generations"))
            body = json.loads(request.content.decode())
            self.assertEqual(body["model"], "gpt-image-1")
            self.assertEqual(body["size"], "1024x1024")
            return httpx.Response(
                200,
                json={"data": [{"b64_json": payload, "revised_prompt": "a cat"}]},
            )

        png, revised = _run(_provider(handler).generate_image("a cat", "gpt-image-1"))
        self.assertEqual(png, PNG_1PX)
        self.assertEqual(revised, "a cat")

    def test_url_download_path(self):
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            if str(request.url).endswith("/images/generations"):
                return httpx.Response(200, json={"data": [{"url": "https://cdn.test/i.png"}]})
            return httpx.Response(200, content=PNG_1PX)

        png, revised = _run(_provider(handler).generate_image("a dog", "gpt-image-1"))
        self.assertEqual(png, PNG_1PX)
        self.assertEqual(revised, "")
        self.assertEqual(len(seen), 2)

    def test_http_error_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text="bad key")

        with self.assertRaises(ProviderError):
            _run(_provider(handler).generate_image("x", "gpt-image-1"))

    def test_empty_data_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": []})

        with self.assertRaises(ProviderError):
            _run(_provider(handler).generate_image("x", "gpt-image-1"))


class TestImageNote(unittest.TestCase):
    def test_roundtrip(self):
        note = image_note("a sunset over hills", "img-1-2.png")
        self.assertTrue(note.startswith("🖼️ Generated image"))
        parsed = parse_image_note(note)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed, ("a sunset over hills", "img-1-2.png"))

    def test_non_note_returns_none(self):
        self.assertIsNone(parse_image_note("hello world"))
        self.assertIsNone(parse_image_note(""))

    def test_long_prompt_truncated(self):
        note = image_note("x" * 500, "f.png")
        parsed = parse_image_note(note)
        assert parsed is not None
        self.assertTrue(len(parsed[0]) <= 200)


class TestSmartSearch(unittest.TestCase):
    def test_capability_word_matches(self):
        hay = row_search_text("openrouter", "moonshotai/kimi-k2.6:free")
        self.assertIn("vision", hay)
        # Text-only coder: no vision word, but reasoning nowhere either.
        hay2 = row_search_text("groq", "openai/gpt-oss-20b")
        self.assertNotIn("vision", hay2)

    def test_context_shorthands(self):
        hay = row_search_text("gemini", "gemini-3.8-flash")
        self.assertIn("1m", hay)
        self.assertIn("1000000", hay)
        self.assertIn("free", hay)

    def test_pricing_word(self):
        self.assertIn("paid", row_search_text("openai", "gpt-4o-mini"))

    def test_multiword_and_semantics(self):
        rows = iter_model_rows("qwen coder")
        self.assertTrue(rows)
        self.assertTrue(all("qwen" in f"{p} {m}".lower() for p, m, _f in rows))

    def test_vision_query_finds_vision_models(self):
        rows = iter_model_rows("vision", linked={"openai", "groq"})
        pids = {p for p, _m, _f in rows}
        self.assertIn("openai", pids)
        # Groq's only vision ID is the maverick model (rest are text-only).
        groq_rows = [(p, m) for p, m, _f in rows if p == "groq"]
        self.assertTrue(all("maverick" in m for _p, m in groq_rows))

    def test_ctx_query(self):
        rows = iter_model_rows("1m", linked={"gemini"})
        self.assertTrue(rows)


if __name__ == "__main__":
    unittest.main()
