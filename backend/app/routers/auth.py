import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import (
    COOKIE,
    get_setting,
    hash_password,
    make_cookie,
    require_auth,
    set_setting,
    signed_in,
    verify_password,
)
from ..crypto import key_location
from ..db import get_session
from ..models import PlaidItem

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    password: str
    remember: bool = True


class PasswordIn(BaseModel):
    current_password: str | None = None
    new_password: str | None = Field(None, min_length=8, max_length=256)  # None removes the password


def _set_cookie(response: Response, session: Session, password_hash: str, remember: bool) -> None:
    value, max_age = make_cookie(session, password_hash, remember)
    response.set_cookie(COOKIE, value, max_age=max_age if remember else None, httponly=True, samesite="strict")


@router.get("/status")
def status(request: Request, session: Session = Depends(get_session)):
    ok = signed_in(session, request)
    out = {"password_enabled": get_setting(session, "password_hash") is not None, "signed_in": ok}
    if ok:
        links = session.scalar(select(func.count()).select_from(PlaidItem))
        out["bank_links"] = links
        out["key_location"] = key_location() if links else None
    return out


@router.post("/login")
def login(body: LoginIn, response: Response, session: Session = Depends(get_session)):
    password_hash = get_setting(session, "password_hash")
    if password_hash is None:
        return {"signed_in": True}
    if not verify_password(body.password, password_hash):
        time.sleep(1)  # slow down guessing
        raise HTTPException(401, "Wrong password")
    _set_cookie(response, session, password_hash, body.remember)
    return {"signed_in": True}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE, httponly=True, samesite="strict")
    return {"signed_in": False}


@router.put("/password", dependencies=[Depends(require_auth)])
def change_password(body: PasswordIn, response: Response, session: Session = Depends(get_session)):
    current = get_setting(session, "password_hash")
    if current is not None and not verify_password(body.current_password or "", current):
        time.sleep(1)
        raise HTTPException(403, "Current password is wrong")
    if body.new_password is None:
        set_setting(session, "password_hash", None)
        session.commit()
        response.delete_cookie(COOKIE, httponly=True, samesite="strict")
        return {"password_enabled": False}
    new_hash = hash_password(body.new_password)
    set_setting(session, "password_hash", new_hash)
    session.commit()
    _set_cookie(response, session, new_hash, remember=True)
    return {"password_enabled": True}
