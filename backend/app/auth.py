"""Optional app password, so someone at your unlocked computer can't open your finances.

The password gates the API only: the database is not encrypted with it, so forgetting it loses
nothing. Remove it with scripts/reset-password.sh.
"""

import hashlib
import hmac
import secrets
import sys
import time

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .db import get_session
from .models import AppSetting

COOKIE = "pft_session"
SIGN_IN_REQUIRED = "Sign in required"
REMEMBER_SECONDS = 30 * 24 * 3600
SESSION_SECONDS = 12 * 3600
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


def get_setting(session: Session, key: str) -> str | None:
    row = session.get(AppSetting, key)
    return row.value if row else None


def set_setting(session: Session, key: str, value: str | None) -> None:
    row = session.get(AppSetting, key)
    if value is None:
        if row:
            session.delete(row)
    elif row:
        row.value = value
    else:
        session.add(AppSetting(key=key, value=value))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
        candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), **_SCRYPT)
    except ValueError:
        return False
    return hmac.compare_digest(candidate.hex(), digest)


def _session_secret(session: Session) -> bytes:
    secret = get_setting(session, "session_secret")
    if secret is None:
        secret = secrets.token_hex(32)
        set_setting(session, "session_secret", secret)
        session.commit()
    return bytes.fromhex(secret)


def _signature(session: Session, expires: int, password_hash: str) -> str:
    # Signing over the password hash signs everyone out when the password changes.
    return hmac.new(_session_secret(session), f"{expires}.{password_hash}".encode(), hashlib.sha256).hexdigest()


def make_cookie(session: Session, password_hash: str, remember: bool) -> tuple[str, int]:
    max_age = REMEMBER_SECONDS if remember else SESSION_SECONDS
    expires = int(time.time()) + max_age
    return f"{expires}.{_signature(session, expires, password_hash)}", max_age


def signed_in(session: Session, request: Request) -> bool:
    password_hash = get_setting(session, "password_hash")
    if password_hash is None:
        return True
    try:
        expires_text, signature = (request.cookies.get(COOKIE) or "").split(".")
        expires = int(expires_text)
    except ValueError:
        return False
    if expires < time.time():
        return False
    return hmac.compare_digest(signature, _signature(session, expires, password_hash))


def require_auth(request: Request, session: Session = Depends(get_session)) -> None:
    if not signed_in(session, request):
        raise HTTPException(401, SIGN_IN_REQUIRED)


def _reset() -> None:
    from .db import SessionLocal, init_db

    init_db()
    with SessionLocal() as session:
        had = get_setting(session, "password_hash") is not None
        set_setting(session, "password_hash", None)
        session.commit()
    print("Password removed. The app opens without one now." if had else "No password was set.")


if __name__ == "__main__":
    if sys.argv[1:] != ["reset"]:
        sys.exit("usage: python -m app.auth reset")
    _reset()
