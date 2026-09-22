"""Prompt library (v0.5 R8, Flet-only, MIT).

User-saved prompt presets: title + prompt + optional provider/model
binding. Same coercion discipline as starter_cards (caps, trims, drops
blanks). Persisted as JSON in KeyStore section 'ui', key 'prompts'
(same pattern as model recents). Pure list ops are unit-tested.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

PROMPT_MAX = 20
PROMPT_TITLE_MAX = 40
PROMPT_TEXT_MAX = 1000


@dataclass(frozen=True)
class SavedPrompt:
    title: str
    prompt: str
    provider: str = ""
    model: str = ""


def coerce_prompts(raw: object) -> list[SavedPrompt]:
    """Validate raw JSON-ish data into SavedPrompts (max PROMPT_MAX)."""
    if not isinstance(raw, list):
        return []
    out: list[SavedPrompt] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()[:PROMPT_TITLE_MAX]
        prompt = str(item.get("prompt", "")).strip()[:PROMPT_TEXT_MAX]
        if not title or not prompt:
            continue
        out.append(
            SavedPrompt(
                title=title,
                prompt=prompt,
                provider=str(item.get("provider", ""))[:40],
                model=str(item.get("model", ""))[:80],
            )
        )
    return out[:PROMPT_MAX]


def prompts_to_json(items: list[SavedPrompt]) -> str:
    try:
        return json.dumps(
            [{"title": p.title, "prompt": p.prompt,
              "provider": p.provider, "model": p.model} for p in items],
            ensure_ascii=False,
        )
    except Exception:
        return "[]"


def prompts_from_json(raw: str) -> list[SavedPrompt]:
    try:
        return coerce_prompts(json.loads(raw or "[]"))
    except Exception:
        return []


def add_prompt(items: list[SavedPrompt], prompt: SavedPrompt) -> list[SavedPrompt]:
    """Prepend (most-recent-first), capped at PROMPT_MAX."""
    return [prompt, *[p for p in items or [] if p != prompt]][:PROMPT_MAX]


def delete_prompt(items: list[SavedPrompt], idx: int) -> list[SavedPrompt]:
    out = list(items or [])
    try:
        if 0 <= int(idx) < len(out):
            del out[int(idx)]
    except Exception:
        pass
    return out


def update_prompt(items: list[SavedPrompt], idx: int, prompt: SavedPrompt) -> list[SavedPrompt]:
    out = list(items or [])
    try:
        if 0 <= int(idx) < len(out):
            out[int(idx)] = prompt
    except Exception:
        pass
    return out


def load_prompts(store) -> list[SavedPrompt]:
    try:
        return prompts_from_json(store.get("ui", "prompts", "[]"))
    except Exception:
        return []


def save_prompts(store, items: list[SavedPrompt]) -> bool:
    try:
        store.set("ui", "prompts", prompts_to_json(items))
        return True
    except Exception:
        return False
