"""Onboarding wizard helpers (v0.5 R5, Flet-only, MIT).

First-run setup tour: provider → key (+Test) → free model → starter.
Pure step-machine logic is unit-tested; the sheet lives in main.py and
reuses the existing Test/model-sheet/starter code paths (no duplicated
provider logic). Completion persists KeyStore ui.onboarded=true.
"""

from __future__ import annotations

WIZARD_STEPS: tuple[str, ...] = ("provider", "key", "model", "start")


def step_index(step: str) -> int:
    try:
        return list(WIZARD_STEPS).index(step)
    except Exception:
        return 0


def next_step(step: str) -> str | None:
    """Next step id, or None when the tour is complete."""
    i = step_index(step) + 1
    return WIZARD_STEPS[i] if 0 <= i < len(WIZARD_STEPS) else None


def prev_step(step: str) -> str | None:
    """Previous step id, or None when already first."""
    i = step_index(step) - 1
    return WIZARD_STEPS[i] if i >= 0 else None


def step_dots(step: str) -> str:
    """'● ○ ○ ○' style progress for the sheet header."""
    cur = step_index(step)
    return " ".join("●" if i == cur else "○" for i in range(len(WIZARD_STEPS)))


def any_key_set(store) -> bool:
    """True when at least one provider key is stored."""
    try:
        from app.config import PROVIDER_IDS

        return any(bool(store.get_key(pid).strip()) for pid in PROVIDER_IDS)
    except Exception:
        return False


def needs_onboarding(store) -> bool:
    """First-run gate: not onboarded AND no keys yet."""
    try:
        if (store.get("ui", "onboarded", "false") or "").lower() == "true":
            return False
    except Exception:
        pass
    return not any_key_set(store)


def mark_onboarded(store) -> None:
    try:
        store.set("ui", "onboarded", "true")
    except Exception:
        pass
