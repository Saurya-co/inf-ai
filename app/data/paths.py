"""Local app-data directory (INF ai, stdlib only).

Why this exists: the Flet desktop runner launches with CWD set to
``C:\\WINDOWS\\System32``, so the old ``os.path.join(os.getcwd(), "data")``
pattern died with ``WinError 5`` (access denied) — history went off and
anything depending on it (drawer search included) broke.

Resolution order (first usable wins):
1. ``INF_AI_DATA_DIR`` env var, when set (tests / packaging override).
2. ``<cwd>/data`` when the current directory is writable — preserves the
   long-standing dev-loop layout and the test isolation that chdirs to a
   temp dir.
3. ``<app_root>/data`` (folder containing ``main.py``) when writable.
4. Per-user fallback: ``%LOCALAPPDATA%\\INF ai`` on Windows,
   ``~/.inf_ai`` elsewhere.
"""

from __future__ import annotations

import os
import sys

APP_DIR_NAME = "INF ai"
ENV_OVERRIDE = "INF_AI_DATA_DIR"


def _writable_dir(path: object) -> str | None:
    """Return path if it can be created + written to, else None."""
    if not isinstance(path, str) or not path.strip() or len(path) > 500:
        return None
    try:
        os.makedirs(path, exist_ok=True)
        # Refuse to use a file-as-dir (makedirs may succeed on odd mounts).
        if not os.path.isdir(path):
            return None
        probe = os.path.join(path, ".write_test")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        try:
            os.remove(probe)
        except OSError:
            pass
        return path
    except (OSError, PermissionError, TypeError, ValueError):
        return None


def _app_root() -> str:
    """Folder containing main.py (parent of the ``app`` package)."""
    if getattr(sys, "frozen", False):  # bundled executable
        try:
            return os.path.dirname(os.path.abspath(sys.executable))
        except Exception:
            pass
    here = os.path.abspath(__file__)  # <root>/app/data/paths.py
    for _ in range(3):
        here = os.path.dirname(here)
    return here


def _user_dir() -> str:
    try:
        local = (os.environ.get("LOCALAPPDATA") or "").strip()
    except Exception:
        local = ""
    if local:
        return os.path.join(local, APP_DIR_NAME)
    try:
        return os.path.join(os.path.expanduser("~"), ".inf_ai")
    except Exception:
        return os.path.join(os.getcwd(), "data")


def app_data_dir() -> str:
    """Best writable app-data dir. Always returns a path (may not exist)."""
    try:
        override = (os.environ.get(ENV_OVERRIDE) or "").strip()
    except Exception:
        override = ""
    if override:
        # Normalize: resolve .. / symlinks, cap length, reject file-as-dir.
        # Symlink escape guard: realpath must equal normpath (no link hop)
        # and must not point at sensitive roots.
        try:
            norm = os.path.abspath(os.path.normpath(override))
            real = os.path.realpath(norm)
        except Exception:
            norm, real = "", ""
        if norm and len(norm) <= 500 and norm == real:
            lowered = norm.lower()
            if not lowered.startswith(("/etc", "/proc", "/sys", "c:\\windows")):
                ok = _writable_dir(norm)
                if ok is not None:
                    return ok
    for candidate in (
        os.path.join(os.getcwd(), "data"),
        os.path.join(_app_root(), "data"),
        _user_dir(),
    ):
        ok = _writable_dir(candidate)
        if ok is not None:
            return ok
    # Last resort: today's behavior — callers already tolerate failure.
    return os.path.join(os.getcwd(), "data")
