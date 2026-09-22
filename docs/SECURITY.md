# Security

BYOK on-device. No backend to leak from — but the device itself is the trust boundary.

## Key storage (v0.4.0)

- API keys live in `data/preferences.json`, each `*.key` value Fernet-encrypted
  (`cryptography`, hard dep since v0.3.0). All keys prefixed `multiai.`.
- The Fernet key is a random 32-byte **KEK stored in platform secure storage**
  (`flet-secure-storage`: Android Keystore / iOS Keychain / Windows Credential
  Manager), loaded once at startup and cached in memory for the session.
  This replaced the v0.2/v0.3 device seed (sha256 of install path), which was
  recoverable from code + file. Migration is automatic (plaintext → seed →
  KEK) and idempotent.
- If secure storage is unavailable, the app falls back to the device seed and
  Settings → Security shows a warning badge.
- Rules: never log keys, never include in exports, mask in UI (`••••1234`),
  keep out of crash reports/screenshots.

## Threat model (what this does and doesn't protect)

- Protects against: casual backup/file reads, another app reading our sandbox
  files, shoulder-surfing (masked UI + optional app lock).
- Does NOT protect against: rooted device with memory inspection while the app
  is unlocked, OS-level keystore compromise, phishing of the keys themselves
  (paste only on official provider pages linked from the Providers screen).

## App lock (optional, Settings → Security)

- 4–8 digit PIN, PBKDF2-HMAC-SHA256 (200k rounds, salted; only hash stored).
- Optional biometric unlock via a Keystore-enforced SecureStorage profile
  (needs `USE_BIOMETRIC`; degrades gracefully without enrolled biometrics).
- Lock shows at startup + via "Lock now". Forgot PIN resets the lock AND all
  saved API keys — chats are kept, nobody is ever permanently locked out.

## Attachments & privacy

- Files are sent to the selected provider only. Show provider name + model in send bar before send.
- Long docs (>12k chars) are chunked on-device; only top-3 retrieved excerpts
  are sent (with `[file §n]` citations) instead of the whole file.
- “No retention” is provider-dependent — link each provider’s policy from Providers screen.
- Local copies under `app_data/attachments/` capped at 5MB; docs larger than that are text-extracted, not stored.

## Transport

- HTTPS only by default. `normalize_base_url` rejects `http://` (loopback dev
  requires explicit opt-in), blocks private/link-local/metadata hosts and
  credentials in URLs. `httpx` clients use `trust_env=False`,
  `follow_redirects=False` with strict timeouts. No certificate bypass.
