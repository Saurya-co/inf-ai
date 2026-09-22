"""RAG source-viewer helpers (v0.5 R4, Flet-only, MIT).

Pure logic for turning `[file §n]` citation labels into a source viewer:
label parsing, excerpt-span search, relevance score banding. Dialog
assembly lives in main.py; span rendering uses ft.TextSpan (built-in).
"""

from __future__ import annotations

import re

_CITE_RE = re.compile(r"^(?P<file>.+?)\s*§\s*(?P<n>\d+)\s*$")


def parse_citation_label(label: str) -> tuple[str, int | None]:
    """Split 'report.pdf §1' → ('report.pdf', 0-based chunk idx).

    Returns (stripped_label, None) when no §n suffix is present.
    """
    m = _CITE_RE.match((label or "").strip())
    if not m:
        return (label or "").strip(), None
    try:
        idx = max(0, int(m.group("n")) - 1)
    except Exception:
        return m.group("file").strip(), None
    return m.group("file").strip(), idx


def find_excerpt_span(chunk: str, terms: list[str]) -> tuple[int, int]:
    """First occurrence span of the longest matching term (case-insensitive).

    Terms shorter than 4 chars are ignored (stop-word noise). Returns
    (0, 0) when nothing matches.
    """
    text = chunk or ""
    lowered = text.casefold()
    best: tuple[int, int] | None = None
    for raw in terms or []:
        t = (raw or "").strip().casefold()
        if len(t) < 4:
            continue
        i = lowered.find(t)
        if i >= 0 and (best is None or len(t) > best[1] - best[0]):
            best = (i, i + len(t))
    return best or (0, 0)


def score_bands(scores: list[float]) -> dict[str, int]:
    """Bucket TF-IDF cosine scores (normalized by max) into high/med/low."""
    bands = {"high": 0, "med": 0, "low": 0}
    vals = []
    for s in scores or []:
        try:
            vals.append(float(s))
        except Exception:
            pass
    if not vals:
        return bands
    top = max(vals)
    if top <= 0:
        bands["low"] = len(vals)
        return bands
    for s in vals:
        frac = s / top
        if frac >= 0.6:
            bands["high"] += 1
        elif frac >= 0.3:
            bands["med"] += 1
        else:
            bands["low"] += 1
    return bands


def bands_tooltip(bands: dict[str, int]) -> str:
    """'Why these' explainer for the RAG status line tooltip."""
    try:
        h, m, lo = int(bands.get("high", 0)), int(bands.get("med", 0)), int(bands.get("low", 0))
    except Exception:
        return "Top excerpts by on-device TF-IDF rank."
    total = h + m + lo
    if total <= 0:
        return "Top excerpts by on-device TF-IDF rank."
    return (
        f"On-device TF-IDF rank ({total} excerpt(s)): "
        f"{h} strong, {m} related, {lo} weak match."
    )
