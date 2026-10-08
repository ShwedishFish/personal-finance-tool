from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_session
from ..models import PlaidItem
from ..plaid_sync import sync_item

router = APIRouter(prefix="/api/plaid", tags=["plaid"])


class ExchangeIn(BaseModel):
    public_token: str
    institution_name: str | None = None


def get_gateway():
    if not settings.plaid_enabled:
        raise HTTPException(503, "Plaid is not configured. Set PLAID_CLIENT_ID and PLAID_SECRET in .env.")
    from ..plaid_client import PlaidGateway

    return PlaidGateway(settings)


def _plaid_call(fn, *args):
    from ..plaid_client import PlaidError

    try:
        return fn(*args)
    except PlaidError as err:
        raise HTTPException(502, f"Plaid error {err.code}: {err.message}") from err


@router.get("/status")
def status():
    return {"enabled": settings.plaid_enabled, "environment": settings.plaid_env}


@router.get("/items")
def list_items(session: Session = Depends(get_session)):
    items = session.scalars(select(PlaidItem).order_by(PlaidItem.created_at))
    return [
        {
            "id": i.id,
            "institution_name": i.institution_name,
            "created_at": i.created_at,
            "last_synced_at": i.last_synced_at,
            "accounts": len(i.accounts),
        }
        for i in items
    ]


@router.post("/link-token")
def link_token(gateway=Depends(get_gateway)):
    return {"link_token": _plaid_call(gateway.create_link_token)}


@router.post("/exchange")
def exchange(body: ExchangeIn, gateway=Depends(get_gateway), session: Session = Depends(get_session)):
    access_token, item_id = _plaid_call(gateway.exchange_public_token, body.public_token)
    item = session.scalar(select(PlaidItem).where(PlaidItem.item_id == item_id))
    if item is None:
        item = PlaidItem(item_id=item_id, access_token=access_token, institution_name=body.institution_name)
        session.add(item)
    else:
        item.access_token = access_token
    session.commit()
    result = _plaid_call(sync_item, session, item, gateway)
    return {"item_id": item.id, **result}


@router.post("/sync")
def sync_all(gateway=Depends(get_gateway), session: Session = Depends(get_session)):
    results = []
    for item in session.scalars(select(PlaidItem)).all():
        if not item.access_token:
            raise HTTPException(
                409,
                f"The saved bank login for {item.institution_name or 'an institution'} can't be decrypted (its "
                "encryption key is missing). Remove that institution and connect it again.",
            )
        results.append({"item_id": item.id, **_plaid_call(sync_item, session, item, gateway)})
    return results


@router.delete("/items/{item_id}", status_code=204)
def remove_item(item_id: int, gateway=Depends(get_gateway), session: Session = Depends(get_session)):
    item = session.get(PlaidItem, item_id)
    if item is None:
        raise HTTPException(404, "Linked institution not found")
    if item.access_token:
        _plaid_call(gateway.remove_item, item.access_token)
    for acct in item.accounts:
        acct.plaid_account_id = None
    session.delete(item)
    session.commit()
