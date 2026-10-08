"""Encrypt secrets stored in the database (Plaid access tokens) with a key kept outside it.

The key comes from PFT_SECRET_KEY if set, else the system keychain (macOS Keychain, Windows
Credential Manager, Secret Service on Linux), else a file in ~/.config/personal-finance-tool
readable only by you. Keychain and file keys are both tried when decrypting, so a keychain that is
briefly unavailable does not strand tokens encrypted earlier.
"""

import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

PREFIX = "enc:v1:"
KEYRING_SERVICE = "personal-finance-tool"
KEYRING_USER = "database-secrets-key"
KEY_FILE = Path(os.getenv("PFT_KEY_FILE", Path.home() / ".config" / "personal-finance-tool" / "secret.key"))

log = logging.getLogger(__name__)
_cipher: tuple[MultiFernet, str] | None = None


def _keyring_get() -> str | None:
    try:
        import keyring

        return keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    except Exception:  # no backend, locked keychain, headless session
        return None


def _keyring_set(key: str) -> bool:
    try:
        import keyring

        keyring.set_password(KEYRING_SERVICE, KEYRING_USER, key)
        return keyring.get_password(KEYRING_SERVICE, KEYRING_USER) == key
    except Exception:
        return False


def _file_get() -> str | None:
    try:
        return KEY_FILE.read_text().strip() or None
    except OSError:
        return None


def _file_set(key: str) -> None:
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(key)


def _load() -> tuple[MultiFernet, str]:
    env = os.getenv("PFT_SECRET_KEY")
    if env:
        return MultiFernet([Fernet(env.encode())]), "PFT_SECRET_KEY environment variable"
    found = [
        (k, source)
        for k, source in ((_keyring_get(), "system keychain"), (_file_get(), f"key file {KEY_FILE}"))
        if k
    ]
    if not found:
        key = Fernet.generate_key().decode()
        if _keyring_set(key):
            found = [(key, "system keychain")]
        else:
            _file_set(key)
            found = [(key, f"key file {KEY_FILE}")]
    return MultiFernet([Fernet(k.encode()) for k, _ in found]), found[0][1]


def cipher() -> tuple[MultiFernet, str]:
    global _cipher
    if _cipher is None:
        _cipher = _load()
    return _cipher


def key_location() -> str:
    return cipher()[1]


def encrypt(value: str) -> str:
    if value.startswith(PREFIX):
        return value
    return PREFIX + cipher()[0].encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    """Plaintext for a stored value; legacy unencrypted values pass through, unreadable ones are ''."""
    if not value.startswith(PREFIX):
        return value
    try:
        return cipher()[0].decrypt(value.removeprefix(PREFIX).encode()).decode()
    except InvalidToken:
        log.warning("Could not decrypt a stored secret: the encryption key is missing or changed.")
        return ""


class EncryptedString(TypeDecorator):
    """A string column encrypted at rest."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else encrypt(value)

    def process_result_value(self, value, dialect):
        return None if value is None else decrypt(value)
