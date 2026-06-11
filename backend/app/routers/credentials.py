from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.services.credential_store import credential_store

router = APIRouter(prefix="/settings", tags=["credentials"])


class CredentialUpdate(BaseModel):
    key: Literal["ibkr_live", "ibkr_paper", "tradier_live", "tradier_paper", "alpaca_paper", "alpaca_live"]
    values: dict


@router.post("/credentials")
async def set_credentials(body: CredentialUpdate) -> dict:
    """Store broker credentials in memory and persist to local (gitignored) file."""
    credential_store.set(body.key, body.values)
    credential_store.save()
    return {"ok": True, "key": body.key}


@router.get("/credentials")
async def get_credentials() -> dict:
    """Return all credential slots with sensitive values masked."""
    return credential_store.all_masked()
