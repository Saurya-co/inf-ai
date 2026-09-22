"""Shared message types (P1 minimal; attachments go full in P3)."""

from dataclasses import dataclass, field


@dataclass
class Message:
    role: str  # "system" | "user" | "assistant"
    content: str | list  # str, or OpenAI-style parts list (P3 multimodal)

    def __post_init__(self) -> None:
        if self.role not in ("system", "user", "assistant"):
            raise ValueError(f"Invalid role {self.role!r}.")
        if not isinstance(self.content, (str, list)):
            raise ValueError("Message content must be str or list.")


@dataclass
class Attachment:
    """Placeholder for P3 — P1 only carries metadata, never sends bytes."""

    name: str
    mime: str = ""
    size: int = 0
    text: str = ""
    data_url: str = ""
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("Attachment name must be a non-empty string.")
        # Sanitize display name: strip directories, cap length.
        import os as _os

        base = _os.path.basename(self.name).strip() or "file"
        self.name = base[:200]
        if not isinstance(self.mime, str):
            self.mime = ""
        if not isinstance(self.size, int) or self.size < 0:
            self.size = 0
        if self.text is None:
            self.text = ""
        if not isinstance(self.text, str):
            raise ValueError("Attachment text must be a string.")
        if self.data_url is None:
            self.data_url = ""
        if not isinstance(self.data_url, str):
            raise ValueError("Attachment data_url must be a string.")
        if self.extra is None:
            self.extra = {}
        if not isinstance(self.extra, dict):
            raise ValueError("Attachment extra must be a dict.")
