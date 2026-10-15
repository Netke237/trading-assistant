"""Strict detached evidence; no lookups by latest run or mutable settings."""
from dataclasses import asdict
import json
import time
from uuid import uuid4
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from app.models.backtest_artifact import BacktestArtifact

RETENTION_SECONDS = 30 * 86400


class ArtifactStorageError(Exception):
    pass


class ArtifactExpired(Exception):
    pass


async def save_artifact(db, *, detail, identity):
    if detail.status != 'success':
        raise ValueError('Only successful engine evidence can be saved')
    now = time.time()
    artifact = dict(schema_version=1, artifact_id=str(uuid4()), provenance='original',
                    identity=identity, created_at=now, expires_at=now + RETENTION_SECONDS,
                    currency=None, detail=asdict(detail))
    # allow_nan=False recursively rejects invalid numbers, including nested config.
    payload = json.dumps(artifact, allow_nan=False, sort_keys=True, separators=(',', ':'))
    frozen = json.loads(payload)
    row = BacktestArtifact(id=frozen['artifact_id'], schema_version=1,
                          symbol=frozen['identity']['symbol'], created_at=now,
                          expires_at=frozen['expires_at'], payload_json=payload)
    try:
        db.add(row)
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        raise ArtifactStorageError('Backtest artifact storage unavailable') from None
    return frozen


async def get_artifact(db, artifact_id, symbol):
    try:
        row = (await db.execute(select(BacktestArtifact).where(
            BacktestArtifact.id == str(artifact_id), BacktestArtifact.symbol == symbol))).scalar_one_or_none()
        if row is None:
            return None
        if row.expires_at <= time.time() or row.payload_json is None:
            raise ArtifactExpired()
        return json.loads(row.payload_json)
    except SQLAlchemyError:
        raise ArtifactStorageError('Backtest artifact storage unavailable') from None


async def cleanup_expired(db):
    try:
        result = await db.execute(update(BacktestArtifact).where(
            BacktestArtifact.expires_at <= time.time(), BacktestArtifact.payload_json.is_not(None)
        ).values(payload_json=None))
        await db.commit()
        return result.rowcount
    except SQLAlchemyError:
        await db.rollback()
        raise ArtifactStorageError('Backtest artifact storage unavailable') from None
