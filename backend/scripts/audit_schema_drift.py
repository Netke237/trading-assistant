"""Full model-vs-database schema drift audit across ALL declarative bases.

Reports, per table, columns the model declares that the DB lacks (DANGEROUS —
these cause 500s), columns the DB has that the model lacks (orphan — harmless
but messy), and tables the model declares that the DB lacks entirely.

Run against the current DATABASE_URL, or pass one:
    cd backend && venv/Scripts/python.exe scripts/audit_schema_drift.py
    cd backend && DATABASE_URL='sqlite+aiosqlite:///./dev.db' venv/.../python.exe scripts/audit_schema_drift.py
"""
import asyncio
import importlib
import pkgutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

import app.models
from app.config import get_settings


def _import_all_models() -> None:
    for mod in pkgutil.iter_modules(app.models.__path__):
        if mod.name != "__init__":
            importlib.import_module(f"app.models.{mod.name}")


def _model_tables() -> dict[str, set[str]]:
    """{table_name: {column names}} unioned across every declarative Base's metadata."""
    from sqlalchemy.orm import DeclarativeBase
    import app.database

    metadatas = {app.database.Base.metadata}
    # Every DeclarativeBase subclass that owns tables registers its own MetaData.
    for cls in DeclarativeBase.__subclasses__():
        md = getattr(cls, "metadata", None)
        if md is not None:
            metadatas.add(md)

    out: dict[str, set[str]] = {}
    for md in metadatas:
        for table in md.sorted_tables:
            out.setdefault(table.name, set()).update(c.name for c in table.columns)
    return out


async def main() -> None:
    _import_all_models()
    model_tables = _model_tables()

    url = get_settings().DATABASE_URL
    print(f"=== Schema drift audit against: {url} ===\n")
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        db_tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
        db_cols: dict[str, set[str]] = {}
        for t in db_tables:
            db_cols[t] = await conn.run_sync(
                lambda c, t=t: {col["name"] for col in inspect(c).get_columns(t)}
            )
    await engine.dispose()

    any_danger = False
    for table, mcols in sorted(model_tables.items()):
        if table not in db_cols:
            print(f"[MISSING TABLE]  {table}  (model declares it; DB has no such table)")
            any_danger = True
            continue
        missing = mcols - db_cols[table]
        orphan = db_cols[table] - mcols
        if missing:
            any_danger = True
            print(f"[MISSING COLUMN] {table}: {sorted(missing)}  <-- model has, DB lacks (causes 500s)")
        if orphan:
            print(f"[ORPHAN COLUMN]  {table}: {sorted(orphan)}  <-- DB has, model lacks (harmless)")

    db_only = sorted(set(db_cols) - set(model_tables) - {"alembic_version"})
    if db_only:
        print(f"\n[DB-ONLY TABLES] {db_only}  (in DB, no model — informational)")

    if not any_danger:
        print("\nNo dangerous (missing-column / missing-table) drift found.")


if __name__ == "__main__":
    asyncio.run(main())
