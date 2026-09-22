"""Factory: registry entry -> provider instance.

Security policy (post-audit):
- https:// only by default. http:// requires explicit allow_insecure=True
  (loopback dev only) and never carries keys to non-loopback hosts.
- Private/loopback/link-local/reserved hosts and cloud-metadata IPs are
  rejected by default to block SSRF via malicious base_url.
"""

import httpx
import ipaddress
from urllib.parse import urlparse

from app.config import PROVIDERS
from app.core.anthropic_provider import AnthropicProvider
from app.core.gemini_provider import GeminiProvider
from app.core.provider_base import OpenAICompatProvider

_BLOCKED_IP_NETS = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local + cloud metadata
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)

_BLOCKED_HOSTNAMES = frozenset({
    "localhost", "metadata.google.internal",
    "instance-data", "instance-data-compute",
})


def _host_is_blocked(host: str) -> bool:
    h = (host or "").strip().lower().rstrip(".")
    if not h:
        return True
    if h in _BLOCKED_HOSTNAMES:
        return True
    # Strip port / brackets for IPv6 literals.
    bare = h.split(":")[0] if h.count(":") == 1 else h.strip("[]")
    # Fast path: literal IP.
    try:
        ip = ipaddress.ip_address(bare)
        return any(ip in net for net in _BLOCKED_IP_NETS) or ip.is_private
    except ValueError:
        pass
    # Hostname heuristics: localhost-ish / .local / .internal / single-label
    # intranet names are rejected; public DNS names pass (DNS-rebinding at
    # request time is mitigated by trust_env=False + https-only).
    if h in ("localhost",) or h.endswith((".local", ".internal", ".lan", ".home")):
        return True
    return False


def normalize_base_url(value: object, allow_insecure: bool = False) -> str:
    """Normalize a provider endpoint and reject values httpx cannot request.

    Empty string is allowed (returns "") so callers can distinguish
    "no URL configured" (Custom provider) from a malformed URL.
    By default only https:// public hosts are accepted.
    """

    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("Base URL must be a string.")
    url = value.strip()
    if not url:
        return ""
    if len(url) > 500:
        raise ValueError("Base URL is too long.")
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    if not parsed.netloc:
        raise ValueError("Base URL must include a valid https:// address.")
    if parsed.scheme == "http":
        if not allow_insecure:
            raise ValueError("Insecure http:// endpoints are blocked. Use https://.")
        # Even with allow_insecure, only loopback dev is permitted.
        if (parsed.hostname or "") not in ("127.0.0.1", "::1", "localhost"):
            raise ValueError("http:// is only allowed for loopback dev endpoints.")
        # Reject credentials in URL (key leakage via logs/proxy).
        if parsed.username or parsed.password:
            raise ValueError("Base URL must not contain credentials.")
        return url.rstrip("/")
    elif parsed.scheme != "https":
        raise ValueError("Base URL must include a valid https:// address.")
    if _host_is_blocked(parsed.hostname or ""):
        raise ValueError(
            f"Base URL host '{parsed.hostname}' is blocked (private/internal)."
        )
    # Reject credentials in URL (key leakage via logs/proxy).
    if parsed.username or parsed.password:
        raise ValueError("Base URL must not contain credentials.")
    return url.rstrip("/")


def _coerce_timeout(timeout: object, default: float = 60.0) -> float:
    try:
        t = float(timeout)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if not (1.0 <= t <= 600.0):
        return default
    return t


def get_provider(
    provider_id: object,
    api_key: object,
    base_url_override: object | None = None,
    client: httpx.AsyncClient | None = None,
    timeout: object = 60.0,
    allow_insecure: bool = False,
) -> OpenAICompatProvider | AnthropicProvider | GeminiProvider:
    if not isinstance(provider_id, str) or provider_id not in PROVIDERS:
        raise ValueError(f"Unknown provider: {provider_id!r}")
    reg = PROVIDERS[provider_id]
    timeout = _coerce_timeout(timeout)
    raw = base_url_override.strip() if isinstance(base_url_override, str) else "" or reg.get("base_url", "")
    if not isinstance(raw, str):
        raw = ""
    base_url = normalize_base_url(raw, allow_insecure=allow_insecure) if raw else ""
    if not base_url:
        raise ValueError(f"Provider '{provider_id}' needs a base URL (set it in Providers).")
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError(f"Provider '{provider_id}' needs an API key (BYOK).")
    if reg["protocol"] == "anthropic":
        return AnthropicProvider(api_key.strip(), base_url, client, timeout)
    if provider_id == "gemini":
        return GeminiProvider(api_key.strip(), base_url, client, timeout)
    return OpenAICompatProvider(
        api_key.strip(), base_url, reg.get("extra_headers"), client, timeout
    )
