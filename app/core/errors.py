"""Provider errors with user-friendly messages (no key leakage)."""

import re as _re

_URL_RE = _re.compile(r"https?://\S+|www\.\S+")
_PATH_RE = _re.compile(r"([A-Za-z]:\\[^\s\"']+|/[A-Za-z0-9_.\-/]+/[A-Za-z0-9_.\-/]+)")


def _sanitize_detail(detail: str) -> str:
    """Strip URLs/paths from server-controlled text (anti-phishing)."""
    try:
        s = _URL_RE.sub("[link removed]", detail or "")
        s = _PATH_RE.sub("[path removed]", s)
        return s.strip()[:160]
    except Exception:
        return ""


class ProviderError(Exception):
    def __init__(self, kind: str, detail: object = "") -> None:
        self.kind = kind if isinstance(kind, str) and kind else "unknown"
        self.detail = detail if isinstance(detail, str) else (str(detail) if detail else "")
        super().__init__(self.detail or self.kind)

    def friendly(self) -> str:
        base = {
            "auth": "Invalid API key (401). Paste a fresh key for this provider.",
            "not_found": "Model or endpoint not found (404). Check model name / base URL.",
            "rate_limit": "Rate limited (429). Free tiers throttle — wait a minute and retry. (OpenRouter :free caps at ~20/min and 50–1000/day.)",
            "network": "Network error. Check internet and retry.",
            "bad_request": "Request rejected (400). Try a shorter message or another model.",
            "too_large": "Request too large (413). Remove/shorten attachments and retry.",
            "unknown": "Provider error. Try again or switch model.",
        }.get(self.kind, "Provider error. Try again or switch model.")
        detail = self.detail if isinstance(self.detail, str) else ""
        if detail and self.kind in ("bad_request", "too_large", "unknown"):
            # Surface server detail sanitized (no URLs/paths/keys).
            clean = _sanitize_detail(detail)
            return f"{base} ({clean})" if clean else base
        return base


def map_http_status(status: object) -> str:
    try:
        code = int(status)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "unknown"
    if code == 401 or code == 403:
        return "auth"
    if code == 404:
        return "not_found"
    if code == 429:
        return "rate_limit"
    if code == 413:
        return "too_large"
    if code in (408, 502, 503, 504):
        # Timeouts / transient gateway failures — retryable like network.
        return "network"
    if 400 <= code < 500:
        return "bad_request"
    return "unknown"
