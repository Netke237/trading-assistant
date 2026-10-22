from __future__ import annotations

from app.schemas.payload_depth import validate_payload_depth

from typing import Literal

from fastapi import APIRouter
from pydantic import field_validator, BaseModel

from app.services.credential_store import credential_store

router = APIRouter(prefix="/settings", tags=["credentials"])


class CredentialUpdate(BaseModel):
    key: Literal[
        "ibkr_live", "ibkr_paper",
        "tradier_live", "tradier_paper",
        "alpaca_paper", "alpaca_live",
        "tastytrade_paper", "tastytrade_live",
    ]
    values: dict

    _validate_payload_depth = field_validator('values', mode="before")(validate_payload_depth)


@router.post("/credentials")
async def set_credentials(body: CredentialUpdate) -> dict:
    """Store broker credentials in memory and persist to local (gitignored) file."""
    credential_store.set_and_save(body.key, body.values)
    if body.key in ("tastytrade_paper", "tastytrade_live"):
        # Deferred import: tastytrade_session imports the `tastytrade` package at
        # module scope, so importing it at router module-load time would make
        # app startup fail hard if the SDK isn't installed. Keeping it local
        # confines that dependency to only when a tastytrade credential is set.
        from app.data.tastytrade_session import clear_cache
        clear_cache()
    return {"ok": True, "key": body.key}


@router.get("/credentials")
async def get_credentials() -> dict:
    """Return all credential slots with sensitive values masked."""
    return credential_store.all_masked()
