"""
API key generation. The plaintext is shown to the user exactly once; only the
SHA-256 hash and a short display prefix are ever persisted.

Later (Slice 3) validation = sha256(presented_key) -> look up by key_hash ->
check status == 'active'. Nothing here changes for that; the hash is the join key.
"""

import hashlib
import secrets

KEY_PREFIX = "stt_"


def hash_key(plaintext: str) -> str:
    """SHA-256 hex of a key. Used at issuance (store) and validation (look up)."""
    return hashlib.sha256(plaintext.encode("ascii")).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """Return (plaintext, key_hash, display_prefix)."""
    plaintext = f"{KEY_PREFIX}{secrets.token_urlsafe(32)}"
    return plaintext, hash_key(plaintext), plaintext[:12]
