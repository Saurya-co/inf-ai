"""Synchronous on-device BYOK store backed by the app sandbox.

Keys are namespaced `multiai.` to avoid collisions with other Flet apps.

Security (v0.3.0): values for `*.key` are encrypted at rest with Fernet
(`cryptography` is a hard dependency). A legacy plaintext fallback is kept
only for upgrades that predate encryption — any plaintext `*.key` found is
migrated to encrypted form on first open. Never log values.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import threading
import time
from typing import Any

PREFIX = "multiai."
ENC_PREFIX = "enc:"
LEGACY_NOTE = "v0.1 plaintext"


def _try_decrypt(fernet, token: str) -> str | None:
    """Return plaintext for an ENC_PREFIX token, or None on any failure."""
    if fernet is None or not isinstance(token, str) or not token.startswith(ENC_PREFIX):
        return None
    try:
        return fernet.decrypt(token[len(ENC_PREFIX):].encode()).decode()
    except Exception:
        return None


def _fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        return None
    # LEGACY device seed (v0.2/v0.3): sha256 of the launch directory.
    # Predictable + cwd-dependent by design flaw — kept ONLY as a migration
    # source for prefs written before the hardware-backed KEK (kek_store).
    # Startup rekeys everything to the KEK ASAP; new installs should never
    # rely on this. Do NOT change the derivation (it would orphan old prefs).
    seed = f"{PREFIX}device-secret-v1:{os.path.abspath(os.getcwd())}".encode()
    digest = hashlib.sha256(seed).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


class KeyStore:
    def __init__(self, page: Any | None = None, fernet=None) -> None:
        self._page = page
        self._persist_lock = threading.RLock()
        try:
            from app.data.paths import app_data_dir

            self._path = os.path.join(app_data_dir(), "preferences.json")
        except Exception:
            self._path = os.path.join(os.getcwd(), "data", "preferences.json")
        self._mem: dict[str, Any] = {}
        # v0.4.0: caller may inject a KEK-backed Fernet (see kek_store).
        # Otherwise fall back to the legacy device seed (v0.2/v0.3).
        self._fernet = fernet if fernet is not None else _fernet()
        # v0.4.0: None = KEK not loaded yet; True = hardware-backed KEK;
        # False = legacy device-seed fallback. Set by startup preload.
        self.secure_backing: bool | None = None
        try:
            with open(self._path, encoding="utf-8") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, dict):
                self._mem = loaded
            else:
                self._backup_corrupt_prefs("non-dict-root")
        except json.JSONDecodeError:
            self._backup_corrupt_prefs("json-decode-error")
        except (OSError, ValueError, TypeError):
            pass
        if self._fernet is not None:
            self._migrate_plaintext_keys()

    def _backup_corrupt_prefs(self, reason: str) -> None:
        """Preserve a corrupt prefs file instead of silently discarding it."""
        try:
            if os.path.exists(self._path) and os.path.getsize(self._path) > 0:
                backup = f"{self._path}.corrupt.{int(time.time())}"
                shutil.copyfile(self._path, backup)
        except OSError:
            pass
        self._mem = {}

    def rekey(self, new_fernet) -> bool:
        """Re-encrypt all *.key values under new_fernet.

        Understands plaintext legacy values AND values encrypted by *any*
        previous Fernet (legacy seed or older KEK): tries the new key first
        (idempotent re-run), then the current one, then stores plaintext
        legacy values encrypted. Returns True if anything changed.
        Never assigns a None/invalid fernet (returns False instead).
        """
        if new_fernet is None or not hasattr(new_fernet, "encrypt"):
            return False
        with self._persist_lock:
            old = self._fernet
            changed = False
            for k, v in list(self._mem.items()):
                if not self._is_key_field(k) or not isinstance(v, str) or not v:
                    continue
                if v.startswith(ENC_PREFIX):
                    if _try_decrypt(new_fernet, v) is not None:
                        continue  # already under the new key — idempotent re-run
                    plain = _try_decrypt(old, v)
                    if plain is None:
                        continue  # undecryptable — leave untouched, never re-encrypt garbage
                else:
                    plain = v  # legacy plaintext — encrypt it under the new key
                try:
                    fresh = ENC_PREFIX + new_fernet.encrypt(plain.encode()).decode()
                except Exception:
                    continue
                self._mem[k] = fresh
                changed = True
            self._fernet = new_fernet
            if changed:
                self._persist()
            return changed

    def _storage(self) -> Any | None:
        # Flet 0.80+ exposes SharedPreferences methods as async service calls.
        # This store is intentionally synchronous because settings are read while
        # building controls, so use the local app sandbox for reliable persistence.
        return None

    def _k(self, provider_id: str, field: str) -> str:
        return f"{PREFIX}{provider_id}.{field}"

    def _is_key_field(self, full_key: str) -> bool:
        return full_key.startswith(PREFIX) and full_key.endswith(".key")

    def _encrypt(self, value: str) -> str:
        if self._fernet is None:
            return value
        if not isinstance(value, str):
            return value  # type: ignore[return-value]
        try:
            return ENC_PREFIX + self._fernet.encrypt(value.encode()).decode()
        except Exception:
            return value

    def _decrypt(self, stored: Any) -> Any:
        """Decrypt an ENC_PREFIX token. Returns None on any failure.

        Callers map None -> default, so undecryptable ciphertext is NEVER
        leaked back as if it were a key (previous behavior returned the
        raw "enc:..." string, which then failed auth opaquely).
        """
        if not isinstance(stored, str) or not stored.startswith(ENC_PREFIX):
            return stored
        if self._fernet is None:
            return None
        try:
            return self._fernet.decrypt(stored[len(ENC_PREFIX):].encode()).decode()
        except Exception:
            return None

    def _migrate_plaintext_keys(self) -> None:
        """One-time upgrade: encrypt any plaintext *.key values in place.

        Only counts a key as migrated when encryption actually produced an
        ENC_PREFIX value — a failed encrypt must not flip changed=True and
        rewrite the file for nothing.
        """
        if self._fernet is None:
            return
        changed = False
        for k, v in list(self._mem.items()):
            if self._is_key_field(k) and isinstance(v, str) and v and not v.startswith(ENC_PREFIX):
                enc = self._encrypt(v)
                if isinstance(enc, str) and enc.startswith(ENC_PREFIX) and enc != v:
                    self._mem[k] = enc
                    changed = True
        if changed:
            self._persist()

    def _persist(self) -> bool:
        """Atomic persist: write temp file + os.replace, 0600 on POSIX.

        Returns True on success. A torn write (crash mid-save) can no
        longer truncate preferences.json to 0 bytes.
        """
        with self._persist_lock:
            try:
                directory = os.path.dirname(self._path) or "."
                os.makedirs(directory, exist_ok=True)
                tmp = self._path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as handle:
                    json.dump(self._mem, handle, ensure_ascii=False)
                    handle.flush()
                    try:
                        os.fsync(handle.fileno())
                    except OSError:
                        pass
                try:
                    os.chmod(tmp, 0o600)
                except OSError:
                    pass  # Windows: no POSIX perms — sandbox ACLs still apply
                os.replace(tmp, self._path)
                return True
            except (OSError, TypeError, ValueError):
                try:
                    if os.path.exists(self._path + ".tmp"):
                        os.remove(self._path + ".tmp")
                except OSError:
                    pass
                return False

    @property
    def encrypted(self) -> bool:
        return self._fernet is not None

    def strict_require_hw(self) -> bool:
        """Fail-closed opt-in: when True, keys are unavailable unless the
        hardware-backed KEK is loaded (secure_backing is True)."""
        try:
            return str(self._mem.get(f"{PREFIX}sec.require_hw", "")).strip().lower() == "true"
        except Exception:
            return False

    def set_strict_require_hw(self, on: bool) -> None:
        with self._persist_lock:
            self._mem[f"{PREFIX}sec.require_hw"] = "true" if on else ""
            self._persist()

    def keys_unlocked(self) -> bool:
        """False when fail-closed mode blocks key reads (no HW KEK yet)."""
        if self.strict_require_hw() and self.secure_backing is not True:
            return False
        return True

    def get(self, provider_id: str, field: str, default: str = "") -> str:
        store = self._storage()
        if store is not None:
            try:
                val = store.get(self._k(provider_id, field))
                return val if isinstance(val, str) else (default if val is None else str(val))
            except (RuntimeError, AttributeError, TypeError, ValueError):
                pass
        raw = self._mem.get(self._k(provider_id, field), default)
        if isinstance(raw, str) and raw.startswith(ENC_PREFIX):
            dec = self._decrypt(raw)
            # None = undecryptable (wrong KEK / corrupt) -> default, never ciphertext.
            return dec if isinstance(dec, str) else default
        if isinstance(raw, str):
            return raw
        if raw is None:
            return default
        return str(raw) if isinstance(default, str) else raw

    def set(self, provider_id: str, field: str, value: str) -> None:
        if not isinstance(provider_id, str) or not isinstance(field, str):
            raise ValueError("provider_id and field must be strings.")
        if not provider_id or not field:
            raise ValueError("provider_id and field must be non-empty.")
        if not isinstance(value, str):
            raise ValueError("value must be a string.")
        if len(value) > 20000:
            raise ValueError("value too long.")
        full = self._k(provider_id, field)
        if self._is_key_field(full) and value:
            value = self._encrypt(value)
        with self._persist_lock:
            self._mem[full] = value
            self._persist()

    # Convenience accessors
    def get_key(self, provider_id: str) -> str:
        # Fail-closed: never decrypt from legacy fallback when the user
        # opted into hardware-only mode and the HW KEK isn't loaded.
        if self.strict_require_hw() and self.secure_backing is not True:
            return ""
        return self.get(provider_id, "key")

    def set_key(self, provider_id: str, value: str) -> None:
        self.set(provider_id, "key", value)

    def get_model(self, provider_id: str, default: str = "") -> str:
        return self.get(provider_id, "model", default)

    def set_model(self, provider_id: str, value: str) -> None:
        self.set(provider_id, "model", value)

    def get_base_url(self, provider_id: str, default: str = "") -> str:
        return self.get(provider_id, "base_url", default)

    def set_base_url(self, provider_id: str, value: str) -> None:
        self.set(provider_id, "base_url", value)

    @staticmethod
    def mask(key: str) -> str:
        key = (key or "").strip()
        if len(key) <= 7:
            return "••••" if key else "not set"
        return f"••••{key[-4:]}"
