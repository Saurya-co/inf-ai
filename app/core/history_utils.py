"""v0.2.0: pure chat-history helpers extracted from main.py.

These were inline closures in main() — now importable + unit-tested.
All functions are side-effect free.
"""

from __future__ import annotations


def _part_text(part: object) -> str:
    if not isinstance(part, dict):
        return ""
    text = part.get("type") == "text" and part.get("text", "")
    return text if isinstance(text, str) else (str(text) if text else "")


def user_text_of(content: object) -> tuple[str, bool]:
    """Return (text, has_images) for a stored user message."""
    if isinstance(content, str):
        return content, False
    if not isinstance(content, list):
        return "", False
    texts = [_part_text(p) for p in content]
    texts = [t for t in texts if t]
    has_images = any(
        isinstance(p, dict) and p.get("type") in ("image_url", "image") for p in content
    )
    return "\n".join(texts), has_images


def assistant_text_of(content: object) -> str:
    """Return plain text for a stored assistant message."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(t for t in (_part_text(p) for p in content) if t)


def short_title(prompt: object, limit: int = 40) -> str:
    """Conversation title from first prompt (matches old ensure_conv logic)."""
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 40
    limit = max(4, min(200, limit))
    if not isinstance(prompt, str):
        return "New chat"
    title = prompt.strip().replace("\n", " ")[:limit]
    return title or "New chat"


def filter_conversations(convs: object, query: object) -> list[dict]:
    """Filter drawer rows by title/provider/model (case-insensitive)."""
    if not isinstance(convs, list):
        return []
    q = query.strip().lower() if isinstance(query, str) else ""
    if not q:
        return list(convs)
    out = []
    for c in convs:
        if not isinstance(c, dict):
            continue
        title = c.get('title') if isinstance(c.get('title'), str) else ""
        prov = c.get('provider') if isinstance(c.get('provider'), str) else ""
        mod = c.get('model') if isinstance(c.get('model'), str) else ""
        hay = f"{title or ''} {prov} {mod}".lower()
        if q in hay:
            out.append(c)
    return out
