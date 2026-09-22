"""Anthropic Messages API adapter (true SSE streaming).

Accepts OpenAI-style parts lists (text + image data URLs) and converts
them to Anthropic blocks. Streams via the Messages SSE protocol
(content_block_delta / message_stop), so the chat UI gets live tokens.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from app.core.errors import ProviderError, map_http_status
from app.core.types import Message

ANTHROPIC_VERSION = "2023-06-01"


def openai_parts_to_anthropic(parts: object) -> list[dict]:
    """Convert OpenAI-style content parts to Anthropic blocks (P3)."""
    import base64 as _b64

    if not isinstance(parts, list):
        return [{"type": "text", "text": ""}]
    blocks: list[dict] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text" and part.get("text"):
            text = part.get("text")
            blocks.append({"type": "text", "text": text if isinstance(text, str) else str(text)})
        elif part.get("type") == "image_url":
            url = (part.get("image_url") or {}).get("url", "") if isinstance(part.get("image_url"), dict) else ""
            if not isinstance(url, str) or not url.startswith("data:"):
                raise ProviderError(
                    "bad_request", "Anthropic needs embedded image data, not URLs."
                )
            try:
                header, b64 = url.split(",", 1)
                media_type = header.split(";")[0].split(":")[1]
            except (IndexError, ValueError, AttributeError) as e:
                raise ProviderError("bad_request", "Malformed image data URL.") from e
            if not b64 or not isinstance(media_type, str) or "/" not in media_type:
                raise ProviderError("bad_request", "Malformed image data URL.")
            if media_type not in ("image/png", "image/jpeg", "image/webp", "image/gif"):
                raise ProviderError("bad_request", f"Unsupported image type {media_type}.")
            try:
                _b64.b64decode(b64, validate=True)
            except Exception as e:
                raise ProviderError("bad_request", "Malformed image data (bad base64).") from e
            if len(b64) > 28_000_000:
                raise ProviderError("too_large", "Image is too large.")
            blocks.append(
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": b64},
                }
            )
    return blocks or [{"type": "text", "text": ""}]


def parse_anthropic_sse_data(data: str) -> str | None:
    """Parse one Anthropic SSE data payload -> text delta.

    Returns "" for control events, None when the message ends.
    Raises ProviderError on {"type": "error", ...} payloads.
    Pure helper — unit-testable without network.
    Oversized payloads are dropped.
    """
    import json

    if not isinstance(data, str):
        return ""
    if len(data) > 64 * 1024:
        return ""
    data = (data or "").strip()
    if not data:
        return ""
    try:
        payload = json.loads(data)
    except ValueError:
        return ""
    if not isinstance(payload, dict):
        return ""
    ptype = payload.get("type", "")
    if ptype == "error":
        err = payload.get("error") or {}
        msg = str(err.get("message", "") if isinstance(err, dict) else err)[:300]
        raise ProviderError("unknown", msg or "Anthropic stream error.")
    if ptype == "message_stop":
        return None
    if ptype in ("ping", "message_start", "content_block_start",
                 "content_block_stop", "message_delta"):
        return ""
    if ptype == "content_block_delta":
        delta = payload.get("delta") or {}
        if isinstance(delta, dict):
            text = delta.get("text", "")
            return str(text) if text else ""
        return ""
    return ""


def _text_of(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    out: list[str] = []
    for p in content:
        if not isinstance(p, dict) or p.get("type") != "text":
            continue
        t = p.get("text", "")
        out.append(t if isinstance(t, str) else (str(t) if t else ""))
    return "\n".join(t for t in out if t)


def _content_for_api(content: object) -> str | list[dict]:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return openai_parts_to_anthropic(content)


class AnthropicProvider:
    provider_id = "anthropic"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.anthropic.com/v1",
        client: httpx.AsyncClient | None = None,
        timeout: float = 60.0,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("API key must be a non-empty string.")
        if not isinstance(base_url, str) or not base_url.strip():
            base_url = "https://api.anthropic.com/v1"
        try:
            t = float(timeout)
        except (TypeError, ValueError):
            t = 60.0
        t = max(5.0, min(300.0, t))
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._client = client
        self._timeout = t

    @asynccontextmanager
    async def _scoped_client(self):
        """Yield the injected client, or an ephemeral one that is closed.

        Fixes the previous leak where each call built a new AsyncClient
        without ever calling aclose(). Injected clients are caller-owned.
        trust_env=False + no redirects to block proxy/SSRF pivots.
        """
        if self._client is not None:
            yield self._client
            return
        async with httpx.AsyncClient(timeout=self._timeout, trust_env=False,
                                     follow_redirects=False) as client:
            yield client

    async def aclose(self) -> None:
        """Best-effort close of an injected shared client (idempotent)."""
        try:
            if self._client is not None and hasattr(self._client, "aclose"):
                await self._client.aclose()
        except Exception:
            pass

    async def list_models(self) -> list[str]:
        """Return model IDs advertised by Anthropic's Models API."""
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
        }
        try:
            async with self._scoped_client() as client:
                resp = await client.get(
                    f"{self.base_url.rstrip('/')}/models", headers=headers
                )
        except httpx.HTTPError as e:
            raise ProviderError("network", str(e)) from e
        if resp.status_code != 200:
            try:
                text = resp.text[:2000]
            except Exception:
                text = ""
            raise ProviderError(map_http_status(resp.status_code), text)
        try:
            body = resp.json() or {}
            items = body.get("data", [])
            models = sorted(
                {
                    item["id"].strip()
                    for item in items
                    if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip()
                }
            )
        except (AttributeError, TypeError, ValueError) as e:
            try:
                snippet = resp.text[:200]
            except Exception:
                snippet = ""
            raise ProviderError("unknown", f"Bad models response shape: {snippet}") from e
        if not models:
            raise ProviderError("unknown", "The provider returned no usable models.")
        return models

    def _headers(self) -> dict:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }

    @staticmethod
    def split_system(messages: object) -> tuple[str, list[dict]]:
        """Split system prompt + merge consecutive same-role turns.

        Anthropic rejects back-to-back same-role messages (HTTP 400) and
        requires the first turn to be user. History + new-prompt appends
        naturally produce user,user runs, so merge them with a separator.
        """
        if not isinstance(messages, list):
            return "", []
        system = "\n".join(
            _text_of(getattr(m, "content", "")) for m in messages
            if m is not None and getattr(m, "role", "") == "system"
        )[:8000]
        rest: list[dict] = []
        for m in messages:
            if m is None:
                continue
            role = getattr(m, "role", None)
            if role not in ("user", "assistant"):
                continue
            role = "assistant" if role == "assistant" else "user"
            try:
                content = _content_for_api(getattr(m, "content", ""))
            except ProviderError:
                raise
            except Exception as e:  # noqa: BLE001 — malformed content blocks
                raise ProviderError("bad_request", f"Bad message content: {e}") from e
            if rest and rest[-1]["role"] == role:
                prev = rest[-1]["content"]
                if isinstance(prev, str) and isinstance(content, str):
                    rest[-1]["content"] = (prev + "\n\n" + content).strip()
                elif isinstance(prev, list) and isinstance(content, list):
                    rest[-1]["content"] = [*prev, *content]
                elif isinstance(prev, str):
                    rest[-1]["content"] = [ {"type": "text", "text": prev}, *content ] if content else prev
                else:
                    rest[-1]["content"] = [*prev, {"type": "text", "text": content}] if isinstance(content, str) else [*prev, *content]
            else:
                rest.append({"role": role, "content": content})
        if not rest:
            raise ProviderError("bad_request", "No user messages to send.")
        # Anthropic requires the first message to be user — drop a leading
        # assistant turn (e.g. reopened compacted thread edge) rather than 400.
        while rest and rest[0]["role"] != "user":
            rest.pop(0)
        if not rest:
            raise ProviderError("bad_request", "No user messages to send.")
        return system, rest

    async def acomplete(
        self, messages: list[Message], model: str, max_tokens: int = 16
    ) -> str:
        system, rest = self.split_system(messages)
        try:
            max_tokens = max(1, min(65536, int(max_tokens)))
        except (TypeError, ValueError):
            max_tokens = 16
        payload: dict = {"model": model if isinstance(model, str) else "", "max_tokens": max_tokens, "messages": rest}
        if system:
            payload["system"] = system
        try:
            async with self._scoped_client() as client:
                resp = await client.post(
                    f"{self.base_url}/messages", headers=self._headers(), json=payload
                )
        except httpx.HTTPError as e:
            raise ProviderError("network", str(e)) from e
        if resp.status_code != 200:
            try:
                text = resp.text[:2000]
            except Exception:
                text = ""
            raise ProviderError(map_http_status(resp.status_code), text)
        try:
            data = resp.json() or {}
            blocks = data.get("content", [])
            if not isinstance(blocks, list):
                raise TypeError("content is not a list")
            return "".join(
                str(b.get("text", ""))
                for b in blocks
                if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
            )
        except (ValueError, AttributeError, TypeError, KeyError, IndexError) as e:
            try:
                snippet = resp.text[:200]
            except Exception:
                snippet = ""
            raise ProviderError("unknown", f"Bad response shape: {snippet}") from e

    async def chat_stream(
        self, messages: list[Message], model: str, max_tokens: int = 1024
    ) -> AsyncIterator[str]:
        """True Messages SSE streaming (content_block_delta text)."""
        import asyncio as _asyncio
        import time as _time

        system, rest = self.split_system(messages)
        try:
            max_tokens = max(1, min(65536, int(max_tokens)))
        except (TypeError, ValueError):
            max_tokens = 1024
        payload: dict = {
            "model": model if isinstance(model, str) else "",
            "max_tokens": max_tokens,
            "messages": rest,
            "stream": True,
        }
        if system:
            payload["system"] = system
        started = _time.monotonic()
        try:
            async with self._scoped_client() as client:
                try:
                    req = client.build_request(
                        "POST",
                        f"{self.base_url}/messages",
                        headers={**self._headers(), "Accept": "text/event-stream"},
                        json=payload,
                    )
                except (TypeError, ValueError) as e:
                    raise ProviderError("bad_request", f"Bad request payload: {e}") from e
                try:
                    resp = await client.send(req, stream=True)
                except httpx.HTTPError as e:
                    raise ProviderError("network", str(e)) from e
                try:
                    if resp.status_code != 200:
                        try:
                            body = await _asyncio.wait_for(resp.aread(), timeout=15.0)
                        except _asyncio.TimeoutError as e:
                            raise ProviderError("network", "Provider error response timed out.") from e
                        except httpx.HTTPError as e:
                            raise ProviderError("network", str(e)) from e
                        try:
                            text = body.decode("utf-8", "replace")[:2000]
                        except Exception:
                            text = ""
                        raise ProviderError(
                            map_http_status(resp.status_code),
                            text,
                        )
                    try:
                        total_chars = 0
                        async for line in resp.aiter_lines():
                            if _time.monotonic() - started > 300.0:
                                break
                            if len(line or "") > 64 * 1024 + 16:
                                continue
                            s = (line or "").strip()
                            if not s or s.startswith(":"):
                                continue
                            if s.startswith("event:"):
                                continue
                            if not s.startswith("data:"):
                                continue
                            try:
                                delta = parse_anthropic_sse_data(s[5:].strip())
                            except ProviderError:
                                raise
                            except Exception:
                                continue
                            if delta is None:
                                break
                            if delta:
                                total_chars += len(delta)
                                if total_chars > 1_000_000:
                                    break
                                yield delta
                    except httpx.HTTPError as e:
                        raise ProviderError("network", str(e)) from e
                finally:
                    try:
                        await resp.aclose()
                    except Exception:
                        pass
        except ProviderError:
            raise
        except Exception as e:  # noqa: BLE001 — never leak httpx internals
            if isinstance(e, _asyncio.CancelledError):
                raise
            raise ProviderError("network", str(e)) from e
