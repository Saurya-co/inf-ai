"""P3 attachments + v0.4.0 RAG: validate, extract, build multimodal payloads.

- Images (png/jpg/webp, <=10MB): base64 data_url for vision models.
- Docs (txt/md/pdf, <=15MB): text-extracted (pypdf for PDFs). Full text
  retained up to RAG_FULL_CHARS for on-device retrieval; the plain
  send path still injects only the first MAX_DOC_CHARS with a
  truncation flag surfaced in the UI.
- No Pillow dependency: downscale attempted only if Pillow happens to be
  installed (desktop dev); Android without the wheel just sends originals.
"""

import base64
import io
import os

from app.config import (
    ALLOWED_DOC_EXTS,
    ALLOWED_IMAGE_EXTS,
    MAX_DOC_BYTES,
    MAX_DOC_CHARS,
    MAX_IMAGE_BYTES,
    MAX_IMAGE_DIM,
    supports_vision,
)
from app.core.types import Attachment, Message

# v0.4.0: full-text retention cap for RAG indexing (~200k chars ≈ 50k
# tokens of source; retrieval injects only top-k chunks from it).
RAG_FULL_CHARS = 200_000

# Total staged budget across all attachments (DoS guard).
TOTAL_STAGED_BUDGET = 30 * 1024 * 1024


def check_magic(kind: str, raw: bytes) -> None:
    """Reject extension/MIME confusion by sniffing magic bytes."""
    if not raw or len(raw) < 4:
        raise ValueError("File is too small to identify.")
    head = bytes(raw[:16])
    if kind == "image":
        ok = (
            head.startswith(b"\x89PNG\r\n\x1a\n")
            or head.startswith(b"\xff\xd8\xff")  # JPEG
            or (head.startswith(b"RIFF") and b"WEBP" in head)  # WEBP
        )
        if not ok:
            raise ValueError("Image content does not match its file type.")
    elif kind == "doc":
        # txt/md: must be mostly decodable text; pdf: %PDF- header.
        # We only know ext here via caller; pdf check happens in prepare_doc.
        pass


def _png_dimensions(raw: bytes) -> tuple[int, int] | None:
    """Parse PNG IHDR without Pillow (Android has no wheel)."""
    try:
        import struct

        if not raw.startswith(b"\x89PNG\r\n\x1a\n") or len(raw) < 33:
            return None
        w, h = struct.unpack(">II", raw[16:24])
        return (w, h) if 0 < w <= 20000 and 0 < h <= 20000 else (w, h)
    except Exception:
        return None


def _jpeg_dimensions(raw: bytes) -> tuple[int, int] | None:
    try:
        i = 2
        n = len(raw)
        while i + 8 < n:
            if raw[i] != 0xFF:
                break
            marker = raw[i + 1]
            if marker in (0xC0, 0xC1, 0xC2):
                h = (raw[i + 5] << 8) + raw[i + 6]
                w = (raw[i + 7] << 8) + raw[i + 8]
                return (w, h)
            seg_len = (raw[i + 2] << 8) + raw[i + 3]
            if seg_len < 2:
                break
            i += 2 + seg_len
        return None
    except Exception:
        return None

_MIME_BY_EXT = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}


def classify(filename: object) -> str | None:
    if not isinstance(filename, str):
        return None
    ext = os.path.splitext(filename)[1].lower().lstrip(".")
    if ext in ALLOWED_IMAGE_EXTS:
        return "image"
    if ext in ALLOWED_DOC_EXTS:
        return "doc"
    return None


def validate_file(name: object, size: object) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("File name must be a non-empty string.")
    # Never trust directory components from pickers — store basename only.
    safe = os.path.basename(name)
    if not safe or safe in (".", ".."):
        raise ValueError(f"Unsupported file '{name}'.")
    kind = classify(safe)
    if kind is None:
        raise ValueError(
            f"Unsupported file '{safe}'. v1 takes: images (png/jpg/webp), docs (txt/md/pdf)."
        )
    try:
        n = int(size)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ValueError(f"Could not determine size of '{safe}'.")
    if n < 0:
        raise ValueError(f"Invalid size for '{safe}'.")
    if kind == "image" and n > MAX_IMAGE_BYTES:
        raise ValueError(f"Image '{safe}' is too large (>10MB). Pick a smaller one.")
    if kind == "doc" and n > MAX_DOC_BYTES:
        raise ValueError(f"Document '{safe}' is too large (>15MB). Pick a smaller one.")
    return kind


def _maybe_downscale(raw: bytes) -> bytes:
    """Best-effort resize to MAX_IMAGE_DIM. No-op if Pillow is missing."""
    if not isinstance(raw, (bytes, bytearray)) or not raw:
        return raw
    # Decompression-bomb guard before Pillow even opens it.
    if len(raw) > MAX_IMAGE_BYTES:
        return raw
    # Without Pillow (Android target): enforce pixel-count guard from
    # headers so a 50MP “10MB” PNG can't OOM the phone/provider.
    dims = None
    try:
        if raw.startswith(b"\x89PNG"):
            dims = _png_dimensions(bytes(raw))
        elif raw.startswith(b"\xff\xd8"):
            dims = _jpeg_dimensions(bytes(raw))
        if dims is not None and dims[0] * dims[1] > 50_000_000:
            raise ValueError("Image has too many pixels (>50MP). Pick a smaller one.")
    except ValueError:
        raise
    except Exception:
        pass
    try:
        from PIL import Image
    except ImportError:
        return raw
    try:
        Image.MAX_IMAGE_PIXELS = 50_000_000  # ~7k x 7k — above that, refuse to expand
        with Image.open(io.BytesIO(bytes(raw))) as img:
            img.load()  # force decode inside try so truncated files fall through
            if max(img.size) <= MAX_IMAGE_DIM:
                return bytes(raw)
            img.thumbnail((MAX_IMAGE_DIM, MAX_IMAGE_DIM))
            buf = io.BytesIO()
            fmt = "PNG" if (img.format or "").upper() == "PNG" else "JPEG"
            img.save(buf, format=fmt)
            return buf.getvalue()
    except Exception:
        return bytes(raw)


def prepare_image(name: object, raw: object) -> Attachment:
    if not isinstance(raw, (bytes, bytearray)):
        raise ValueError(f"Image '{name}' has no readable data.")
    raw = bytes(raw)
    if not raw:
        raise ValueError(f"Image '{name}' is empty.")
    validate_file(name if isinstance(name, str) else "", len(raw))
    check_magic("image", raw)
    assert isinstance(name, str)
    ext = os.path.splitext(name)[1].lower().lstrip(".")
    raw = _maybe_downscale(raw)
    mime = _MIME_BY_EXT.get(ext, "image/jpeg")
    b64 = base64.b64encode(raw).decode("ascii")
    return Attachment(
        name=os.path.basename(name), mime=mime, size=len(raw), data_url=f"data:{mime};base64,{b64}"
    )


def _extract_pdf_text(raw: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(raw))
    # Cap pages AND chars: a 10k-page PDF must not OOM the phone.
    MAX_PDF_PAGES = 200
    texts: list[str] = []
    total = 0
    for i, page in enumerate(reader.pages):
        if i >= MAX_PDF_PAGES:
            texts.append("\n…(truncated: too many pages)…")
            break
        try:
            t = page.extract_text() or ""
        except Exception:
            t = ""
        total += len(t)
        texts.append(t)
        if total > RAG_FULL_CHARS:
            texts.append("\n…(truncated: too long)…")
            break
    joined = "\n".join(texts)
    return joined[: RAG_FULL_CHARS + 100]


def prepare_doc(name: object, raw: object) -> Attachment:
    if not isinstance(raw, (bytes, bytearray)):
        raise ValueError(f"Document '{name}' has no readable data.")
    raw = bytes(raw)
    if not raw:
        raise ValueError(f"Document '{name}' is empty.")
    validate_file(name if isinstance(name, str) else "", len(raw))
    assert isinstance(name, str)
    ext = os.path.splitext(name)[1].lower().lstrip(".")
    if ext == "pdf":
        # Magic-byte check before invoking the PDF parser (polyglot guard).
        if not raw.startswith(b"%PDF-"):
            raise ValueError(f"Document '{os.path.basename(name)}' is not a valid PDF.")
        try:
            text = _extract_pdf_text(raw)
        except Exception as e:
            raise ValueError(f"Could not read PDF '{os.path.basename(name)}': {e}") from e
    else:
        # Decode only what we keep: slice bytes first to avoid a 15MB spike.
        text = raw[: RAG_FULL_CHARS * 4].decode("utf-8", errors="replace")
        if len(raw) > RAG_FULL_CHARS * 4:
            text += "\n…(truncated: too long)…"
    if not isinstance(text, str):
        text = ""
    full_len = len(text)
    truncated = full_len > MAX_DOC_CHARS
    if full_len > RAG_FULL_CHARS:
        # Even RAG can't usefully index beyond this; hard-cut with flag.
        text = text[:RAG_FULL_CHARS]
    return Attachment(
        name=os.path.basename(name),
        mime="text/plain",
        size=len(raw),
        text=text,
        extra={"chars": len(text), "full_chars": full_len, "truncated": truncated},
    )


def prepare_file(name: object, raw: object) -> Attachment:
    kind = classify(name if isinstance(name, str) else "")
    if kind == "image":
        assert isinstance(name, str)
        return prepare_image(name, raw)  # type: ignore[arg-type]
    if kind == "doc":
        assert isinstance(name, str)
        return prepare_doc(name, raw)  # type: ignore[arg-type]
    raise ValueError(f"Unsupported file '{name}'.")


def chunk_text(text: object, size: object = 2000) -> list[str]:
    """v2 RAG hook (unused in v1 — simple attach+send only)."""
    if not isinstance(text, str) or not text:
        return [""]
    try:
        n = int(size)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        n = 2000
    n = max(100, min(20000, n))
    return [text[i : i + n] for i in range(0, len(text), n)] or [""]


def doc_block(att: object) -> str:
    if att is None or not hasattr(att, "extra"):
        return "[Attached file: unknown]"
    try:
        extra = att.extra if isinstance(att.extra, dict) else {}  # type: ignore[union-attr]
        note = " (truncated to fit context)" if extra.get("truncated") else ""
        body = (att.text if isinstance(att.text, str) else "")[:MAX_DOC_CHARS]  # type: ignore[union-attr]
        name = att.name if isinstance(att.name, str) else "file"  # type: ignore[union-attr]
        return f"[Attached file: {name}{note}]\n{body}"
    except Exception:
        return "[Attached file: unreadable]"


def build_chat_messages(
    history: list[Message],
    prompt: str,
    attachments: list[Attachment],
    provider_id: str,
    model: str,
    vision_override: bool = False,
) -> list[Message]:
    """Merge history + prompt + attachments; enforce vision capability.

    ``vision_override`` skips the text-only block after the user confirms
    Send-anyway (the provider itself may still reject with a 400, which
    surfaces as a normal error bubble).
    """
    images = [a for a in (attachments or []) if a is not None and getattr(a, "data_url", "")]
    docs = [a for a in (attachments or []) if a is not None and getattr(a, "text", "")]
    if not isinstance(history, list):
        history = []
    if not isinstance(prompt, str):
        prompt = ""
    if images and not vision_override and not supports_vision(provider_id, model):
        raise ValueError(
            f"Model '{model}' has no vision support — remove the "
            f"{len(images)} image(s) or switch to a vision model."
        )
    if images:
        parts: list = [{"type": "text", "text": prompt}]
        parts += [
            {"type": "text", "text": doc_block(a)} for a in docs
        ]
        parts += [
            {"type": "image_url", "image_url": {"url": a.data_url}} for a in images
        ]
        content: str | list = parts
    elif docs:
        content = prompt + "\n\n" + "\n\n".join(doc_block(a) for a in docs)
    else:
        content = prompt
    return [*history, Message("user", content)]
