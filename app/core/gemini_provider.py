"""Gemini via its OpenAI-compatible endpoint (no separate SDK needed)."""

import httpx

from app.core.provider_base import OpenAICompatProvider

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


class GeminiProvider(OpenAICompatProvider):
    provider_id = "gemini"

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        client: httpx.AsyncClient | None = None,
        timeout: float = 60.0,
        extra_headers: dict | None = None,
    ) -> None:
        super().__init__(
            api_key, base_url or DEFAULT_BASE_URL, extra_headers, client, timeout
        )
