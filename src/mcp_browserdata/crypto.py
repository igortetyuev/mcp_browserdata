"""Chromium v10 cookie/login decryption on macOS.

`encrypted_value` = b"v10" + AES-128-CBC(plaintext), key = PBKDF2-HMAC-SHA1(
"<Browser> Safe Storage" from login keychain, salt=b"saltysalt", iter=1003, 16B),
IV = 16 spaces. Cookie plaintexts since Chrome 80 carry a 32-byte
SHA-256(host_key) prefix; login passwords do not.
"""

from __future__ import annotations

import hashlib
import subprocess
from functools import lru_cache

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from mcp_browserdata.errors import BrowserDataError

_SALT = b"saltysalt"
_ITERATIONS = 1003
_IV = b" " * 16
_V10_PREFIX = b"v10"


@lru_cache(maxsize=16)
def safe_storage_password(service: str) -> str:
    """Fetch '<Browser> Safe Storage' from the login keychain (may prompt once)."""
    proc = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-w"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise BrowserDataError(
            f"keychain item '{service}' not readable: {proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc.stdout.rstrip("\n")


@lru_cache(maxsize=16)
def _derived_key(service: str) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha1", safe_storage_password(service).encode(), _SALT, _ITERATIONS, 16
    )


def _cipher(service: str) -> Cipher:
    return Cipher(algorithms.AES(_derived_key(service)), modes.CBC(_IV))


def decrypt_v10(blob: bytes, service: str) -> bytes:
    """Decrypt a v10 blob, return unpadded plaintext. Returns b"" for empty input."""
    if not blob:
        return b""
    if blob[:3] != _V10_PREFIX:
        # Older rows may hold a plaintext value (pre-v10 or DPAPI-only field).
        return blob
    dec = _cipher(service).decryptor()
    padded = dec.update(blob[3:]) + dec.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    try:
        return unpadder.update(padded) + unpadder.finalize()
    except ValueError:
        # Chrome tolerates padding sloppiness; do the same rather than fail hard.
        return padded


def encrypt_v10(plaintext: bytes, service: str) -> bytes:
    padder = padding.PKCS7(128).padder()
    enc = _cipher(service).encryptor()
    return _V10_PREFIX + enc.update(padder.update(plaintext) + padder.finalize()) + enc.finalize()


def decrypt_cookie_value(
    encrypted: bytes, plaintext_column: str | bytes, host: str, service: str
) -> str:
    """Decode a cookie row's value.

    `plaintext_column` is the `value` column (usually empty when encrypted_value
    is set). Strips the SHA-256(host) prefix Chrome 80+ adds inside the
    encrypted plaintext.
    """
    if plaintext_column:
        if isinstance(plaintext_column, bytes):
            return plaintext_column.decode()
        return plaintext_column
    raw = decrypt_v10(encrypted, service)
    digest = hashlib.sha256(host.encode()).digest()
    if len(raw) > 32 and raw[:32] == digest:
        raw = raw[32:]
    return raw.decode("utf-8", errors="replace")


def encrypt_cookie_value(value: str, host: str, service: str) -> bytes:
    """Encrypt in the Chrome 80+ format: AES(SHA256(host) || value)."""
    return encrypt_v10(hashlib.sha256(host.encode()).digest() + value.encode(), service)
