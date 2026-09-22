"""Chat orchestration (P2 core, P3 multimodal): resolve BYOK target, stream."""

from app.config import PROVIDERS, context_limit
from app.core.attachment_service import build_chat_messages as _build_mm
from app.core.provider_factory import get_provider, normalize_base_url
from app.core.types import Attachment, Message
from app.data.key_store import KeyStore


def estimate_tokens(text: object) -> int:
    """Rough estimate (~4 chars/token) for preflight + status line.

    Byte-aware: CJK/emoji/base64 undercount len//4, so take the max with
    utf8_len//3 to avoid meter bypass on non-Latin docs.
    """
    if not isinstance(text, str):
        return 1
    try:
        ub = len(text.encode("utf-8"))
    except Exception:
        ub = len(text)
    return max(1, len(text) // 4, ub // 3)


# Conservative per-image estimate for context accounting (OpenAI-class
# high-detail images cost ~765-1100 tokens; other providers vary).
# Overestimating is safe: it only trips compaction/metering earlier.
IMAGE_TOKEN_ESTIMATE = 1024


def _image_parts(content: list) -> int:
    n = 0
    for part in content:
        if not isinstance(part, dict):
            continue
        ptype = part.get("type", "")
        if ptype in ("image_url", "image"):
            n += 1
    return n


def message_tokens(message: Message) -> int:
    try:
        content = message.content
    except AttributeError:
        return 1
    if isinstance(content, str):
        return estimate_tokens(content)
    if not isinstance(content, list):
        return 1
    return estimate_tokens(
        "\n".join(
            str(part.get("text", "")) if isinstance(part.get("text", ""), str) else ""
            for part in content
            if isinstance(part, dict)
        )
    ) + IMAGE_TOKEN_ESTIMATE * _image_parts(content)


def should_compact(messages: list[Message], model: str, threshold: float = 0.8) -> bool:
    return sum(message_tokens(message) for message in messages) >= int(
        context_limit(model) * threshold
    )


def compaction_target_count(messages: list[Message], model: str) -> int:
    """Keep recent turns while leaving room for a summary and the next reply."""
    budget = max(1024, int(context_limit(model) * 0.55))
    total = 0
    keep_from = len(messages)
    for index in range(len(messages) - 1, -1, -1):
        total += message_tokens(messages[index])
        if total > budget:
            break
        keep_from = index
    return keep_from


def _safe_store_str(store: KeyStore, section: str, field: str, default: str = "") -> str:
    try:
        val = store.get(section, field, default)
    except Exception:
        return default
    return val if isinstance(val, str) else default


def resolve_chat_target(store: KeyStore) -> tuple[str, str, str, str]:
    """Return (provider_id, model, base_url, api_key) or raise ValueError with UI text."""
    provider_id = (_safe_store_str(store, "chat", "provider", "gemini").strip() or "gemini")
    if provider_id not in PROVIDERS:
        raise ValueError(f"Unknown provider '{provider_id}'. Pick one in the model bar.")
    reg = PROVIDERS[provider_id]
    if not isinstance(reg, dict):
        raise ValueError("Provider registry is corrupt — restart the app.")
    model = _safe_store_str(store, "chat", "model", "").strip() or str(reg.get("default_model", "") or "")
    raw_base_url = _safe_store_str(store, provider_id, "base_url", "").strip() or str(reg.get("base_url", "") or "")
    try:
        base_url = normalize_base_url(raw_base_url)
    except ValueError as e:
        raise ValueError(f"Invalid base URL for {reg.get('display_name', provider_id)}: {e}") from e
    try:
        api_key = store.get_key(provider_id)
    except Exception:
        api_key = ""
    api_key = api_key.strip() if isinstance(api_key, str) else ""
    if not api_key:
        raise ValueError(
            f"No API key for {reg.get('display_name', provider_id)}. Open Providers tab → paste key → Test."
        )
    if not model:
        raise ValueError(f"No model for {reg.get('display_name', provider_id)}. Type one in the model bar.")
    if not base_url:
        raise ValueError(f"No base URL for {reg.get('display_name', provider_id)}. Set it in Providers tab.")
    return provider_id, model, base_url, api_key


def get_chat_provider(store: KeyStore):
    provider_id, model, base_url, api_key = resolve_chat_target(store)
    return get_provider(provider_id, api_key, base_url), model


def build_messages(history: list[Message], new_text: str) -> list[Message]:
    return [*history, Message("user", new_text)]


def build_multimodal_messages(
    store: KeyStore,
    history: list[Message],
    prompt: str,
    attachments: list[Attachment],
    vision_override: bool = False,
) -> tuple[list[Message], str, str]:
    """Resolve target + merge prompt/attachments. Returns (messages, pid, model).

    Raises ValueError with UI-ready text (missing key, vision mismatch, ...).
    """
    provider_id, model, _base_url, _api_key = resolve_chat_target(store)
    return (
        _build_mm(history, prompt, attachments, provider_id, model,
                  vision_override=vision_override),
        provider_id,
        model,
    )
