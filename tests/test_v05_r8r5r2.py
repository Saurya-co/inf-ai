"""v0.5 R8+R5+R2 tests (stdlib unittest — no new deps, APK-safe).

Covers prompt-library CRUD/coercion/persistence, onboarding step-machine
+ first-run gate, and compare pair/guard/verdict helpers.
Run: python -m unittest discover -s tests -v
"""
import os
import tempfile
import unittest

from app.ui.controllers.compare import (
    default_pair,
    guard_text,
    loser_note,
    pair_from_json,
    pair_to_json,
    validate_pair,
)
from app.ui.widgets.onboarding import (
    WIZARD_STEPS,
    any_key_set,
    mark_onboarded,
    needs_onboarding,
    next_step,
    prev_step,
    step_dots,
    step_index,
)
from app.ui.widgets.prompt_library import (
    PROMPT_MAX,
    SavedPrompt,
    add_prompt,
    coerce_prompts,
    delete_prompt,
    load_prompts,
    prompts_from_json,
    prompts_to_json,
    save_prompts,
    update_prompt,
)


class TestPromptLibrary(unittest.TestCase):
    def test_coerce(self):
        raw = [{"title": "  T  ", "prompt": "  P  ", "provider": "gemini", "model": "m"},
               {"title": "", "prompt": "x"},
               {"title": "y", "prompt": ""},
               "junk",
               {"title": "T2", "prompt": "P2"}]
        out = coerce_prompts(raw)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0].title, "T")
        self.assertEqual(out[0].provider, "gemini")

    def test_coerce_caps_and_trims(self):
        raw = [{"title": f"t{i}", "prompt": "p"} for i in range(30)]
        self.assertEqual(len(coerce_prompts(raw)), PROMPT_MAX)
        self.assertEqual(coerce_prompts("nope"), [])
        long_p = {"title": "t", "prompt": "x" * 5000}
        self.assertLessEqual(len(coerce_prompts([long_p])[0].prompt), 1000)

    def test_json_roundtrip(self):
        items = [SavedPrompt("A", "do a", "gemini", "m")]
        self.assertEqual(prompts_from_json(prompts_to_json(items)), items)
        self.assertEqual(prompts_from_json("garbage"), [])

    def test_add_prepends_and_caps(self):
        items: list = []
        for i in range(PROMPT_MAX + 5):
            items = add_prompt(items, SavedPrompt(f"t{i}", "p"))
        self.assertEqual(len(items), PROMPT_MAX)
        self.assertEqual(items[0].title, f"t{PROMPT_MAX + 4}")

    def test_delete_update(self):
        items = [SavedPrompt("a", "1"), SavedPrompt("b", "2")]
        self.assertEqual([p.title for p in delete_prompt(items, 0)], ["b"])
        self.assertEqual(len(delete_prompt(items, 99)), 2)
        out = update_prompt(items, 1, SavedPrompt("B", "two"))
        self.assertEqual(out[1].title, "B")
        self.assertEqual(len(update_prompt(items, 9, SavedPrompt("X", "x"))), 2)

    def test_store_roundtrip(self):
        from app.data.key_store import KeyStore

        with tempfile.TemporaryDirectory() as d:
            old = os.getcwd()
            os.chdir(d)
            try:
                store = KeyStore()
                self.assertEqual(load_prompts(store), [])
                self.assertTrue(save_prompts(store, [SavedPrompt("T", "P")]))
                self.assertEqual(load_prompts(store), [SavedPrompt("T", "P", "", "")])
            finally:
                os.chdir(old)


class TestOnboarding(unittest.TestCase):
    def test_steps(self):
        self.assertEqual(len(WIZARD_STEPS), 4)
        self.assertEqual(next_step("provider"), "key")
        self.assertEqual(next_step("model"), "start")
        self.assertIsNone(next_step("start"))
        self.assertIsNone(prev_step("provider"))
        self.assertEqual(prev_step("start"), "model")
        self.assertEqual(step_index("bogus"), 0)

    def test_dots(self):
        dots = step_dots("key")
        self.assertEqual(dots.count("●"), 1)
        self.assertEqual(len(dots.split(" ")), 4)

    def test_gate(self):
        from app.data.key_store import KeyStore

        with tempfile.TemporaryDirectory() as d:
            old = os.getcwd()
            os.chdir(d)
            try:
                store = KeyStore()
                self.assertFalse(any_key_set(store))
                self.assertTrue(needs_onboarding(store))
                mark_onboarded(store)
                self.assertFalse(needs_onboarding(store))
                store.set_key("gemini", "sk-x")
                store.set("ui", "onboarded", "false")
                # Key present → no tour even when flag is false.
                self.assertTrue(any_key_set(store))
                self.assertFalse(needs_onboarding(store))
            finally:
                os.chdir(old)


class TestCompare(unittest.TestCase):
    PAIR = {"a": ["groq", "m1"], "b": ["gemini", "m2"]}

    def test_pair_json(self):
        self.assertEqual(pair_from_json(pair_to_json(self.PAIR)), self.PAIR)
        self.assertIsNone(pair_from_json("junk"))
        self.assertIsNone(pair_from_json('{"a": ["x", "y"]}'))
        self.assertIsNone(pair_from_json('{"a": ["", "y"], "b": ["x", "y"]}'))

    def test_default_pair(self):
        self.assertEqual(default_pair("g", "m"), {"a": ["g", "m"], "b": ["g", "m"]})

    def test_validate(self):
        ok, _ = validate_pair(self.PAIR, lambda pid: True)
        self.assertTrue(ok)
        ok, msg = validate_pair(self.PAIR, lambda pid: pid != "groq")
        self.assertFalse(ok)
        self.assertIn("side A", msg)
        ok, msg = validate_pair({"a": ["groq", "m1"], "b": ["nope", "m"]}, lambda pid: True)
        self.assertFalse(ok)
        self.assertIn("Unknown provider", msg)
        ok, msg = validate_pair({"a": ["groq", ""], "b": ["gemini", "m"]}, lambda pid: True)
        self.assertFalse(ok)
        self.assertIn("side A", msg)

    def test_guard_and_note(self):
        g = guard_text("hi", 2, 400)
        self.assertIn("twice", g)
        self.assertIn("400", g)
        self.assertIn("2 file", g)
        self.assertIn("Continue?", g)
        note = loser_note("a", "gemini", "flash")
        self.assertIn("gemini", note)
        self.assertIn("side A", note)


if __name__ == "__main__":
    unittest.main()
