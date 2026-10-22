"""Single-deployment durable scan evidence.

Mutations own a transaction and require a clean AsyncSession. Dispatch integration
must supply resolved inputs at begin and matching diagnostics/results at finish.
The JSON envelope is serialized before writing, so caller edits cannot relabel it.
Errors are safe codes only: callers must not pass raw provider exceptions.
"""
from datetime import datetime, timezone
import json
from uuid import uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.scan_report import ScanReport, ScanReportHead
from app.models.scan_session import ScanSession

CATEGORIES = ('options', 'stocks', 'prebreakout', 'pullback', 'fib')
TRIGGERS = ('manual', 'scheduled', 'automatic')
TERMINAL_STATES = ('complete', 'failed', 'cancelled', 'no_data', 'interrupted')
ERROR_CODES = ('scan_failed', 'cancelled', 'interrupted', 'no_data', 'report_unavailable')
# Reject payload containers used for raw exceptions/credentials. Domain reasons
# and observed values retain their source schema; adapters must provide safe reasons.
FORBIDDEN_KEYS = {'token', 'access_token', 'refresh_token', 'api_token', 'api_key',
                  'password', 'secret', 'credentials', 'authorization', 'exception',
                  'traceback', 'error', 'errors', 'error_message', 'error_detail'}


class ScanReportStorageError(RuntimeError):
    """Visible save/read failure without secret-bearing database exception text."""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _encode(payload):
    def validate(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if not isinstance(key, str) or key.lower() in FORBIDDEN_KEYS or any(
                    part in key.lower() for part in ('password', 'token', 'secret', 'credential', 'api_key', 'authorization')):
                    raise ValueError('Unsafe report payload key; use safe error codes')
                validate(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                validate(child)
    validate(payload)
    return json.dumps(payload, allow_nan=False, separators=(',', ':'))


async def _prune(db, category):
    head = await db.get(ScanReportHead, category, populate_existing=True)
    retained = [v for v in (head.latest_id, head.usable_id) if v]
    # Never delete another category or any inflight attempt.
    await db.execute(delete(ScanReport).where(
        ScanReport.category == category, ScanReport.status != 'running',
        ScanReport.id.not_in(retained)))


async def begin_run(db: AsyncSession, *, category: str, trigger: str, inputs: dict) -> dict:
    if category not in CATEGORIES or trigger not in TRIGGERS:
        raise ValueError('Unknown scan category or trigger')
    frozen = json.loads(_encode(inputs))
    run_id = str(uuid4())
    try:
        async with db.begin():
            dialect = db.get_bind().dialect.name
            if dialect == 'sqlite':
                from sqlalchemy.dialects.sqlite import insert
            elif dialect == 'postgresql':
                from sqlalchemy.dialects.postgresql import insert
            else:
                raise ValueError('Unsupported scan report database')
            await db.execute(insert(ScanReportHead).values(category=category, generation=0)
                             .on_conflict_do_nothing(index_elements=['category']))
            generation = (await db.execute(update(ScanReportHead).where(
                ScanReportHead.category == category).values(
                generation=ScanReportHead.generation + 1, latest_id=run_id)
                .returning(ScanReportHead.generation))).scalar_one()
            envelope = dict(schema_version=1, run_id=run_id, category=category,
                            generation=generation, trigger=trigger, started_at=_now(),
                            ended_at=None, status='running', dispatch_inputs=frozen, inputs=frozen,
                            diagnostics_available=False, diagnostics=None,
                            result=None, error_code=None, persistence='saved')
            db.add(ScanReport(id=run_id, category=category, generation=generation,
                              status='running', envelope_json=_encode(envelope)))
            await db.flush()
            await _prune(db, category)
        return envelope
    except SQLAlchemyError:
        raise ScanReportStorageError('Scan report storage unavailable') from None


async def finish_run(db: AsyncSession, run_id: str, *, status: str,
                     diagnostics: dict | None = None, result: dict | None = None,
                     error_code: str | None = None, inputs: dict | None = None,
                     promote_usable: bool = True) -> dict:
    if status not in TERMINAL_STATES or (error_code is not None and error_code not in ERROR_CODES):
        raise ValueError('Invalid terminal status or unsafe error code')
    # Validate before opening the transaction so invalid data never partially writes.
    _encode({'diagnostics': diagnostics, 'result': result, 'inputs': inputs})
    try:
        async with db.begin():
            row = await db.get(ScanReport, run_id)
            if row is None:
                raise ValueError('Unknown run ID')
            # Lock category ownership before terminal write/pruning, in the same
            # order as begin_run. Works for PostgreSQL and SQLite writers.
            await db.execute(update(ScanReportHead).where(
                ScanReportHead.category == row.category).values(
                generation=ScanReportHead.generation))
            envelope = json.loads(row.envelope_json)
            if row.status != 'running':
                raise ValueError('Run is already terminal')
            if inputs is not None:
                envelope['inputs'] = inputs
            envelope.update(status=status, ended_at=_now(), diagnostics=diagnostics,
                            diagnostics_available=diagnostics is not None, result=result,
                            error_code=error_code)
            encoded = _encode(envelope)
            changed = (await db.execute(update(ScanReport).where(
                ScanReport.id == run_id, ScanReport.status == 'running').values(
                status=status, envelope_json=encoded).returning(ScanReport.id))).scalar_one_or_none()
            if changed is None:
                raise ValueError('Run is already terminal')
            # Only the newest started attempt can replace usable evidence. A
            # failed run with usable diagnostics is inspectable in its own right.
            # promote_usable=False keeps partial diagnostics on this run's own
            # envelope without replacing (and so pruning) the usable report.
            if diagnostics is not None and promote_usable:
                await db.execute(update(ScanReportHead).where(
                    ScanReportHead.category == row.category,
                    ScanReportHead.latest_id == run_id,
                    ScanReportHead.generation == row.generation).values(usable_id=run_id))
            await _prune(db, row.category)
        return json.loads(encoded)
    except SQLAlchemyError:
        raise ScanReportStorageError('Scan report storage unavailable') from None


async def get_run(db: AsyncSession, run_id: str) -> dict | None:
    try:
        row = await db.get(ScanReport, run_id, populate_existing=True)
        return json.loads(row.envelope_json) if row else None
    except SQLAlchemyError:
        raise ScanReportStorageError('Scan report storage unavailable') from None


async def get_latest(db: AsyncSession, category: str) -> dict:
    if category not in CATEGORIES:
        raise ValueError('Unknown scan category')
    try:
        # One statement snapshots head and both envelopes coherently even while
        # another connection replaces pointers/prunes records.
        from sqlalchemy.orm import aliased
        latest, usable = aliased(ScanReport), aliased(ScanReport)
        row = (await db.execute(select(ScanReportHead.latest_id, ScanReportHead.usable_id,
            latest.envelope_json, usable.envelope_json).outerjoin(
            latest, latest.id == ScanReportHead.latest_id).outerjoin(
            usable, usable.id == ScanReportHead.usable_id).where(
            ScanReportHead.category == category))).one_or_none()
        return dict(category=category,
                    latest_attempt=json.loads(row[2]) if row and row[2] else None,
                    previous_report=json.loads(row[3]) if row and row[3] and row[0] != row[1] else None)
    except SQLAlchemyError:
        raise ScanReportStorageError('Scan report storage unavailable') from None


async def get_legacy(db: AsyncSession) -> list[dict]:
    """Inspect legacy evidence without guessing whether stock-current was Pullback.

    Source storage stays byte-for-byte intact. Safe parsed payloads are returned;
    malformed or unsafe legacy data is explicitly unavailable, never fabricated.
    """
    try:
        rows = (await db.execute(select(ScanSession).order_by(ScanSession.id))).scalars().all()
        output = []
        for row in rows:
            entry = dict(run_id=f'legacy:{row.id}', legacy_id=row.id,
                         category='legacy/unclassified', status=row.status,
                         started_at=row.created_at.isoformat() if row.created_at else None,
                         ended_at=row.updated_at.isoformat() if row.updated_at else None,
                         diagnostics_available=False, inputs=None, result=None,
                         unavailable_fields=[], unavailable_field_paths={})
            for field, raw in [('inputs', row.last_request_json), ('result', row.last_result_json)]:
                try:
                    value = json.loads(raw) if raw else None
                    _encode(value)
                    from app.services.scan_report_lifecycle import project
                    unavailable = []
                    safe = project(value, path=field, unavailable=unavailable)
                    if unavailable:
                        entry['unavailable_fields'].append(field)
                        entry['unavailable_field_paths'][field] = unavailable
                    entry[field] = safe if isinstance(safe, (dict, list, str, int, float, bool)) or safe is None else None
                except (ValueError, TypeError):
                    entry['unavailable_fields'].append(field)
            output.append(entry)
        return output
    except SQLAlchemyError:
        raise ScanReportStorageError('Scan report storage unavailable') from None


async def recover_interrupted(db: AsyncSession) -> int:
    """Call only once at process startup, before any dispatch is admitted.

    Caller owns lifecycle integration (LOG-02). Never use as periodic cleanup.
    """
    try:
        async with db.begin():
            # Serialize with category writers before reading envelopes.
            for category in CATEGORIES:
                await db.execute(update(ScanReportHead).where(
                    ScanReportHead.category == category).values(generation=ScanReportHead.generation))
            rows = (await db.execute(select(ScanReport).where(ScanReport.status == 'running'))).scalars().all()
            for row in rows:
                envelope = json.loads(row.envelope_json)
                envelope.update(status='interrupted', ended_at=_now(), error_code='interrupted')
                row.status = 'interrupted'
                row.envelope_json = _encode(envelope)
            await db.flush()
            for category in CATEGORIES:
                if await db.get(ScanReportHead, category) is not None:
                    await _prune(db, category)
        return len(rows)
    except SQLAlchemyError:
        raise ScanReportStorageError('Scan report storage unavailable') from None
