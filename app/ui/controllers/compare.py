"""Multi-model compare helpers (v0.5 R2, Flet-only, MIT).

Pure logic for side-by-side answers: slot-pair persistence/validation,
cost-guard text, verdict note. Streaming orchestration lives in main.py
and reuses the normal provider/chat_stream path per slot. Explicit
non-goals: more than 2 slots, cross-model image diffing, RAG in compare
(staged docs inject as plain text), auto-compaction (skipped).
"""

from __future__ import annotations

import json

COMPARE_SLOTS: tuple[str, ...] = ("a", "b")


def default_pair(pid: str, model: str) -> dict[str, list[str]]:
    """Initial pair: both slots start on the current chat target."""
    return {"a": [pid, model], "b": [pid, model]}


def pair_to_json(pair: dict) -> str:
    try:
        return json.dumps(
            {"a": [str(pair["a"][0]), str(pair["a"][1])],
             "b": [str(pair["b"][0]), str(pair["b"][1])]},
            ensure_ascii=False,
        )
    except Exception:
        return "{}"


def pair_from_json(raw: str) -> dict[str, list[str]] | None:
    """Parse a persisted pair; None when malformed/incomplete."""
    try:
        data = json.loads(raw or "")
        if not isinstance(data, dict):
            return None
        out: dict[str, list[str]] = {}
        for slot in COMPARE_SLOTS:
            item = data.get(slot)
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                return None
            pid, model = str(item[0]).strip(), str(item[1]).strip()
            if not pid or not model:
                return None
            out[slot] = [pid, model]
        return out
    except Exception:
        return None


def validate_pair(pair: dict, has_key) -> tuple[bool, str]:
    """Check both slots are set, known, and keyed. Returns (ok, message)."""
    try:
        from app.config import PROVIDERS

        for slot in COMPARE_SLOTS:
            item = (pair or {}).get(slot)
            if not item or len(item) != 2:
                return False, f"Pick a model for side {slot.upper()} first."
            pid, model = str(item[0]).strip(), str(item[1]).strip()
            if pid not in PROVIDERS:
                return False, f"Unknown provider '{pid}' on side {slot.upper()}."
            if not model:
                return False, f"Pick a model for side {slot.upper()} first."
            try:
                keyed = bool(has_key(pid))
            except Exception:
                keyed = False
            if not keyed:
                name = PROVIDERS[pid].get("display_name", pid)
                return False, f"No API key for {name} (side {slot.upper()}). See Providers tab."
        return True, ""
    except Exception as e:  # noqa: BLE001
        return False, f"Compare setup failed: {e}"


def guard_text(prompt: str, staged_count: int, in_estimate: int) -> str:
    """Cost-guard dialog body: names the 2× send explicitly."""
    return (
        f"Compare sends this prompt twice (side A + side B)"
        f" — ~{max(1, int(in_estimate))} tokens in each."
        + (f" {int(staged_count)} file(s) go to both sides." if staged_count else "")
        + " Continue?"
    )


def loser_note(winner_side: str, loser_pid: str, loser_model: str) -> str:
    other = "B" if winner_side == "a" else "A"
    return f"Compared {loser_pid} / {loser_model} (side {other}) — kept side {winner_side.upper()}."
