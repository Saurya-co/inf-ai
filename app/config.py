"""Provider registry — single source of truth for v0.3.0.

Edit models here when providers rename them (Groq/OpenRouter churn often).
UI always allows '+ Custom model' on top of these defaults.

v0.3.0 notes (Sept 2026 refresh):
- Groq: qwen3-32b + llama-4-scout retired 07/17/26 — lineup is now
  gpt-oss-20b/120b + qwen3.6-27b + qwen3.8-27b (all text-only; vision only
  on *vision*/llava IDs).
- Anthropic: new ID scheme — claude-haiku-4-5 (default, cheapest),
  claude-sonnet-5, claude-opus-5 (1M ctx on Sonnet 5 / Opus 5).
- Gemini: 3.8-flash GA (1M in / 65K out) is the default; 2.5-flash kept.
- OpenRouter :free lineup rotated — GLM 5.2, MiniMax M3, Qwen3-Coder,
  plus the openrouter/free auto-router as resilient default.
- Together free tier uses `-Free` suffixed IDs (paid Turbo IDs bill credits).

v0.6 notes (model-sheet completeness):
- Offline registry expanded to the full known free lineup per provider —
  the Model Sheet must never hide models a provider actually offers.
  (Live /models refresh still replaces these once a key is set.)
"""

APP_VERSION = "0.6.0"

PROVIDERS: dict[str, dict] = {
    "gemini": {
        "display_name": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "protocol": "openai",
        "free": True,
        "models": [
            "gemini-3.8-flash",
            "gemini-3.8-pro",
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
        ],
        "default_model": "gemini-3.8-flash",
    },
    "groq": {
        "display_name": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "protocol": "openai",
        "free": True,
        "models": [
            "openai/gpt-oss-20b",
            "openai/gpt-oss-120b",
            "qwen/qwen3.6-27b",
            "qwen/qwen3.8-27b",
            "moonshotai/kimi-k2-instruct-0905",
            "meta-llama/llama-4-maverick-17b-128e-instruct",
        ],
        "default_model": "openai/gpt-oss-20b",
    },
    "openrouter": {
        "display_name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "protocol": "openai",
        "free": True,
        "models": [
            "openrouter/free",
            "z-ai/glm-5.2:free",
            "minimax/minimax-m3:free",
            "qwen/qwen3-coder-480b:free",
            "moonshotai/kimi-k2.6:free",
            "deepseek/deepseek-r1:free",
            "meta-llama/llama-3.3-70b-instruct:free",
            "google/gemma-3-27b-it:free",
            "mistralai/mistral-small-3.2-24b-instruct:free",
            "qwen/qwen3-235b-a22b:free",
        ],
        "default_model": "openrouter/free",
        "extra_headers": {"HTTP-Referer": "com.saurya.multiai", "X-Title": "INF ai"},
    },
    "together": {
        "display_name": "Together AI",
        "base_url": "https://api.together.xyz/v1",
        "protocol": "openai",
        "free": True,
        "models": [
            "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free",
            "deepseek-ai/DeepSeek-R1-Distill-Llama-70B-free",
            "meta-llama/Llama-Vision-Free",
            "meta-llama/Llama-4-Scout-Free",
            "Qwen/Qwen2.5-72B-Instruct-Turbo-Free",
        ],
        "default_model": "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free",
    },
    "huggingface": {
        "display_name": "HuggingFace",
        "base_url": "https://api-inference.huggingface.co/v1",
        "protocol": "openai",
        "free": True,
        "models": [
            "meta-llama/Llama-3.3-70B-Instruct",
            "Qwen/Qwen2.5-72B-Instruct",
            "mistralai/Mistral-7B-Instruct-v0.3",
            "microsoft/Phi-4-mini-instruct",
            "HuggingFaceH4/zephyr-7b-beta",
        ],
        "default_model": "meta-llama/Llama-3.3-70B-Instruct",
    },
    "deepseek": {
        "display_name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "protocol": "openai",
        "free": False,
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "default_model": "deepseek-chat",
    },
    "openai": {
        "display_name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "protocol": "openai",
        "free": False,
        "models": ["gpt-4o-mini", "gpt-5-mini", "gpt-5", "gpt-4o"],
        "default_model": "gpt-4o-mini",
    },
    "anthropic": {
        "display_name": "Anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "protocol": "anthropic",
        "free": False,
        "models": ["claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5"],
        "default_model": "claude-haiku-4-5",
    },
    "custom": {
        "display_name": "Custom (OpenAI-compat)",
        "base_url": "",
        "protocol": "openai",
        "free": False,
        "models": [],
        "default_model": "",
    },
}

PROVIDER_IDS: list[str] = list(PROVIDERS.keys())
# Populated after a successful provider `/models` request. Registry values remain
# the offline fallback so the UI is still usable before a key is configured.
LIVE_MODELS: dict[str, list[str]] = {}
import threading as _threading

_LIVE_MODELS_LOCK = _threading.RLock()


def available_models(provider_id: str) -> list[str]:
    with _LIVE_MODELS_LOCK:
        live = LIVE_MODELS.get(provider_id)
    if live:
        return list(live)
    reg = PROVIDERS.get(provider_id, {})
    models = reg.get("models", []) if isinstance(reg, dict) else []
    return list(models or [])


def set_live_models(provider_id: str, models: object) -> None:
    if not isinstance(provider_id, str) or not provider_id:
        return
    if isinstance(models, str):
        # A bare string is one model id, not a char sequence.
        models = [models]
    if not isinstance(models, (list, tuple, set)):
        return
    clean = [m.strip() for m in models if isinstance(m, str) and m.strip()][:200]
    if not clean:
        return
    with _LIVE_MODELS_LOCK:
        LIVE_MODELS[provider_id] = list(dict.fromkeys(clean))

# ---- P3: attachments ----
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_DOC_BYTES = 15 * 1024 * 1024
MAX_DOC_CHARS = 12_000
MAX_IMAGE_DIM = 1568  # Pillow downscale target (when available)
DEFAULT_CONTEXT_LIMIT = 8192
CONTEXT_LIMITS: dict[str, int] = {
    "gemini-3.8-flash": 1_000_000,
    "gemini-3.8-pro": 1_000_000,
    "gemini-2.5-flash": 1_000_000,
    "gemini-2.5-pro": 1_000_000,
    "gemini-2.0-flash": 1_000_000,
    "gemini-2.0-flash-lite": 1_000_000,
    "gemini-1.5-flash": 1_000_000,
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-5-mini": 400_000,
    "gpt-5": 400_000,
    "gpt-oss-20b": 131_072,
    "gpt-oss-120b": 131_072,
    "qwen3.6-27b": 131_072,
    "qwen3.8-27b": 131_042,
    "qwen3-coder": 262_000,
    "qwen3-235b": 262_000,
    "kimi-k2": 262_000,
    "glm-5": 200_000,
    "minimax-m3": 200_000,
    "llama-4-scout": 131_072,  # retired 07/17/26 — kept for history compat
    "llama-4-maverick": 131_072,
    "llama-3.3-70b": 131_072,
    "qwen3-32b": 40_960,  # retired 07/17/26 — kept for history compat
    "claude-haiku-4-5": 200_000,
    "claude-sonnet-5": 1_000_000,
    "claude-opus-5": 1_000_000,
    "claude-3-5-haiku-20241022": 200_000,  # superseded — history compat
    "claude-sonnet-4": 200_000,  # superseded — history compat
    "deepseek-chat": 64_000,
    "deepseek-reasoner": 64_000,
    "deepseek-r1-distill": 32_768,
    "deepseek-r1": 64_000,
    "llama-3.3-70b-versatile": 131_072,  # retired 08/16/26 — history compat
    "llama-3.1-8b-instant": 131_072,  # retired 08/16/26 — history compat
    "gemma-3": 128_000,
    "mistral-small": 128_000,
    "mistral-7b": 32_768,
    "qwen2.5-72b": 32_768,
    "phi-4": 128_000,
}
ALLOWED_IMAGE_EXTS = {"png", "jpg", "jpeg", "webp"}
ALLOWED_DOC_EXTS = {"txt", "md", "pdf"}

# ---- Image output (text-to-image, OpenAI /images/generations shape) ----
# v0.6: models that DRAW, not chat. Kept separate from the chat registry —
# picking one as a chat model would break replies. Only providers whose
# endpoint speaks POST {base}/images/generations are listed here (OpenAI,
# Together, and any Custom OpenAI-compat server; Gemini/Anthropic use
# different image APIs and stay chat-only for now).
IMAGE_MODELS: dict[str, list[str]] = {
    "openai": ["gpt-image-1", "dall-e-3"],
    "together": [
        "black-forest-labs/FLUX.1-schnell-Free",
        "black-forest-labs/FLUX.1-dev",
    ],
    "custom": [],
}
IMAGE_SIZES: tuple[str, ...] = ("1024x1024", "1024x1792", "1792x1024")
IMAGE_GEN_TIMEOUT = 180.0


def supports_image_gen(provider_id: str) -> bool:
    """True when the provider can render images (v0.6 image output)."""
    return provider_id in IMAGE_MODELS


def available_image_models(provider_id: str) -> list[str]:
    """Image-gen model IDs for a provider (registry; editable in the dialog)."""
    return list(IMAGE_MODELS.get(provider_id, []) or [])

# Providers whose models only do vision when the model name says so.
# NOTE: substring gating is a heuristic — registries and live /models lists
# churn. Anything not matched here is ALLOWED (default True below) so the
# app never wrongly stops the user; truly text-only IDs go in
# TEXT_ONLY_MODELS, and per-model user overrides win over both.
VISION_BY_SUBSTRING: dict[str, tuple[str, ...]] = {
    "groq": ("vision", "llava", "-vl", "maverick", "scout"),
    "together": ("vision", "llava", "-vl", "maverick", "scout"),
    # openrouter deliberately absent: it routes over hundreds of models
    # (claude/gpt-4o/gemini/qwen-vl/gemma-3/llama-3.2-vision/...) — gating
    # by substring misfires, so unknown IDs are attempted.
}

# Explicit text-only models (images need a "Send anyway" confirm).
TEXT_ONLY_MODELS: dict[str, tuple[str, ...]] = {
    "deepseek": ("deepseek-chat",),
    "openrouter": (
        "qwen/qwen3-coder-480b:free",  # text-only coder
        "deepseek/deepseek-r1:free",  # text-only reasoner
        "meta-llama/llama-3.3-70b-instruct:free",
        "mistralai/mistral-small-3.2-24b-instruct:free",
        "qwen/qwen3-235b-a22b:free",
    ),
    "groq": (
        "openai/gpt-oss-20b",
        "openai/gpt-oss-120b",
        "qwen/qwen3.6-27b",
        "qwen/qwen3.8-27b",
        "moonshotai/kimi-k2-instruct-0905",  # text-only
        "qwen/qwen3-32b",  # retired
        "meta-llama/llama-4-scout-17b-16e-instruct",  # retired
        "llama-3.3-70b-versatile",  # retired
        "llama-3.1-8b-instant",  # retired
    ),
}


def is_known_text_only(provider_id: str, model: str) -> bool:
    """True when the model is on the explicit text-only list."""
    m = (model or "").lower()
    return any(m == exact.lower() for exact in TEXT_ONLY_MODELS.get(provider_id, ()))


def vision_override_key(provider_id: str, model: str) -> str:
    """KeyStore key (section 'vision') remembering a user's Send-anyway."""
    return f"{(provider_id or '').strip()}||{(model or '').strip()}"


def supports_vision(
    provider_id: str, model: str, allow: object = ()
) -> bool:
    """Return True when images may be attempted for (provider, model).

    ``allow`` is a collection of ``vision_override_key`` values the user
    has confirmed via Send-anyway — those always return True.
    """
    try:
        if isinstance(allow, str):
            allow_set = {allow}
        elif isinstance(allow, (tuple, list, set, frozenset)):
            allow_set = {a for a in allow if isinstance(a, str)}
        else:
            allow_set = set()
    except Exception:
        allow_set = set()
    if vision_override_key(provider_id, model) in allow_set:
        return True
    m = (model or "").lower()
    for exact in TEXT_ONLY_MODELS.get(provider_id, ()):
        if m == exact.lower():
            return False
    needles = VISION_BY_SUBSTRING.get(provider_id)
    if needles is not None:
        return any(n in m for n in needles)
    return True  # OpenAI/gpt-4o*, Gemini, Anthropic, OpenRouter, HF, Custom: attempt


def supports_docs(provider_id: str, model: str) -> bool:
    """Docs ride along as extracted text — supported everywhere in v1."""
    return bool((model or "").strip())


def context_limit(model: object) -> int:
    """Return a conservative context limit for known models."""
    model_lower = model.lower() if isinstance(model, str) else ""
    if not model_lower:
        return DEFAULT_CONTEXT_LIMIT
    # Longest-substring wins so "llama-4-scout" beats a shorter generic
    # "llama" entry regardless of dict order.
    best: int | None = None
    best_len = -1
    for name, limit in CONTEXT_LIMITS.items():
        needle = name.lower()
        if needle and needle in model_lower and len(needle) > best_len:
            best, best_len = limit, len(needle)
    return best if best is not None else DEFAULT_CONTEXT_LIMIT


# ---- Model metadata for capability detail view ----
MODEL_METADATA: dict[str, dict[str, dict]] = {
    "gemini": {
        "gemini-3.8-flash": {
            "context_window": 1_000_000,
            "max_output": 65536,
            "knowledge_cutoff": "2024-11",
            "pricing_tier": "free",
            "capabilities": ["vision", "docs", "function_calling", "json_mode", "code_execution"],
        },
        "gemini-3.8-pro": {
            "context_window": 1_000_000,
            "max_output": 65536,
            "knowledge_cutoff": "2024-11",
            "pricing_tier": "free",
            "capabilities": ["vision", "docs", "function_calling", "json_mode", "code_execution", "reasoning", "long_context"],
        },
        "gemini-2.5-flash": {
            "context_window": 1_000_000,
            "max_output": 65536,
            "knowledge_cutoff": "2024-11",
            "pricing_tier": "free",
            "capabilities": ["vision", "docs", "function_calling", "json_mode"],
        },
        "gemini-2.5-pro": {
            "context_window": 1_000_000,
            "max_output": 65536,
            "knowledge_cutoff": "2024-11",
            "pricing_tier": "free",
            "capabilities": ["vision", "docs", "function_calling", "json_mode", "reasoning", "long_context"],
        },
        "gemini-2.0-flash": {
            "context_window": 1_000_000,
            "max_output": 8192,
            "knowledge_cutoff": "2024-11",
            "pricing_tier": "free",
            "capabilities": ["vision", "docs", "function_calling", "json_mode"],
        },
        "gemini-2.0-flash-lite": {
            "context_window": 1_000_000,
            "max_output": 8192,
            "knowledge_cutoff": "2024-11",
            "pricing_tier": "free",
            "capabilities": ["function_calling", "json_mode"],
        },
    },
    "groq": {
        "openai/gpt-oss-20b": {
            "context_window": 131_072,
            "max_output": 8192,
            "knowledge_cutoff": "2024-06",
            "pricing_tier": "free",
            "capabilities": ["function_calling", "json_mode"],
        },
        "openai/gpt-oss-120b": {
            "context_window": 131_072,
            "max_output": 8192,
            "knowledge_cutoff": "2024-06",
            "pricing_tier": "free",
            "capabilities": ["function_calling", "json_mode"],
        },
        "qwen/qwen3.6-27b": {
            "context_window": 131_072,
            "max_output": 8192,
            "knowledge_cutoff": "2024-06",
            "pricing_tier": "free",
            "capabilities": ["function_calling", "json_mode", "reasoning"],
        },
        "qwen/qwen3.8-27b": {
            "context_window": 131_072,
            "max_output": 8192,
            "knowledge_cutoff": "2024-06",
            "pricing_tier": "free",
            "capabilities": ["function_calling", "json_mode", "reasoning"],
        },
        "moonshotai/kimi-k2-instruct-0905": {
            "context_window": 131_072,
            "max_output": 8192,
            "knowledge_cutoff": "2024-06",
            "pricing_tier": "free",
            "capabilities": ["function_calling", "json_mode", "long_context"],
        },
        "meta-llama/llama-4-maverick-17b-128e-instruct": {
            "context_window": 131_072,
            "max_output": 8192,
            "knowledge_cutoff": "2024-06",
            "pricing_tier": "free",
            "capabilities": ["vision", "function_calling", "json_mode"],
        },
    },
    "openrouter": {
        "openrouter/free": {
            "context_window": 128_000,
            "max_output": 4096,
            "knowledge_cutoff": "varies",
            "pricing_tier": "free",
            "capabilities": ["vision", "docs", "function_calling", "json_mode"],
        },
        "z-ai/glm-5.2:free": {
            "context_window": 128_000,
            "max_output": 4096,
            "knowledge_cutoff": "2024-10",
            "pricing_tier": "free",
            "capabilities": ["vision", "docs", "function_calling", "json_mode", "reasoning"],
        },
        "minimax/minimax-m3:free": {
            "context_window": 200_000,
            "max_output": 4096,
            "knowledge_cutoff": "2024-10",
            "pricing_tier": "free",
            "capabilities": ["vision", "docs", "function_calling", "json_mode"],
        },
        "qwen/qwen3-coder-480b:free": {
            "context_window": 262_000,
            "max_output": 4096,
            "knowledge_cutoff": "2024-10",
            "pricing_tier": "free",
            "capabilities": ["function_calling", "json_mode", "code_specialist"],
        },
        "moonshotai/kimi-k2.6:free": {
            "context_window": 262_000,
            "max_output": 4096,
            "knowledge_cutoff": "2024-10",
            "pricing_tier": "free",
            "capabilities": ["vision", "docs", "function_calling", "json_mode", "long_context"],
        },
        "deepseek/deepseek-r1:free": {
            "context_window": 64_000,
            "max_output": 4096,
            "knowledge_cutoff": "2024-10",
            "pricing_tier": "free",
            "capabilities": ["reasoning", "json_mode"],
        },
        "meta-llama/llama-3.3-70b-instruct:free": {
            "context_window": 131_072,
            "max_output": 4096,
            "knowledge_cutoff": "2024-06",
            "pricing_tier": "free",
            "capabilities": ["function_calling", "json_mode"],
        },
        "google/gemma-3-27b-it:free": {
            "context_window": 128_000,
            "max_output": 8192,
            "knowledge_cutoff": "2024-10",
            "pricing_tier": "free",
            "capabilities": ["vision", "function_calling", "json_mode"],
        },
        "mistralai/mistral-small-3.2-24b-instruct:free": {
            "context_window": 128_000,
            "max_output": 4096,
            "knowledge_cutoff": "2024-10",
            "pricing_tier": "free",
            "capabilities": ["function_calling", "json_mode"],
        },
        "qwen/qwen3-235b-a22b:free": {
            "context_window": 262_000,
            "max_output": 4096,
            "knowledge_cutoff": "2024-10",
            "pricing_tier": "free",
            "capabilities": ["reasoning", "function_calling", "json_mode", "long_context"],
        },
    },
    "together": {
        "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free": {
            "context_window": 131_072,
            "max_output": 4096,
            "knowledge_cutoff": "2024-06",
            "pricing_tier": "free",
            "capabilities": ["function_calling", "json_mode"],
        },
        "deepseek-ai/DeepSeek-R1-Distill-Llama-70B-free": {
            "context_window": 32_768,
            "max_output": 4096,
            "knowledge_cutoff": "2024-06",
            "pricing_tier": "free",
            "capabilities": ["reasoning", "json_mode"],
        },
        "meta-llama/Llama-Vision-Free": {
            "context_window": 131_072,
            "max_output": 4096,
            "knowledge_cutoff": "2024-06",
            "pricing_tier": "free",
            "capabilities": ["vision", "function_calling", "json_mode"],
        },
        "meta-llama/Llama-4-Scout-Free": {
            "context_window": 131_072,
            "max_output": 4096,
            "knowledge_cutoff": "2024-06",
            "pricing_tier": "free",
            "capabilities": ["vision", "function_calling", "json_mode"],
        },
        "Qwen/Qwen2.5-72B-Instruct-Turbo-Free": {
            "context_window": 32_768,
            "max_output": 4096,
            "knowledge_cutoff": "2024-06",
            "pricing_tier": "free",
            "capabilities": ["function_calling", "json_mode"],
        },
    },
    "huggingface": {
        "meta-llama/Llama-3.3-70B-Instruct": {
            "context_window": 131_072,
            "max_output": 4096,
            "knowledge_cutoff": "2024-06",
            "pricing_tier": "free",
            "capabilities": ["function_calling", "json_mode"],
        },
        "Qwen/Qwen2.5-72B-Instruct": {
            "context_window": 32_768,
            "max_output": 4096,
            "knowledge_cutoff": "2024-06",
            "pricing_tier": "free",
            "capabilities": ["function_calling", "json_mode"],
        },
        "mistralai/Mistral-7B-Instruct-v0.3": {
            "context_window": 32_768,
            "max_output": 4096,
            "knowledge_cutoff": "2024-04",
            "pricing_tier": "free",
            "capabilities": ["function_calling"],
        },
        "microsoft/Phi-4-mini-instruct": {
            "context_window": 128_000,
            "max_output": 4096,
            "knowledge_cutoff": "2024-10",
            "pricing_tier": "free",
            "capabilities": ["function_calling", "json_mode"],
        },
        "HuggingFaceH4/zephyr-7b-beta": {
            "context_window": 8_192,
            "max_output": 4096,
            "knowledge_cutoff": "2024-04",
            "pricing_tier": "free",
            "capabilities": [],
        },
    },
    "deepseek": {
        "deepseek-chat": {
            "context_window": 64_000,
            "max_output": 8192,
            "knowledge_cutoff": "2024-07",
            "pricing_tier": "paid",
            "capabilities": ["function_calling", "json_mode", "reasoning"],
        },
        "deepseek-reasoner": {
            "context_window": 64_000,
            "max_output": 8192,
            "knowledge_cutoff": "2024-07",
            "pricing_tier": "paid",
            "capabilities": ["reasoning", "json_mode"],
        },
    },
    "openai": {
        "gpt-4o-mini": {
            "context_window": 128_000,
            "max_output": 16384,
            "knowledge_cutoff": "2024-10",
            "pricing_tier": "paid",
            "capabilities": ["vision", "docs", "function_calling", "json_mode", "reasoning"],
        },
        "gpt-5-mini": {
            "context_window": 400_000,
            "max_output": 32768,
            "knowledge_cutoff": "2024-10",
            "pricing_tier": "paid",
            "capabilities": ["vision", "docs", "function_calling", "json_mode", "reasoning"],
        },
        "gpt-5": {
            "context_window": 400_000,
            "max_output": 32768,
            "knowledge_cutoff": "2024-10",
            "pricing_tier": "paid",
            "capabilities": ["vision", "docs", "function_calling", "json_mode", "reasoning", "long_context"],
        },
        "gpt-4o": {
            "context_window": 128_000,
            "max_output": 16384,
            "knowledge_cutoff": "2024-10",
            "pricing_tier": "paid",
            "capabilities": ["vision", "docs", "function_calling", "json_mode", "reasoning"],
        },
    },
    "anthropic": {
        "claude-haiku-4-5": {
            "context_window": 200_000,
            "max_output": 8192,
            "knowledge_cutoff": "2024-10",
            "pricing_tier": "paid",
            "capabilities": ["vision", "docs", "function_calling", "json_mode", "reasoning"],
        },
        "claude-sonnet-5": {
            "context_window": 1_000_000,
            "max_output": 8192,
            "knowledge_cutoff": "2024-10",
            "pricing_tier": "paid",
            "capabilities": ["vision", "docs", "function_calling", "json_mode", "reasoning", "long_context"],
        },
        "claude-opus-5": {
            "context_window": 1_000_000,
            "max_output": 8192,
            "knowledge_cutoff": "2024-10",
            "pricing_tier": "paid",
            "capabilities": ["vision", "docs", "function_calling", "json_mode", "reasoning", "long_context"],
        },
    },
    "custom": {},
}


def get_model_metadata(provider_id: str, model: str) -> dict:
    """Return metadata dict for a model, with sensible defaults.

    Unlisted models fall back to the CONTEXT_LIMITS heuristic; pricing
    derives from the provider's free flag so offline-registry models
    (HuggingFace, custom endpoints) never show "Unknown" when the
    provider is a free tier.
    """
    default_pricing = "free" if PROVIDERS.get(provider_id, {}).get("free") else "unknown"
    return MODEL_METADATA.get(provider_id, {}).get(model, {
        "context_window": context_limit(model),
        "max_output": 4096,
        "knowledge_cutoff": "unknown",
        "pricing_tier": default_pricing,
        "capabilities": [],
    })
