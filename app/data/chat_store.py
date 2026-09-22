"""P4 persistence: SQLite conversations + messages + md/json export.

stdlib only (sqlite3/json) — Android-safe. Content may be str (plain) or
list (multimodal parts) and is stored as JSON so history round-trips.
DB location: app-data dir (see app.data.paths — cwd-anchored when
writable, relocated when the launcher parks us in System32). Override
with db_path for tests.
"""

import json
import os
import re
import sqlite3
import threading
import time

from app.core.types import Message

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL DEFAULT 'New chat',
    provider TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conv_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content_json TEXT NOT NULL DEFAULT '""',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conv_id, id);
-- v0.4.0 RAG: chunked long-document excerpts per conversation.
CREATE TABLE IF NOT EXISTS doc_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conv_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    attachment TEXT NOT NULL DEFAULT '',
    chunk_idx INTEGER NOT NULL DEFAULT 0,
    content TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_conv ON doc_chunks(conv_id, id);
"""

VALID_ROLES = frozenset({"user", "assistant", "system"})


def _escape_like(raw: str) -> str:
    """Escape FTS/LIKE wildcards so a literal search never breaks syntax."""
    return (
        raw.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )


def _sanitize_fts(raw: str) -> str:
    """Strip FTS5 operators so user input can't raise OperationalError.

    FTS5 treats `" * : ( ) NEAR NOT AND OR` specially; an unbalanced
    quote or bare operator crashes MATCH. We keep it simple: drop
    operator punctuation, collapse whitespace, and truncate — the LIKE
    fallback still finds literal text.
    """
    cleaned = re.sub(r'["*:()^~\-+]', " ", raw or "")
    cleaned = re.sub(r"\b(AND|OR|NOT|NEAR)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:200]


def _clamp_limit(limit: object, default: int = 100, maximum: int = 1000) -> int:
    try:
        n = int(limit)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(1, min(maximum, n))


def default_db_path() -> str:
    from app.data.paths import app_data_dir

    return os.path.join(app_data_dir(), "chat.db")


class ChatStore:
    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or default_db_path()
        self._closed = False
        self._lock = threading.RLock()
        try:
            parent = os.path.dirname(os.path.abspath(self.db_path))
            if parent:
                os.makedirs(parent, exist_ok=True)
        except OSError:
            pass
        # Restrict DB file permissions on POSIX (chats are plaintext).
        try:
            if self.db_path != ":memory:" and os.path.exists(self.db_path):
                os.chmod(self.db_path, 0o600)
        except OSError:
            pass
        try:
            self._conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
        except sqlite3.Error:
            # Last resort: in-memory so the app stays usable, history off.
            self._conn = sqlite3.connect(":memory:", timeout=30.0, check_same_thread=False)
            self.db_path = ":memory:"
        try:
            self._conn.execute("PRAGMA foreign_keys = ON")
        except sqlite3.Error:
            pass
        try:
            self._conn.execute("PRAGMA busy_timeout = 5000")
        except sqlite3.Error:
            pass
        try:
            self._conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.Error:
            pass
        try:
            self._conn.execute("PRAGMA synchronous = NORMAL")
        except sqlite3.Error:
            pass
        try:
            with self._lock:
                self._conn.executescript(SCHEMA)
                self._ensure_history_flags()
                self._ensure_token_totals()
                self._fts = self._ensure_fts()
                try:
                    self._conn.commit()
                except sqlite3.Error:
                    try:
                        self._conn.rollback()
                    except sqlite3.Error:
                        pass
        except sqlite3.Error:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass
            raise

    def _ensure_open(self) -> None:
        if self._closed:
            raise sqlite3.ProgrammingError("ChatStore is closed.")

    def __enter__(self) -> ChatStore:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _ensure_history_flags(self) -> None:
        """Additive v0.4 refinement migration: pinned/archived flags.

        Idempotent ALTER TABLE — existing installs backfill 0, no data loss.
        """
        try:
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(conversations)")}
        except sqlite3.Error:
            return
        try:
            if "pinned" not in cols:
                self._conn.execute("ALTER TABLE conversations ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
            if "archived" not in cols:
                self._conn.execute("ALTER TABLE conversations ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
            self._conn.commit()
        except sqlite3.Error:
            pass

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            with self._lock:
                try:
                    self._conn.commit()
                except sqlite3.Error:
                    try:
                        self._conn.rollback()
                    except sqlite3.Error:
                        pass
                try:
                    self._conn.close()
                except sqlite3.Error:
                    pass
        except Exception:
            pass

    def __del__(self) -> None:  # best-effort: never leak -wal/-shm handles
        try:
            self.close()
        except Exception:
            pass

    def _ensure_token_totals(self) -> None:
        """Additive v0.5 R7 migration: per-conversation token totals.

        Idempotent ALTER TABLE — existing installs backfill 0, no data loss.
        """
        try:
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(conversations)")}
        except sqlite3.Error:
            return
        try:
            if "input_tokens" not in cols:
                self._conn.execute("ALTER TABLE conversations ADD COLUMN input_tokens INTEGER NOT NULL DEFAULT 0")
            if "output_tokens" not in cols:
                self._conn.execute("ALTER TABLE conversations ADD COLUMN output_tokens INTEGER NOT NULL DEFAULT 0")
            self._conn.commit()
        except sqlite3.Error:
            pass

    # ---- conversations ----
    def _conv_exists(self, conv_id: int) -> bool:
        try:
            row = self._conn.execute(
                "SELECT 1 FROM conversations WHERE id = ?", (conv_id,)
            ).fetchone()
            return row is not None
        except sqlite3.Error:
            return False

    def _require_conv(self, conv_id: int) -> None:
        try:
            cid = int(conv_id)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Invalid conversation id: {conv_id!r}") from e
        if not self._conv_exists(cid):
            raise ValueError(f"Unknown conversation: {cid}")

    @staticmethod
    def _check_role(role: str) -> str:
        if role not in VALID_ROLES:
            raise ValueError(f"Invalid role {role!r} (want user|assistant|system).")
        return role

    def create_conversation(self, title: str, provider: str, model: str) -> int:
        self._ensure_open()
        now = int(time.time())
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO conversations (title, provider, model, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (title or "New chat", provider or "", model or "", now, now),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def _conversation_meta(self, conv_id: int) -> dict:
        """Fetch one conversation row without scanning the whole table."""
        self._ensure_open()
        try:
            cid = int(conv_id)
        except (TypeError, ValueError):
            return {"id": conv_id, "missing": True}
        with self._lock:
            try:
                cur = self._conn.execute(
                    "SELECT id, title, provider, model, created_at, updated_at,"
                    " COALESCE(pinned,0) AS pinned, COALESCE(archived,0) AS archived,"
                    " COALESCE(input_tokens,0) AS input_tokens,"
                    " COALESCE(output_tokens,0) AS output_tokens"
                    " FROM conversations WHERE id = ?",
                    (cid,),
                )
            except sqlite3.Error:
                try:
                    cur = self._conn.execute(
                        "SELECT id, title, provider, model, created_at, updated_at"
                        " FROM conversations WHERE id = ?",
                        (cid,),
                    )
                except sqlite3.Error:
                    return {"id": conv_id, "missing": True}
            row = cur.fetchone()
            if row is None:
                return {"id": conv_id, "missing": True}
            cols = [c[0] for c in cur.description]
            meta = dict(zip(cols, row))
            meta.setdefault("pinned", 0)
            meta.setdefault("archived", 0)
            meta.setdefault("input_tokens", 0)
            meta.setdefault("output_tokens", 0)
            return meta

    def list_conversations(self, limit: int = 100) -> list[dict]:
        self._ensure_open()
        limit = _clamp_limit(limit, default=100, maximum=1000)
        with self._lock:
            try:
                cur = self._conn.execute(
                    "SELECT id, title, provider, model, created_at, updated_at,"
                    " COALESCE(pinned,0) AS pinned, COALESCE(archived,0) AS archived,"
                    " COALESCE(input_tokens,0) AS input_tokens,"
                    " COALESCE(output_tokens,0) AS output_tokens"
                    " FROM conversations ORDER BY pinned DESC, updated_at DESC, id DESC LIMIT ?",
                    (limit,),
                )
            except sqlite3.Error:
                try:
                    cur = self._conn.execute(
                        "SELECT id, title, provider, model, created_at, updated_at"
                        " FROM conversations ORDER BY updated_at DESC, id DESC LIMIT ?",
                        (limit,),
                    )
                except sqlite3.Error:
                    return []
            try:
                cols = [c[0] for c in cur.description]
                rows = [dict(zip(cols, row)) for row in cur.fetchall()]
            except sqlite3.Error:
                return []
        for r in rows:
            r.setdefault("pinned", 0)
            r.setdefault("archived", 0)
            r.setdefault("input_tokens", 0)
            r.setdefault("output_tokens", 0)
        return rows

    def add_token_usage(self, conv_id: int, input_tokens: int, output_tokens: int) -> None:
        """Accumulate per-conversation token totals (v0.5 R7 metering)."""
        self._ensure_open()
        try:
            with self._lock:
                self._conn.execute(
                    "UPDATE conversations SET input_tokens = COALESCE(input_tokens,0) + ?,"
                    " output_tokens = COALESCE(output_tokens,0) + ? WHERE id = ?",
                    (max(0, int(input_tokens)), max(0, int(output_tokens)), int(conv_id)),
                )
                self._conn.commit()
        except (sqlite3.Error, ValueError, TypeError):
            try:
                with self._lock:
                    self._conn.rollback()
            except sqlite3.Error:
                pass

    def set_pinned(self, conv_id: int, pinned: bool) -> None:
        self._ensure_open()
        self._require_conv(conv_id)
        self._ensure_history_flags()
        with self._lock:
            try:
                self._conn.execute(
                    "UPDATE conversations SET pinned = ?, updated_at = ? WHERE id = ?",
                    (1 if pinned else 0, int(time.time()), conv_id),
                )
                self._conn.commit()
            except sqlite3.OperationalError:
                # Column may still be missing if the migration was skipped —
                # retry the migration once before giving up.
                try:
                    self._conn.rollback()
                except sqlite3.Error:
                    pass
                self._ensure_history_flags()
                try:
                    self._conn.execute(
                        "UPDATE conversations SET pinned = ?, updated_at = ? WHERE id = ?",
                        (1 if pinned else 0, int(time.time()), conv_id),
                    )
                    self._conn.commit()
                except sqlite3.Error:
                    try:
                        self._conn.rollback()
                    except sqlite3.Error:
                        pass
                    raise

    def set_archived(self, conv_id: int, archived: bool) -> None:
        self._ensure_open()
        self._require_conv(conv_id)
        self._ensure_history_flags()
        with self._lock:
            try:
                self._conn.execute(
                    "UPDATE conversations SET archived = ?, updated_at = ? WHERE id = ?",
                    (1 if archived else 0, int(time.time()), conv_id),
                )
                self._conn.commit()
            except sqlite3.OperationalError:
                try:
                    self._conn.rollback()
                except sqlite3.Error:
                    pass
                self._ensure_history_flags()
                try:
                    self._conn.execute(
                        "UPDATE conversations SET archived = ?, updated_at = ? WHERE id = ?",
                        (1 if archived else 0, int(time.time()), conv_id),
                    )
                    self._conn.commit()
                except sqlite3.Error:
                    try:
                        self._conn.rollback()
                    except sqlite3.Error:
                        pass
                    raise

    def rename_conversation(self, conv_id: int, title: str) -> None:
        self._ensure_open()
        self._require_conv(conv_id)
        with self._lock:
            self._conn.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                ((title or "New chat")[:200], int(time.time()), conv_id),
            )
            self._conn.commit()

    def delete_conversation(self, conv_id: int) -> None:
        self._ensure_open()
        with self._lock:
            with self._conn:
                self._conn.execute("DELETE FROM messages WHERE conv_id = ?", (conv_id,))
                self._conn.execute("DELETE FROM doc_chunks WHERE conv_id = ?", (conv_id,))
                self._conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
            # Best-effort secure-delete: VACUUM reclaims freelist pages so
            # deleted chats don't linger in the file/WAL for forensics.
            try:
                self._conn.execute("VACUUM")
            except sqlite3.Error:
                pass

    def touch(self, conv_id: int, provider: str = "", model: str = "") -> None:
        self._ensure_open()
        self._require_conv(conv_id)
        with self._lock:
            if provider or model:
                self._conn.execute(
                    "UPDATE conversations SET updated_at = ?, provider = ?, model = ?"
                    " WHERE id = ?",
                    (int(time.time()), (provider or "")[:120], (model or "")[:200], conv_id),
                )
            else:
                self._conn.execute(
                    "UPDATE conversations SET updated_at = ? WHERE id = ?",
                    (int(time.time()), conv_id),
                )
            self._conn.commit()

    # ---- messages ----
    def _ensure_fts(self) -> bool:
        """Create FTS5 index over message bodies. Returns True if available."""
        try:
            self._conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5("
                "content, conv_id UNINDEXED, tokenize='porter')"
            )
            self._conn.execute(
                "CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages "
                "BEGIN INSERT INTO messages_fts(rowid, content, conv_id) "
                "VALUES (new.id, new.content_json, new.conv_id); END"
            )
            self._conn.execute(
                "CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages "
                "BEGIN DELETE FROM messages_fts WHERE rowid = old.id; END"
            )
            # Repair rows missing from FTS (upgrade installs, partial backfill,
            # or replace_messages races) — not just when the table is empty.
            try:
                missing = self._conn.execute(
                    "SELECT COUNT(*) FROM messages WHERE id NOT IN "
                    "(SELECT rowid FROM messages_fts)"
                ).fetchone()[0]
            except sqlite3.Error:
                missing = 0
            if missing:
                self._conn.execute(
                    "INSERT OR IGNORE INTO messages_fts(rowid, content, conv_id) "
                    "SELECT id, content_json, conv_id FROM messages "
                    "WHERE id NOT IN (SELECT rowid FROM messages_fts)"
                )
            return True
        except sqlite3.Error:
            return False

    def search_conversations(self, query: str, limit: int = 50) -> list[int]:
        """Return conv_ids with message-body matches (FTS5, LIKE fallback)."""
        self._ensure_open()
        q = (query or "").strip()[:200]
        if not q:
            return []
        limit = _clamp_limit(limit, default=50, maximum=200)
        with self._lock:
            try:
                if self._fts:
                    safe = _sanitize_fts(q)
                    if safe:
                        cur = self._conn.execute(
                            "SELECT DISTINCT conv_id FROM messages_fts "
                            "WHERE messages_fts MATCH ? LIMIT ?",
                            (safe, limit),
                        )
                        return [r[0] for r in cur.fetchall()]
            except sqlite3.Error:
                pass
            try:
                cur = self._conn.execute(
                    "SELECT DISTINCT conv_id FROM messages WHERE content_json LIKE ? ESCAPE '\\' LIMIT ?",
                    (f"%{_escape_like(q)}%", limit),
                )
                return [r[0] for r in cur.fetchall()]
            except sqlite3.Error:
                return []

    @staticmethod
    def _encode(content: str | list) -> str:
        return json.dumps(content, ensure_ascii=False)

    @staticmethod
    def _decode(raw: object) -> str | list:
        if raw is None:
            return ""
        if isinstance(raw, (bytes, bytearray)):
            try:
                raw = bytes(raw).decode("utf-8", errors="replace")
            except Exception:
                return ""
        if not isinstance(raw, str):
            return raw if isinstance(raw, list) else ""
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return raw

    def add_message(self, conv_id: int, role: str, content: str | list) -> int:
        self._ensure_open()
        self._require_conv(conv_id)
        self._check_role(role)
        try:
            encoded = self._encode(content)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Message content is not JSON-encodable: {e}") from e
        with self._lock:
            with self._conn:
                cur = self._conn.execute(
                    "INSERT INTO messages (conv_id, role, content_json, created_at)"
                    " VALUES (?, ?, ?, ?)",
                    (conv_id, role, encoded, int(time.time())),
                )
                self._conn.execute(
                    "UPDATE conversations SET updated_at = ? WHERE id = ?",
                    (int(time.time()), conv_id),
                )
                return int(cur.lastrowid)

    def get_messages(self, conv_id: int) -> list[Message]:
        self._ensure_open()
        with self._lock:
            try:
                cur = self._conn.execute(
                    "SELECT role, content_json FROM messages WHERE conv_id = ? ORDER BY id",
                    (conv_id,),
                )
                rows = cur.fetchall()
            except sqlite3.Error:
                return []
        out: list[Message] = []
        for role, raw in rows:
            try:
                content = self._decode(raw)
                if not isinstance(content, (str, list)):
                    content = ""
                if role not in ("user", "assistant", "system"):
                    role = "user"  # coerce corrupt rows instead of crashing load
                out.append(Message(role, content))
            except (ValueError, TypeError):
                continue  # skip one corrupt row, keep the rest of history
        return out

    def replace_messages(self, conv_id: int, messages: list[Message]) -> None:
        """Replace a conversation after context compaction (atomic)."""
        self._ensure_open()
        self._require_conv(conv_id)
        messages = list(messages or [])
        if len(messages) > 1000:
            raise ValueError("Too many messages (max 1000).")
        for m in messages:
            if m is None:
                raise ValueError("Message list contains None.")
            self._check_role(m.role)
            try:
                self._encode(m.content)
            except (TypeError, ValueError) as e:
                raise ValueError(f"Message content is not JSON-encodable: {e}") from e
        with self._lock:
            with self._conn:
                self._conn.execute("DELETE FROM messages WHERE conv_id = ?", (conv_id,))
                now = int(time.time())
                for message in messages:
                    self._conn.execute(
                        "INSERT INTO messages (conv_id, role, content_json, created_at)"
                        " VALUES (?, ?, ?, ?)",
                        (conv_id, message.role, self._encode(message.content), now),
                    )
                self._conn.execute(
                    "UPDATE conversations SET updated_at = ? WHERE id = ?",
                    (now, conv_id),
                )

    # ---- v0.4.0 RAG: long-document chunks ----
    def index_doc_chunks(self, conv_id: int, attachment: str, chunks: list[str]) -> int:
        """(Re)index one attachment's chunks. Returns chunk count (atomic)."""
        self._ensure_open()
        self._require_conv(conv_id)
        if not attachment or not isinstance(attachment, str):
            raise ValueError("Attachment name must be a non-empty string.")
        attachment = attachment[:200]
        if isinstance(chunks, str):
            chunks = [chunks]
        if chunks is None:
            chunks = []
        try:
            seq = list(chunks)
        except TypeError:
            raise ValueError("chunks must be a list of strings.")
        if len(seq) > 2000:
            raise ValueError("Too many chunks (max 2000).")
        texts = [c for c in seq if isinstance(c, str) and c][:2000]
        with self._lock:
            with self._conn:
                self._conn.execute(
                    "DELETE FROM doc_chunks WHERE conv_id = ? AND attachment = ?",
                    (conv_id, attachment),
                )
                now = int(time.time())
                for i, text in enumerate(texts):
                    self._conn.execute(
                        "INSERT INTO doc_chunks (conv_id, attachment, chunk_idx, content, created_at)"
                        " VALUES (?, ?, ?, ?, ?)",
                        (conv_id, attachment, i, text[:20000], now),
                    )
        return len(texts)

    def get_doc_chunks(self, conv_id: int) -> dict[str, list[str]]:
        """Return {attachment: [chunk_text...]} in chunk order."""
        self._ensure_open()
        with self._lock:
            try:
                cur = self._conn.execute(
                    "SELECT attachment, content FROM doc_chunks"
                    " WHERE conv_id = ? ORDER BY attachment, chunk_idx",
                    (conv_id,),
                )
                rows = cur.fetchall()
            except sqlite3.Error:
                return {}
        out: dict[str, list[str]] = {}
        for name, content in rows:
            out.setdefault(name, []).append(content)
        return out

    def clear_doc_chunks(self, conv_id: int) -> int:
        """Delete a conversation's RAG index. Returns rows removed."""
        self._ensure_open()
        try:
            cid = int(conv_id)
        except (TypeError, ValueError):
            return 0
        try:
            with self._lock:
                cur = self._conn.execute("DELETE FROM doc_chunks WHERE conv_id = ?", (cid,))
                self._conn.commit()
                return int(cur.rowcount or 0)
        except sqlite3.Error:
            try:
                with self._lock:
                    self._conn.rollback()
            except sqlite3.Error:
                pass
            return 0

    def delete_doc_chunks(self, conv_id: int, attachment: str) -> int:
        """Delete one attachment's chunks. Returns rows removed."""
        self._ensure_open()
        if not isinstance(attachment, str) or not attachment:
            return 0
        try:
            cid = int(conv_id)
        except (TypeError, ValueError):
            return 0
        try:
            with self._lock:
                cur = self._conn.execute(
                    "DELETE FROM doc_chunks WHERE conv_id = ? AND attachment = ?",
                    (cid, attachment),
                )
                self._conn.commit()
                return int(cur.rowcount or 0)
        except sqlite3.Error:
            try:
                with self._lock:
                    self._conn.rollback()
            except sqlite3.Error:
                pass
            return 0

    # ---- export ----
    @staticmethod
    def _export_content(content: str | list):
        """Strip image blobs from exports (privacy + size)."""
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return ""
        out = []
        imgs = 0
        for p in content:
            if not isinstance(p, dict):
                continue
            if p.get("type") in ("image_url", "image"):
                imgs += 1
                continue
            if p.get("type") == "text" and isinstance(p.get("text"), str):
                out.append({"type": "text", "text": p["text"]})
        if imgs and not out:
            return f"_(+ {imgs} attached image(s) removed from export)_"
        if imgs:
            out.append({"type": "text", "text": f"_(+ {imgs} attached image(s) removed)_"})
        return out

    def export_json(self, conv_id: int) -> str:
        meta = self._conversation_meta(conv_id)
        data = {
            "conversation": meta,
            "messages": [
                {"role": m.role, "content": self._export_content(m.content)}
                for m in self.get_messages(conv_id)
            ],
        }
        return json.dumps(data, ensure_ascii=False, indent=2)

    @staticmethod
    def _has_images(content: str | list) -> bool:
        return isinstance(content, list) and any(
            isinstance(p, dict)
            and (p.get("type") == "image_url" or p.get("type") == "image")
            for p in content
        )

    def export_markdown(self, conv_id: int) -> str:
        meta = self._conversation_meta(conv_id)
        title = (meta.get("title") if isinstance(meta, dict) else "") or "Chat"
        lines = [f"# {title}", ""]
        for m in self.get_messages(conv_id):
            who = {"user": "You", "assistant": "Assistant"}.get(m.role, m.role)
            if isinstance(m.content, str):
                body = m.content
            else:
                body = "\n".join(
                    p.get("text", "")
                    for p in m.content
                    if isinstance(p, dict) and p.get("type") == "text"
                )
                if self._has_images(m.content):
                    body += "\n\n_(+ attached images)_"
            lines += [f"## {who}", "", body, ""]
        return "\n".join(lines)
