"""v0.4.0: optional app lock — PIN gate + biometric unlock + recovery.

- PIN: 4–8 digits, PBKDF2-HMAC-SHA256 (200k rounds, stdlib hashlib),
  salt + hash stored in prefs (never the PIN itself).
- Biometric unlock: a second SecureStorage profile with
  enforce_biometrics=True guarding a random unlock token. Reading it
  triggers the OS prompt; success returns the token. Gracefully
  degrades where biometrics are unavailable.
- Recovery: "forgot PIN" wipes lock prefs AND all API keys (chats kept),
  so nobody is ever permanently locked out.

v0.5.1 fix: the original AndroidOptions used enforce_biometrics=True
with the default RSA key cipher, which flutter_secure_storage rejects —
biometrics REQUIRE key_cipher AES_GCM_NO_PADDING on API 28+. That is why
"Biometric unlock" could never be enabled on phones. This module now uses
the documented Required-Biometrics combo + prompt titles, iOS biometry
flags, and surfaces the real platform error instead of a generic
"unavailable" so users can fix enrollment.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

PIN_MIN_LEN = 4
PIN_MAX_LEN = 8
PBKDF2_ROUNDS = 200_000
UNLOCK_TOKEN_KEY = "multiai.unlock-token"

# Brute-force resistance: in-memory + persisted counters.
MAX_PIN_ATTEMPTS = 5
LOCKOUT_SECONDS = 30


def valid_pin(pin: object) -> bool:
    if not isinstance(pin, str):
        return False
    p = pin.strip()
    return p.isdigit() and PIN_MIN_LEN <= len(p) <= PIN_MAX_LEN


def new_salt() -> str:
    return secrets.token_hex(16)


def hash_pin(pin: object, salt_hex: object) -> str:
    if not isinstance(pin, str):
        raise ValueError("Malformed PIN.")
    if not isinstance(salt_hex, str):
        raise ValueError("Malformed PIN salt.")
    try:
        salt = bytes.fromhex(salt_hex.strip())
    except (ValueError, TypeError, AttributeError) as e:
        raise ValueError("Malformed PIN salt.") from e
    if len(salt) < 8:
        raise ValueError("Malformed PIN salt.")
    dk = hashlib.pbkdf2_hmac(
        "sha256", (pin or "").strip().encode(), salt, PBKDF2_ROUNDS
    )
    return dk.hex()


def verify_pin(pin: str, salt_hex: str, expected_hex: str) -> bool:
    try:
        if not salt_hex or not expected_hex:
            return False
        return hmac.compare_digest(hash_pin(pin, salt_hex), expected_hex)
    except Exception:
        return False


def pin_locked_out(store) -> tuple[bool, int]:
    """Check exponential lockout after failed PIN attempts.

    Returns (locked, seconds_remaining). Counters live in KeyStore so they
    survive restarts; success clears them via pin_success().
    """
    import time as _t

    try:
        fails = int((store.get("lock", "fails", "0") or "0").strip() or 0)
    except Exception:
        fails = 0
    try:
        until = float((store.get("lock", "lockout_until", "0") or "0").strip() or 0)
    except Exception:
        until = 0.0
    now = _t.time()
    if until and now < until:
        return True, int(until - now) + 1
    if fails >= MAX_PIN_ATTEMPTS:
        # First lockout window (subsequent windows extend in pin_failed).
        return False, 0
    return False, 0


def pin_failed(store) -> int:
    """Record a failed attempt; returns seconds until retry (0 if none)."""
    import time as _t

    try:
        fails = int((store.get("lock", "fails", "0") or "0").strip() or 0)
    except Exception:
        fails = 0
    fails += 1
    try:
        store.set("lock", "fails", str(fails))
    except Exception:
        pass
    if fails >= MAX_PIN_ATTEMPTS:
        backoff = LOCKOUT_SECONDS * (2 ** min(4, fails - MAX_PIN_ATTEMPTS))
        try:
            store.set("lock", "lockout_until", str(_t.time() + backoff))
        except Exception:
            pass
        return backoff
    return 0


def pin_success(store) -> None:
    try:
        store.set("lock", "fails", "0")
        store.set("lock", "lockout_until", "0")
    except Exception:
        pass


def new_unlock_token() -> str:
    return secrets.token_hex(32)


def friendly_bio_error(exc: BaseException | None) -> str:
    """Map a flutter_secure_storage PlatformException to actionable text."""
    raw = str(exc or "").strip()
    low = raw.lower()
    if not raw:
        return "Biometrics unavailable on this device."
    if any(k in low for k in ("no biometric", "not enrolled", "no biometrics enrolled",
                              "biometric_not_enrolled", "not_enrolled")):
        return ("No fingerprint/face enrolled. Add one in Android Settings → "
                "Security → Fingerprint/Face, plus a PIN/pattern, then retry.")
    if any(k in low for k in ("no hardware", "not available", "not supported",
                              "biometric_not_available", "no_hardware")):
        return "This device has no biometric hardware or it is disabled."
    if any(k in low for k in ("lock screen", "device credential", "device not secured",
                              "no device credential", "screen lock")):
        return ("Set a device PIN/pattern/password first (Settings → Security → "
                "Screen lock), then enroll biometrics and retry.")
    if any(k in low for k in ("user cancel", "user_cancel", "cancelled", "canceled",
                              "dismissed", "negative button")):
        return "Biometric prompt was cancelled — try again."
    if any(k in low for k in ("lockout", "too many attempts", "temporarily locked")):
        return ("Too many attempts — biometrics locked temporarily. "
                "Unlock with device PIN, wait, then retry.")
    if any(k in low for k in ("key Permanently invalidated", "permanently invalidated",
                              "invalidated", "unwrap", "bad padding", "cipher")):
        return ("Biometric key was invalidated (new fingerprint added or "
                "backup restored). Turn biometric unlock OFF and back ON to "
                "re-enroll.")
    if any(k in low for k in ("api 28", "api level", "sdk 28", "requires api")):
        return "Biometric unlock needs Android 9 (API 28) or newer."
    # Fallback: keep the raw platform message (truncated) for debugging.
    return f"Biometrics failed: {raw[:220]}"


# Page-scoped SecureStorage singletons: every BioUnlock(page) reuses one
# service instead of appending duplicates to page.services on each toggle.
_ATTACHED: dict[int, object] = {}


class BioUnlock:
    """Biometric-gated unlock token via an enforcing SecureStorage profile."""

    def __init__(self, page=None) -> None:
        self._page = page
        self._storage = None
        self._aopts = None
        self.last_error: str = ""

    def _options(self):
        """The enforcing Android profile, reused for control AND per-call.

        Per-call args are the decisive path on the native side
        (args["android"] wins over control props), so every secure-storage
        call carries them explicitly — enforcement can never silently fall
        back to defaults on one path but not the other.
        """
        if self._aopts is None:
            import flet_secure_storage as fss

            self._aopts = fss.AndroidOptions(
                reset_on_error=False,
                migrate_on_algorithm_change=True,
                enforce_biometrics=True,
                key_cipher_algorithm=fss.KeyCipherAlgorithm.AES_GCM_NO_PADDING,
                storage_cipher_algorithm=fss.StorageCipherAlgorithm.AES_GCM_NO_PADDING,
                # ISOLATED native store. The plugin caches one native
                # instance per shared-preferences name and runs the
                # biometric init only on its first use: sharing the
                # default store with the KEK profile meant the KEK's
                # non-biometric init won the race at startup and our
                # enforce flag was silently ignored (no prompt, ever).
                shared_preferences_name="multiai_biometric",
                preferences_key_prefix="multiai_bio",
                biometric_prompt_title="Unlock INF ai",
                biometric_prompt_subtitle="Use fingerprint, face, or device PIN",
            )
        return self._aopts

    def _attach(self):
        if self._storage is not None:
            # Guard against id() reuse: verify the cached entry still
            # belongs to this page object.
            try:
                key = id(self._page) if self._page is not None else None
                if key is not None and _ATTACHED.get(key) is not self._storage:
                    self._storage = None
                else:
                    return self._storage
            except Exception:
                return self._storage
        key = id(self._page) if self._page is not None else None
        if key is not None and key in _ATTACHED:
            candidate = _ATTACHED[key]
            # id() can be recycled after GC — only reuse when the stored
            # entry was created for this exact page instance.
            owner = getattr(candidate, "_owner_id", None)
            if owner is None or owner == key:
                self._storage = candidate
                return self._storage
            else:
                try:
                    del _ATTACHED[key]
                except KeyError:
                    pass
        import flet_secure_storage as fss

        # Required-Biometrics combo per Flet docs: enforce_biometrics=True
        # ONLY works with key_cipher AES_GCM_NO_PADDING (API 28+). The old
        # code kept the default RSA cipher → every phone failed here.
        kwargs: dict = {"android_options": self._options()}
        # iOS: require biometry for this item so Face ID/Touch ID gates the
        # read. Without this the token reads silently (no prompt) on iPhones.
        try:
            kwargs["ios_options"] = fss.IOSOptions(
                access_control_flags=[fss.AccessControlFlag.BIOMETRY_ANY]
            )
        except Exception:
            pass
        self._storage = fss.SecureStorage(**kwargs)
        try:
            # Tag owner so id() reuse after GC can't hand us a stale entry.
            self._storage._owner_id = key  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            services = getattr(self._page, "services", None)
            if services is not None and self._storage not in services:
                services.append(self._storage)
                # A service appended after startup is not mounted until the
                # next update — without this the first get/set can fail and
                # biometric setup always reports failure on phones.
                try:
                    self._page.update()
                except Exception:
                    pass
        except Exception:
            pass
        if key is not None:
            # Bound the cache — page objects come and go; never grow forever.
            try:
                if len(_ATTACHED) > 8:
                    _ATTACHED.clear()
            except Exception:
                pass
            _ATTACHED[key] = self._storage
        return self._storage

    def _remember(self, exc: BaseException | None) -> str:
        self.last_error = friendly_bio_error(exc)
        return self.last_error

    async def probe_with_reason(self) -> tuple[bool, str]:
        """Try a biometric-gated read/write; return (ok, message).

        Non-destructive: reads the existing token when present, and only
        writes a fresh one when missing.
        """
        import asyncio as _asyncio

        BIO_TIMEOUT_S = 30.0
        try:
            storage = self._attach()
            ao = self._options()
            try:
                existing = await _asyncio.wait_for(
                    storage.get(UNLOCK_TOKEN_KEY, android=ao), timeout=BIO_TIMEOUT_S
                )
            except _asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — stale RSA-cipher entry?
                # Phones that enabled the toggle on the buggy build may hold
                # an unreadable token (wrong cipher). Drop it once and retry
                # with the fixed AES_GCM profile instead of failing forever.
                msg = str(e or "").lower()
                if any(k in msg for k in ("unwrap", "invalidated", "bad padding",
                                          "cipher", "decrypt", "keystore")):
                    try:
                        await _asyncio.wait_for(
                            storage.remove(UNLOCK_TOKEN_KEY, android=ao),
                            timeout=BIO_TIMEOUT_S,
                        )
                    except _asyncio.CancelledError:
                        raise
                    except Exception:
                        pass
                raise
            if existing:
                self.last_error = ""
                return True, ""
            token = new_unlock_token()
            await _asyncio.wait_for(
                storage.set(UNLOCK_TOKEN_KEY, token, android=ao), timeout=BIO_TIMEOUT_S
            )
            ok = (await _asyncio.wait_for(
                storage.get(UNLOCK_TOKEN_KEY, android=ao), timeout=BIO_TIMEOUT_S
            )) == token
            if ok:
                self.last_error = ""
                return True, ""
            return False, self._remember(None)
        except _asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — surface WHY it failed
            return False, self._remember(e)

    async def probe(self) -> bool:
        """True if a biometric-gated read works on this device."""
        ok, _ = await self.probe_with_reason()
        return ok

    async def ensure_token(self) -> bool:
        """Create the unlock token if missing (after PIN setup)."""
        ok, _ = await self.probe_with_reason()
        return ok

    async def unlock_with_reason(self) -> tuple[bool, str]:
        """Trigger the OS biometric prompt; return (ok, message)."""
        import asyncio as _asyncio

        try:
            storage = self._attach()
            ok = bool(await _asyncio.wait_for(
                storage.get(UNLOCK_TOKEN_KEY, android=self._options()), timeout=30.0
            ))
            if ok:
                self.last_error = ""
                return True, ""
            return False, self._remember(None)
        except _asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            return False, self._remember(e)

    async def unlock(self) -> bool:
        """Trigger the OS biometric prompt; True on success."""
        ok, _ = await self.unlock_with_reason()
        return ok

    async def clear(self) -> bool:
        import asyncio as _asyncio

        try:
            storage = self._attach()
            await _asyncio.wait_for(
                storage.remove(UNLOCK_TOKEN_KEY, android=self._options()), timeout=15.0
            )
            return True
        except _asyncio.CancelledError:
            raise
        except Exception:
            return False


def _coerce_flag(value: object) -> bool:
    return str(value or "").strip().lower() == "true"


def lock_prefs(store) -> dict:
    try:
        salt = store.get("lock", "salt", "")
        pin_hash = store.get("lock", "pin_hash", "")
    except Exception:
        salt, pin_hash = "", ""
    if not isinstance(salt, str):
        salt = ""
    if not isinstance(pin_hash, str):
        pin_hash = ""
    # Treat malformed hex as absent (verify_pin already returns False).
    try:
        bytes.fromhex(salt.strip())
    except Exception:
        salt = ""
    try:
        if pin_hash.strip():
            bytes.fromhex(pin_hash.strip())
        else:
            pin_hash = ""
    except Exception:
        pin_hash = ""
    try:
        enabled = _coerce_flag(store.get("lock", "enabled", "false"))
        biometric = _coerce_flag(store.get("lock", "biometric", "false"))
    except Exception:
        enabled, biometric = False, False
    return {
        "enabled": enabled and bool(salt) and bool(pin_hash),
        "salt": salt,
        "pin_hash": pin_hash,
        "biometric": biometric,
    }


def set_pin(store, pin: object) -> None:
    if not valid_pin(pin):
        raise ValueError("PIN must be 4–8 digits.")
    assert isinstance(pin, str)
    salt = new_salt()
    pin_hash = hash_pin(pin, salt)
    # Write salt+hash before flipping enabled so a crash mid-sequence
    # can never leave enabled=true with no credentials (lock_prefs
    # already requires all three).
    store.set("lock", "salt", salt)
    store.set("lock", "pin_hash", pin_hash)
    store.set("lock", "enabled", "true")


def clear_lock(store) -> None:
    for field in ("enabled", "salt", "pin_hash", "biometric", "fails", "lockout_until"):
        try:
            store.set("lock", field, "")
        except Exception:
            pass


def wipe_keys(store, provider_ids) -> int:
    wiped = 0
    for pid in provider_ids or []:
        try:
            store.set_key(pid, "")
            wiped += 1
        except Exception:
            continue
    return wiped
