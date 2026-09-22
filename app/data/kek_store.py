"""v0.4.0: hardware-backed key-encrypting-key (KEK) via flet-secure-storage.

Design:
- A random 32-byte KEK per install lives in platform secure storage
  (Android Keystore / iOS Keychain / Windows Credential Manager).
  API keys in preferences.json are Fernet-encrypted *under the KEK*.
- Replaces the v0.2/v0.3 device seed (sha256 of install path), which was
  recoverable by anyone reading the code + prefs file.
- SecureStorage is async; KeyStore stays sync. KEK is loaded once at
  startup (page.run_task) and cached in memory for the session.
- Fallback: if secure storage is unavailable, derive the old device seed
  and flag secure=False so Settings can show a warning badge.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import time
from typing import Any

PREFIX = "multiai."
KEK_KEY = f"{PREFIX}kek"
KEK_BYTES = 32


def _legacy_seed() -> bytes:
    """v0.2/v0.3 device seed — fallback + migration source only."""
    seed = f"{PREFIX}device-secret-v1:{os.path.abspath(os.getcwd())}".encode()
    return hashlib.sha256(seed).digest()


def legacy_fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError as e:
        raise RuntimeError("cryptography package is required for key storage") from e

    return Fernet(base64.urlsafe_b64encode(_legacy_seed()))


def fernet_for_kek(kek: bytes):
    try:
        from cryptography.fernet import Fernet
    except ImportError as e:
        raise RuntimeError("cryptography package is required for key storage") from e

    if not isinstance(kek, (bytes, bytearray)) or len(kek) != KEK_BYTES:
        raise ValueError("KEK must be 32 bytes")
    return Fernet(base64.urlsafe_b64encode(bytes(kek)))


class KekStore:
    """Loads/caches the install KEK. Sync accessors read the cache only."""

    _LOAD_TIMEOUT_S = 15.0

    def __init__(self, page: Any | None = None) -> None:
        self._page = page
        self._kek: bytes | None = None
        self._secure: bool = False
        self._loaded: bool = False
        self._storage: Any | None = None
        self._lock: asyncio.Lock | None = None

    def _get_lock(self) -> asyncio.Lock:
        # Lazily created so it binds to the running loop (constructing
        # asyncio.Lock() outside a loop pins the wrong loop on py3.10+).
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        lock = self._lock
        needs_new = (
            lock is None
            or (loop is not None and getattr(lock, "_loop", None) not in (None, loop))
        )
        if needs_new:
            self._lock = asyncio.Lock()
        return self._lock  # type: ignore[return-value]

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def secure(self) -> bool:
        return self._secure and self._kek is not None

    def cached_kek(self) -> bytes | None:
        return self._kek

    def _attach_storage(self):
        """Construct (once) the SecureStorage service and attach to page."""
        if self._storage is not None:
            return self._storage
        import flet_secure_storage as fss

        self._storage = fss.SecureStorage(
            android_options=fss.AndroidOptions(
                reset_on_error=False,
                migrate_on_algorithm_change=True,
                enforce_biometrics=False,
            )
        )
        page = self._page
        if page is not None:
            try:
                services = getattr(page, "services", None)
                if services is not None and self._storage not in services:
                    services.append(self._storage)
            except Exception:
                pass
        return self._storage

    async def load(self) -> tuple[bytes, bool]:
        """Return (kek, secure). Never raises — falls back to legacy seed.

        A corrupt stored value (bad base64 / wrong length) is backed up to
        "<KEK_KEY>.corrupt.<ts>" before a fresh KEK is generated, so a
        keystore glitch can never silently orphan preferences.json with no
        way back. Concurrent callers are serialized via an asyncio lock.
        """
        if self._loaded and self._kek is not None:
            return self._kek, self._secure
        async with self._get_lock():
            if self._loaded and self._kek is not None:
                return self._kek, self._secure
            try:
                storage = self._attach_storage()
                raw = await asyncio.wait_for(storage.get(KEK_KEY), timeout=self._LOAD_TIMEOUT_S)
                if isinstance(raw, str) and raw:
                    try:
                        kek = base64.b64decode(raw.encode("ascii"))
                    except Exception:
                        kek = None
                    if kek is not None and len(kek) == KEK_BYTES:
                        self._kek, self._secure, self._loaded = kek, True, True
                        return self._kek, True
                    # Corrupt entry — back it up before overwriting.
                    try:
                        backup_key = f"{KEK_KEY}.corrupt.{int(time.time())}"
                        await asyncio.wait_for(
                            storage.set(backup_key, raw), timeout=self._LOAD_TIMEOUT_S
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        pass
                kek = os.urandom(KEK_BYTES)
                await asyncio.wait_for(
                    storage.set(KEK_KEY, base64.b64encode(kek).decode("ascii")),
                    timeout=self._LOAD_TIMEOUT_S,
                )
                check = await asyncio.wait_for(storage.get(KEK_KEY), timeout=self._LOAD_TIMEOUT_S)
                if check:
                    self._kek, self._secure, self._loaded = kek, True, True
                    return self._kek, True
            except asyncio.CancelledError:
                raise
            except (asyncio.TimeoutError, Exception):
                pass
            # Fallback: legacy device seed (v0.2/v0.3 behavior).
            self._kek, self._secure, self._loaded = _legacy_seed(), False, True
            return self._kek, False

    def detach(self) -> None:
        """Remove our SecureStorage from page.services (avoid duplicates)."""
        try:
            services = getattr(self._page, "services", None)
            if services is not None and self._storage is not None:
                while self._storage in services:
                    services.remove(self._storage)
        except Exception:
            pass
        self._storage = None
