"""OpenAI-compatible provider: chat + true SSE streaming.

Covers Gemini (via /v1beta/openai/), Groq, Together, OpenRouter,
DeepSeek, HuggingFace, OpenAI, and any Custom base_url.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

from app.core.errors import ProviderError, map_http_status
from app.core.types import Message


MAX_SSE_LINE_CHARS = 64 * 1024
MAX_STREAM_CHARS = 1_000_000
MAX_IMAGE_B64_CHARS = 28_000_000
MAX_IMAGE_DOWNLOAD_BYTES = 15 * 1024 * 1024


def _is_safe_image_url(url: str) -> bool:
    """Allow only public https:// hosts for provider-supplied image URLs."""
    try:
        from urllib.parse import urlparse as _up
        import ipaddress as _ip

        p = _up(url)
        if p.scheme != "https" or not p.netloc or p.username or p.password:
            return False
        host = (p.hostname or "").lower().rstrip(".")
        if not host or host in ("localhost", "metadata.google.internal"):
            return False
        if host.endswith((".local", ".internal", ".lan", ".home")):
            return False
        try:
            ip = _ip.ip_address(host.strip("[]"))
            return not (ip.is_private or ip.is_loopback or ip.is_link_local
                        or ip.is_reserved or ip.is_multicast)
        except ValueError:
            return True  # public DNS name — resolved at connect; https-only
    except Exception:
        return False


def parse_sse_line(line: str) -> str | None:
    """Parse one SSE line -> text delta. Pure function (unit-tested).

    Returns "" for keep-alives, None when stream ends ([DONE]).
    Raises ProviderError when the provider streams an {"error": ...} payload.
    Oversized lines (>MAX_SSE_LINE_CHARS) are dropped to bound json.loads.
    """
    if not isinstance(line, str):
        return ""
    if len(line) > MAX_SSE_LINE_CHARS + 16:
        return ""
    line = line.strip()
    if not line or line.startswith(":"):
        return ""
    if not line.startswith("data:"):
        return ""
    data = line[5:].strip()
    if len(data) > MAX_SSE_LINE_CHARS:
        return ""
    if data == "[DONE]":
        return None
    import json

    try:
        payload = json.loads(data)
    except ValueError:
        return ""
    if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
        msg = str(payload["error"].get("message", "") or "stream error")[:300]
        raise ProviderError("unknown", msg)
    if isinstance(payload, dict) and isinstance(payload.get("error"), str):
        raise ProviderError("unknown", str(payload["error"])[:300])
    try:
        choices = payload["choices"]
        first = choices[0]
        if isinstance(first, dict):
            # Standard streaming chunk: choices[0].delta.content
            delta = first.get("delta")
            if isinstance(delta, dict):
                text = delta.get("content")
                if text:
                    return str(text)
                # Reasoning models stream into reasoning_content.
                reasoning = delta.get("reasoning_content")
                if reasoning:
                    return str(reasoning)
                # Tool-call deltas carry no displayable text — skip.
                if delta.get("tool_calls"):
                    return ""
            # Some gateways send non-stream shapes mid-stream.
            text = first.get("text")
            if text:
                return str(text)
            msg = first.get("message")
            if isinstance(msg, dict) and msg.get("content"):
                return str(msg["content"])
        return ""
    except (KeyError, IndexError, TypeError, AttributeError):
        return ""


class OpenAICompatProvider:
    provider_id = "openai-compat"

    def __init__(
        self,
        api_key: str,
        base_url: str,
        extra_headers: dict | None = None,
        client: httpx.AsyncClient | None = None,
        timeout: float = 60.0,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("API key must be a non-empty string.")
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("base_url must be a non-empty string.")
        try:
            t = float(timeout)
        except (TypeError, ValueError):
            t = 60.0
        t = max(5.0, min(300.0, t))
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.extra_headers = dict(extra_headers or {})
        self._client = client
        self._timeout = t

    def _headers(self) -> dict:
        h = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        h.update(self.extra_headers)
        return h

    def _url(self) -> str:
        return f"{self.base_url}/chat/completions"

    def _models_url(self) -> str:
        return f"{self.base_url}/models"

    def _images_url(self) -> str:
        return f"{self.base_url}/images/generations"

    def _client_or(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        return httpx.AsyncClient(timeout=self._timeout, trust_env=False,
                                 follow_redirects=False)

    @asynccontextmanager
    async def _scoped_client(self):
        """Yield the injected client, or an ephemeral one that is closed.

        Ephemeral clients are created per call and always closed — this
        fixes the previous leak where _client_or() built a new AsyncClient
        per request without ever calling aclose(). Injected clients remain
        owned by the caller and are never closed here.
        trust_env=False so proxy/env cannot MITM; redirects disabled.
        """
        if self._client is not None:
            yield self._client
            return
        async with httpx.AsyncClient(timeout=self._timeout, trust_env=False,
                                     follow_redirects=False) as client:
            yield client

    async def aclose(self) -> None:
        """Best-effort close of an injected shared client.

        Ephemeral per-call clients are already closed by _scoped_client,
        so providers created per request (main.py pattern) need no cleanup.
        httpx aclose() is idempotent, so calling this twice is safe.
        """
        try:
            if self._client is not None and hasattr(self._client, "aclose"):
                await self._client.aclose()
        except Exception:
            pass

    @staticmethod
    def _raise_for(status: int, body: str) -> ProviderError:
        return ProviderError(map_http_status(status), body[:300])

    async def acomplete(
        self, messages: list[Message], model: str, max_tokens: int = 16
    ) -> str:
        payload = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "max_tokens": max_tokens,
            "stream": False,
        }
        try:
            async with self._scoped_client() as client:
                resp = await client.post(self._url(), headers=self._headers(), json=payload)
        except httpx.HTTPError as e:
            raise ProviderError("network", str(e)) from e
        if resp.status_code != 200:
            # Bound the error body: providers can return MBs of HTML.
            try:
                text = resp.text[:2000]
            except Exception:
                text = ""
            raise self._raise_for(resp.status_code, text)
        try:
            data = resp.json()
            choices = data["choices"]
            msg = choices[0]["message"]
            content = msg.get("content") if isinstance(msg, dict) else None
            if isinstance(content, str) and content:
                return content
            reasoning = msg.get("reasoning_content") if isinstance(msg, dict) else None
            if isinstance(reasoning, str) and reasoning:
                return reasoning
            return ""
        except (KeyError, IndexError, ValueError, AttributeError, TypeError) as e:
            try:
                snippet = resp.text[:200]
            except Exception:
                snippet = ""
            raise ProviderError("unknown", f"Bad response shape: {snippet}") from e

    async def generate_image(
        self, prompt: str, model: str, size: str = "1024x1024"
    ) -> tuple[bytes, str]:
        """Render an image via POST {base}/images/generations.

        Returns (png_bytes, revised_prompt). Accepts both `b64_json`
        (preferred, no second round-trip) and `url` (downloaded) payloads.
        Raises ProviderError on any failure.
        """
        import base64
        from urllib.parse import urlparse

        from app.config import IMAGE_GEN_TIMEOUT

        if not isinstance(prompt, str) or not prompt.strip():
            raise ProviderError("bad_request", "Image prompt is empty.")
        prompt = prompt[:2000]
        if not isinstance(model, str) or not model.strip():
            raise ProviderError("bad_request", "Image model is empty.")
        allowed_sizes = ("1024x1024", "1024x1792", "1792x1024")
        if size not in allowed_sizes:
            size = "1024x1024"
        payload = {"model": model, "prompt": prompt, "size": size, "n": 1}
        try:
            timeout = IMAGE_GEN_TIMEOUT if isinstance(IMAGE_GEN_TIMEOUT, (int, float)) else 180.0
        except Exception:
            timeout = 180.0
        timeout = max(30.0, min(600.0, float(timeout)))
        # Respect an injected client (tests + shared connections); only the
        # ephemeral fallback uses the long image timeout.
        if self._client is not None:
            try:
                async with self._scoped_client() as client:
                    resp = await client.post(
                        self._images_url(), headers=self._headers(), json=payload
                    )
            except httpx.HTTPError as e:
                raise ProviderError("network", str(e)) from e
        else:
            try:
                async with httpx.AsyncClient(timeout=timeout, trust_env=False,
                                             follow_redirects=False) as client:
                    resp = await client.post(
                        self._images_url(), headers=self._headers(), json=payload
                    )
            except httpx.HTTPError as e:
                raise ProviderError("network", str(e)) from e
        if resp.status_code != 200:
            try:
                text = resp.text[:2000]
            except Exception:
                text = ""
            raise self._raise_for(resp.status_code, text)
        try:
            items = resp.json().get("data") or []
            data = items[0] if items else {}
            revised = str(data.get("revised_prompt") or "")[:500]
            b64 = data.get("b64_json")
            if b64:
                if not isinstance(b64, str) or not b64:
                    raise ValueError("empty b64_json")
                # Cap ~20MB base64 (~15MB png) — larger would OOM the phone.
                if len(b64) > 28_000_000:
                    raise ValueError("image too large")
                return base64.b64decode(b64), revised
            url = data.get("url")
            if url:
                if not isinstance(url, str):
                    raise ValueError("bad image url")
                if not _is_safe_image_url(url):
                    raise ProviderError("unknown", "Provider returned a blocked image URL.")
                # Streamed download with running cap (never buffer unbounded).
                try:
                    if self._client is not None:
                        async with self._scoped_client() as client:
                            async with client.stream("GET", url) as dl:
                                if dl.status_code != 200:
                                    raise ProviderError(
                                        "network", f"Image download failed: HTTP {dl.status_code}"
                                    )
                                ctype = (dl.headers.get("content-type", "") or "").lower()
                                if ctype and "image" not in ctype and "octet-stream" not in ctype:
                                    raise ProviderError("unknown", "Image download is not an image.")
                                buf = bytearray()
                                async for chunk in dl.aiter_bytes(65536):
                                    buf.extend(chunk)
                                    if len(buf) > MAX_IMAGE_DOWNLOAD_BYTES:
                                        raise ProviderError("too_large", "Generated image is too large.")
                                content = bytes(buf)
                    else:
                        async with httpx.AsyncClient(timeout=timeout, trust_env=False,
                                                     follow_redirects=False) as client:
                            async with client.stream("GET", url) as dl:
                                if dl.status_code != 200:
                                    raise ProviderError(
                                        "network", f"Image download failed: HTTP {dl.status_code}"
                                    )
                                ctype = (dl.headers.get("content-type", "") or "").lower()
                                if ctype and "image" not in ctype and "octet-stream" not in ctype:
                                    raise ProviderError("unknown", "Image download is not an image.")
                                buf = bytearray()
                                async for chunk in dl.aiter_bytes(65536):
                                    buf.extend(chunk)
                                    if len(buf) > MAX_IMAGE_DOWNLOAD_BYTES:
                                        raise ProviderError("too_large", "Generated image is too large.")
                                content = bytes(buf)
                except ProviderError:
                    raise
                except httpx.HTTPError as e:
                    raise ProviderError("network", str(e)) from e
                # Magic-byte check: PNG/JPEG/WEBP/GIF only.
                if not (content.startswith(b"\x89PNG") or content.startswith(b"\xff\xd8")
                        or content.startswith(b"RIFF") or content.startswith(b"GIF8")):
                    raise ProviderError("unknown", "Image download is not a valid image.")
                if not content:
                    raise ProviderError("unknown", "Image download was empty.")
                return content, revised
        except ProviderError:
            raise
        except Exception as e:  # noqa: BLE001 — malformed payload shape
            try:
                snippet = resp.text[:200]
            except Exception:
                snippet = ""
            raise ProviderError(
                "unknown", f"Bad image response shape: {snippet}"
            ) from e
        raise ProviderError("unknown", "No image in the provider response.")

    async def list_models(self) -> list[str]:
        """Return model IDs advertised by an OpenAI-compatible endpoint."""
        try:
            async with self._scoped_client() as client:
                resp = await client.get(self._models_url(), headers=self._headers())
        except httpx.HTTPError as e:
            raise ProviderError("network", str(e)) from e
        if resp.status_code != 200:
            try:
                text = resp.text[:2000]
            except Exception:
                text = ""
            raise self._raise_for(resp.status_code, text)
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

    async def chat_stream(
        self, messages: list[Message], model: str, max_tokens: int = 1024
    ) -> AsyncIterator[str]:
        import asyncio as _asyncio
        import time as _time

        STREAM_DEADLINE_S = 300.0  # hung streams can't run forever on phones
        # Sanitize payload: non-str content (list/dict from corrupt history)
        # would raise TypeError inside build_request.
        safe_messages = []
        for m in messages or []:
            try:
                role = getattr(m, "role", "user")
                content = getattr(m, "content", "")
                if not isinstance(role, str):
                    role = "user"
                if not isinstance(content, (str, list)):
                    content = str(content)
                safe_messages.append({"role": role, "content": content})
            except Exception:
                continue
        try:
            max_tokens = int(max_tokens)
        except (TypeError, ValueError):
            max_tokens = 1024
        max_tokens = max(1, min(65536, max_tokens))
        payload = {
            "model": model if isinstance(model, str) else "",
            "messages": safe_messages,
            "max_tokens": max_tokens,
            "stream": True,
        }
        started = _time.monotonic()
        try:
            async with self._scoped_client() as client:
                try:
                    req = client.build_request(
                        "POST", self._url(), headers=self._headers(), json=payload
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
                        raise self._raise_for(resp.status_code, text)
                    try:
                        total_chars = 0
                        async for line in resp.aiter_lines():
                            if _time.monotonic() - started > STREAM_DEADLINE_S:
                                break
                            if len(line) > MAX_SSE_LINE_CHARS + 16:
                                continue  # drop oversized line before parse
                            try:
                                delta = parse_sse_line(line)
                            except ProviderError:
                                raise
                            except Exception:
                                continue
                            if delta is None:
                                break
                            if delta:
                                total_chars += len(delta)
                                if total_chars > MAX_STREAM_CHARS:
                                    break  # runaway provider — truncate
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
