"""Disposable verification of the MEAS live-DB isolation (plan §3, ticket T4 #284).

Plan: docs/superpowers/plans/2026-10-13-meas-live-db-isolation-plan.md.

Runs the orchestrator's own functions (``scripts/meas/isolated_day.py``)
against a THROWAWAY Postgres container and the frozen tag's own prune code:

1. ``docker run --rm --pull never postgres:15-alpine`` under a random name
   ``meas-verify-<hex>``, host port chosen by Docker on 127.0.0.1, a random
   superuser password generated here and given to docker through its env.
   The DB ``fake_live`` gets ``ohlcv_daily`` (DDL compiled from the tag's
   model), an ``alembic_version`` row and 3 symbols of weekday rows from
   2009-10-01 to today.
2. ``isolated_day.setup`` against ``fake_live`` (a throwaway DB: approval is
   implicit, the function is called, never the CLI flag), then
   ``copy_live_to_meas`` and ``verify_copy``.
3. The tag's ``app.services.ingestion_job._prune_old_rows(6)`` runs in a
   subprocess from a temporary ``git worktree`` of ``meas-freeze-1`` outside
   the repo, with ``isolated_day.build_child_env`` and the meas ``.env``
   written by ``isolated_day.write_meas_dotenv``: the exact code that deleted
   live history, now pointed at the copy.
4. Assertions: the copy lost every row older than 6*365 days; ``fake_live`` is
   unchanged; G2 holds; the tag code connecting to ``fake_live`` as
   ``meas_runner`` is refused; G3's ``meas_connections_ok`` passes while the tag
   code holds a session on the copy (and fails with none); G1 refuses each
   violation.
5. A report with counts and pass/fail lines only:
   ``docs/superpowers/measurements/isolation-verification-<date>.md``.

It never touches ``tradingassistant-db``, the live database or the live
backend: the container name is generated here and refused if it is the live
one. The container is stopped (``--rm`` removes it) and the temporary worktree
removed in ``finally`` blocks.

Usage (Windows, repo venv, Docker running):
    backend\\.venv\\Scripts\\python.exe scripts\\meas\\verify_isolation_disposable.py
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import quote

_HERE = Path(__file__).resolve().parent
REPO_ROOT = _HERE.parents[1]


def _load_isolated_day():
    name = "meas_isolated_day"   # same module name as the T1-T3 tests
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _HERE / "isolated_day.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


iso = _load_isolated_day()

IMAGE = "postgres:15-alpine"
CONTAINER_PREFIX = "meas-verify-"
_CONTAINER_NAME_RE = re.compile(r"^meas-verify-[0-9a-f]{8,32}$")
FAKE_LIVE_DB = "fake_live"
SUPERUSER = "postgres"
SYMBOLS: tuple[str, ...] = ("VRFA", "VRFB", "VRFC")
SEED_START = dt.date(2009, 10, 1)
PRUNE_YEARS = 6
FAKE_ALEMBIC = "meas_verify_0001"
REPORT_DIR = REPO_ROOT / "docs" / "superpowers" / "measurements"
DUMMY_MARKET_ENV = {"TRADIER_API_TOKEN": "dummy-verify-token", "TRADIER_BASE_URL": "https://sandbox.invalid",
                    "TIINGO_API_TOKEN": "dummy-verify-token"}
EXIT_OK, EXIT_FAILED, EXIT_REFUSED = 0, 1, 2

# ── child code: runs the TAG's code from the temporary tag checkout ──────────
# Each prints APP_INSIDE_CWD=1 when the imported ``app`` package is the tag
# checkout's (cwd = <tag checkout>/backend), never another checkout's.

_APP_CHECK = (
    "import os, app\n"
    "print('APP_INSIDE_CWD=' + ('1' if os.path.abspath(app.__file__).lower()"
    ".startswith(os.getcwd().lower() + os.sep) else '0'), flush=True)\n"
)

DDL_CODE = (
    "from sqlalchemy.dialects import postgresql\n"
    "from sqlalchemy.schema import CreateTable\n"
    "from app.models.ohlcv_daily import OhlcvDailyModel\n"
    "print(str(CreateTable(OhlcvDailyModel.__table__).compile(dialect=postgresql.dialect())).strip() + ';')\n"
)

PRUNE_CODE = _APP_CHECK + (
    "import asyncio\n"
    "from app.services.ingestion_job import _prune_old_rows\n"
    f"n = asyncio.run(_prune_old_rows({PRUNE_YEARS}))\n"
    "print(f'PRUNED={n}', flush=True)\n"
)

HOLD_CODE = _APP_CHECK + (
    "import asyncio, sys\n"
    "from sqlalchemy import text\n"
    "from app.database import AsyncSessionLocal\n"
    "async def main():\n"
    "    async with AsyncSessionLocal() as db:\n"
    "        row = (await db.execute(text('SELECT current_database(), current_user'))).one()\n"
    "        print(f'HOLDING={row[0]}|{row[1]}', flush=True)\n"
    "        sys.stdin.readline()\n"
    "asyncio.run(main())\n"
)

CONNECT_CODE = _APP_CHECK + (
    "import asyncio, sys\n"
    "from sqlalchemy import text\n"
    "from app.database import engine\n"
    "async def main():\n"
    "    try:\n"
    "        async with engine.connect() as conn:\n"
    "            await conn.execute(text('SELECT 1'))\n"
    "    except Exception as exc:\n"
    "        inner = getattr(exc, 'orig', None) or exc.__cause__ or exc\n"
    "        print('CONNECT_ERROR=' + type(exc).__name__ + '/' + type(inner).__name__, flush=True)\n"
    "        print('PERMISSION=' + ('1' if 'permission denied for database' in str(exc).lower() else '0'),"
    " flush=True)\n"
    "        return 3\n"
    "    print('CONNECTED=1', flush=True)\n"
    "    return 0\n"
    "sys.exit(asyncio.run(main()))\n"
)


# ── pure helpers (unit-tested in CI, no Docker) ──────────────────────────────

@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def new_container_name(token_hex: Callable[[int], str] = secrets.token_hex) -> str:
    return f"{CONTAINER_PREFIX}{token_hex(6)}"


def check_container_name(name: str) -> None:
    """Only a ``meas-verify-<hex>`` throwaway; never the live container."""
    if not name or name.casefold() == iso.DB_CONTAINER.casefold():
        raise iso.GuardRefusal("refusing: that is the live database container")
    if not _CONTAINER_NAME_RE.match(name):
        raise iso.GuardRefusal("refusing: container name must be meas-verify-<hex>")


def docker_run_argv(name: str) -> list[str]:
    """The throwaway container. The password is NOT in argv: ``-e POSTGRES_PASSWORD``
    without a value makes docker take it from its own environment."""
    check_container_name(name)
    return ["docker", "run", "--rm", "-d", "--pull", "never", "--name", name,
            "-e", "POSTGRES_PASSWORD", "-e", f"POSTGRES_USER={SUPERUSER}", "-e", f"POSTGRES_DB={FAKE_LIVE_DB}",
            "-p", "127.0.0.1::5432", IMAGE]


def docker_stop_argv(name: str) -> list[str]:
    check_container_name(name)
    return ["docker", "stop", "-t", "5", name]


def docker_env(base: Mapping[str, str], password: str) -> dict[str, str]:
    env = dict(base)
    env["POSTGRES_PASSWORD"] = password
    return env


def parse_port_output(text: str) -> int:
    """``docker port <name> 5432/tcp`` -> the 127.0.0.1 host port."""
    for line in (text or "").splitlines():
        m = re.fullmatch(r"127\.0\.0\.1:(\d{1,5})", line.strip())
        if m:
            return int(m.group(1))
    raise iso.GuardRefusal("no 127.0.0.1 port mapping for the throwaway container")


def cutoff_for(today: dt.date, years: int) -> dt.date:
    """The tag's prune rule: ``date.today() - timedelta(days=years * 365)``."""
    return today - dt.timedelta(days=years * 365)


def expected_seed_rows(start: dt.date, end: dt.date, n_symbols: int) -> int:
    days = (end - start).days + 1
    weekdays = sum(1 for i in range(max(days, 0)) if (start + dt.timedelta(days=i)).weekday() < 5)
    return weekdays * n_symbols


def seed_sql(symbols: Iterable[str], start: dt.date, end: dt.date, alembic_version: str) -> str:
    syms = ", ".join(iso.quote_literal(s) for s in symbols)
    return (
        "/* verify:seed */\n"
        "CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY);\n"
        f"INSERT INTO alembic_version (version_num) VALUES ({iso.quote_literal(alembic_version)});\n"
        "INSERT INTO ohlcv_daily (symbol, date, open, high, low, close, volume, adj_factor, split_factor, "
        "div_cash, source, fetched_at)\n"
        "SELECT s, d::date, 100, 101, 99, 100.5, 1000000, 1, 1, 0, 'verify', now()\n"
        f"FROM unnest(ARRAY[{syms}]) AS s, "
        f"generate_series(DATE '{start.isoformat()}', DATE '{end.isoformat()}', interval '1 day') AS d\n"
        "WHERE extract(isodow FROM d) < 6;\n"
    )


def fake_live_url(port: int, password: str) -> str:
    return f"postgresql+asyncpg://{SUPERUSER}:{quote(password, safe='')}@127.0.0.1:{int(port)}/{FAKE_LIVE_DB}"


def check_tmp_path(path: Path | str, *, repo_root: Path | str = REPO_ROOT) -> None:
    path = Path(path)
    if not path.name.startswith(CONTAINER_PREFIX):
        raise iso.GuardRefusal("temporary paths must be named meas-verify-*")
    if iso.path_is_inside(path, repo_root):
        raise iso.GuardRefusal("the temporary tag checkout must be outside the repo")


def parse_marker(output: str, key: str) -> str | None:
    for line in (output or "").splitlines():
        if line.strip().startswith(key + "="):
            return line.strip()[len(key) + 1:]
    return None


def g1_matrix(live: Any, meas: Any, *, checkout: Path, repo_root: Path) -> list[Check]:
    """G1 passes for the valid meas config and refuses each violation (fake
    listener/connect seams: no port is real here)."""
    no_listeners = lambda: [("0.0.0.0", 135)]          # noqa: E731
    no_connect = lambda *_a, **_k: False                # noqa: E731
    base = dict(meas_port=iso.MEAS_PORT, meas_base=iso.MEAS_BASE, meas_checkout=checkout, repo_root=repo_root,
                list_listeners=no_listeners, tcp_connect=no_connect)

    def evaluate(meas_url: Any, **over: Any) -> tuple[list[Any], bool]:
        results = iso.g1_checks(live, meas_url, **{**base, **over})
        try:
            iso.enforce_g1(results)
            return results, False
        except iso.GuardRefusal:
            return results, True

    out: list[Check] = []
    results, refused = evaluate(meas)
    bad = [r.rule for r in results if not r.ok]
    out.append(Check("G1 passes for the valid meas config", not refused and not bad,
                     "all rules ok" if not bad else f"failed rules {bad}"))
    cases = [
        ("same dbname", "same_dbname", (replace(meas, dbname=live.dbname),), {}),
        ("wrong meas user", "meas_user", (replace(meas, user="someone_else"),), {}),
        ("port 8000", "meas_port", (meas,), {"meas_port": iso.LIVE_PORT,
                                             "meas_base": f"http://127.0.0.1:{iso.LIVE_PORT}"}),
        ("meas checkout inside the repo", "checkout_outside_repo", (meas,),
         {"meas_checkout": Path(repo_root) / ".claude" / "worktrees" / "meas-verify-inside"}),
    ]
    for label, rule, (meas_url,), over in cases:
        results, refused = evaluate(meas_url, **over)
        hit = any(r.rule == rule and not r.ok for r in results)
        out.append(Check(f"G1 refuses {label}", refused and hit,
                         f"rule {rule} {'failed' if hit else 'passed'}; enforce_g1 "
                         f"{'refused' if refused else 'did NOT refuse'}"))
    return out


def exit_code_for(checks: Iterable[Check]) -> int:
    checks = list(checks)
    return EXIT_OK if checks and all(c.ok for c in checks) else EXIT_FAILED


_ABS_PATH_RE = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]|/home/|/Users/|/tmp/")


def render_report(checks: list[Check], facts: Mapping[str, Any], *, date: dt.date,
                  secrets: Iterable[str]) -> str:
    """Markdown: facts (counts, versions) and one line per check. Refuses on any
    secret or absolute path."""
    checks = list(checks)
    passed = sum(1 for c in checks if c.ok)
    lines = [
        f"# MEAS isolation verification on disposable data ({date.isoformat()})",
        "",
        "Ticket #284 (MEAS-LIVE-DB-ISOLATION T4), plan "
        "`docs/superpowers/plans/2026-10-13-meas-live-db-isolation-plan.md` §3.",
        "Produced by `scripts/meas/verify_isolation_disposable.py` against a throwaway "
        f"`{IMAGE}` container (`meas-verify-<hex>`, `--rm`, host port chosen by Docker on 127.0.0.1); "
        "the live container, live database and live backend were not touched.",
        "",
        "## Facts",
        "",
    ]
    for k, v in facts.items():
        lines.append(f"- {k}: {v}")
    lines += ["", "## Checks", "", f"{passed}/{len(checks)} checks passed.", ""]
    for c in checks:
        lines.append(f"- {'PASS' if c.ok else 'FAIL'} {c.name}: {c.detail}")
    text = "\n".join(lines) + "\n"
    iso.assert_no_secret(text, [s for s in secrets if s])
    if _ABS_PATH_RE.search(text):
        raise iso.GuardRefusal("absolute path in the report; refusing to write it")
    return text


# ── the real run (Docker; Windows) ───────────────────────────────────────────

class _Run:
    def __init__(self, name: str, *, python: str, log: Callable[[str], None]):
        self.name, self.python, self.log_fn = name, python, log
        self.hexid = name[len(CONTAINER_PREFIX):]
        tmp_root = Path(tempfile.gettempdir())
        self.checkout = tmp_root / f"{CONTAINER_PREFIX}{self.hexid}"
        self.workdir = tmp_root / f"{CONTAINER_PREFIX}{self.hexid}-work"
        check_tmp_path(self.checkout)
        check_tmp_path(self.workdir)
        self.password = secrets.token_urlsafe(24)
        self.meas_password: str | None = None
        self.secrets: list[str] = [self.password]
        self.checks: list[Check] = []
        self.facts: dict[str, Any] = {}
        self.pg = iso.PgDocker(container=name)
        self.container_started = False
        self.worktree_added = False

    # logging / recording
    def log(self, line: str) -> None:
        self.log_fn(iso.redact_text(line, self.secrets))

    def check(self, name: str, ok: bool, detail: str) -> bool:
        detail = iso.redact_text(detail, self.secrets)
        detail = iso.scrub_paths(detail, [(self.checkout, "<tmp>/meas-verify-<hex>"), (REPO_ROOT, "<repo>"),
                                          (Path(tempfile.gettempdir()), "<tmp>"), (Path.home(), "~")])
        self.checks.append(Check(name, bool(ok), detail))
        self.log(f"{'PASS' if ok else 'FAIL'} {name}: {detail}")
        return bool(ok)

    def require(self, name: str, ok: bool, detail: str) -> None:
        if not self.check(name, ok, detail):
            raise iso.GuardRefusal(f"stopping: {name} failed")

    # subprocess helpers
    def git(self, *args: str) -> iso.CmdResult:
        return iso.subprocess_runner(["git", "-C", str(REPO_ROOT), *args], timeout=600)

    def _child_in_tag(self, code: str, env: Mapping[str, str], timeout: float) -> iso.CmdResult:
        proc = subprocess.run([self.python, "-c", code], cwd=str(self.checkout / "backend"), env=dict(env),
                              capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, stdin=subprocess.DEVNULL)
        return iso.CmdResult(proc.returncode, proc.stdout or "", proc.stderr or "")

    def stats(self, dbname: str, cutoff: dt.date) -> dict[str, Any]:
        return self.pg.select_json(
            "/* verify:stats */ SELECT json_build_object('count', count(*), 'min', min(date)::text, "
            f"'max', max(date)::text, 'older', count(*) FILTER (WHERE date < DATE '{cutoff.isoformat()}')) "
            "FROM public.ohlcv_daily;\n", dbname=dbname, what=f"ohlcv_daily stats ({dbname})")

    # steps
    def add_worktree(self) -> None:
        if self.checkout.exists():
            raise iso.GuardRefusal("temporary checkout path already exists")
        res = self.git("worktree", "add", "--detach", str(self.checkout), iso.TAG)
        self.worktree_added = res.returncode == 0 or self.checkout.exists()
        self.require("temporary tag checkout created outside the repo", res.returncode == 0,
                     f"git worktree add --detach <tmp>/meas-verify-<hex> {iso.TAG}: exit {res.returncode}")
        sha = self.git("-C", str(self.checkout), "rev-parse", "HEAD").stdout.strip()
        tag = self.git("rev-parse", f"{iso.TAG}^{{commit}}").stdout.strip()
        self.facts["tag"] = f"{iso.TAG} @ {tag}"
        self.require("temporary checkout HEAD is the tag commit", sha == tag and bool(sha),
                     f"HEAD {sha[:12]} vs tag {tag[:12]}")

    def start_container(self) -> int:
        argv = docker_run_argv(self.name)
        self.container_started = True   # from here on, finally stops it (by this name only)
        res = iso.subprocess_runner(argv, env=docker_env(os.environ, self.password), timeout=120)
        self.require("throwaway container started (--pull never, --rm, Docker-chosen port)",
                     res.returncode == 0, f"docker run exit {res.returncode}")
        deadline = time.monotonic() + 90
        while True:
            # TCP readiness: the image's init server listens on the socket only
            r = iso.subprocess_runner(["docker", "exec", self.name, "pg_isready", "-h", "127.0.0.1",
                                       "-U", SUPERUSER, "-d", FAKE_LIVE_DB], timeout=30)
            if r.returncode == 0:
                break
            if time.monotonic() > deadline:
                self.require("throwaway Postgres ready", False, "pg_isready did not succeed in 90 s")
            time.sleep(1.0)
        port = parse_port_output(iso.subprocess_runner(["docker", "port", self.name, "5432/tcp"],
                                                       timeout=30).stdout)
        if port == 5433:
            raise iso.GuardRefusal("Docker mapped the live port; refusing")
        ver = self.pg.select_json("/* verify:version */ SELECT to_json(current_setting('server_version'));\n",
                                  dbname=FAKE_LIVE_DB, what="server version")
        self.facts["postgres"] = f"{IMAGE} (server {ver})"
        self.check("throwaway Postgres ready", True, "pg_isready over TCP ok; host port chosen by Docker")
        return port

    def stop_container(self) -> None:
        try:
            iso.subprocess_runner(docker_stop_argv(self.name), timeout=60)
        except Exception as exc:
            self.log(f"docker stop failed ({type(exc).__name__})")
        gone = False
        for _ in range(30):
            r = iso.subprocess_runner(["docker", "ps", "-a", "-q", "--filter", f"name=^/{self.name}$"], timeout=30)
            if r.returncode == 0 and not r.stdout.strip():
                gone = True
                break
            time.sleep(1.0)
        self.check("throwaway container stopped and removed", gone,
                   "docker ps -a shows no meas-verify-<hex> container" if gone else "container still listed")

    def remove_worktree(self) -> None:
        if self.worktree_added or self.checkout.exists():
            self.git("worktree", "remove", "--force", str(self.checkout))
            if self.checkout.exists():
                check_tmp_path(self.checkout)
                shutil.rmtree(self.checkout, ignore_errors=True)
        self.git("worktree", "prune")
        listed = str(self.checkout).replace("\\", "/").lower() in \
            self.git("worktree", "list", "--porcelain").stdout.replace("\\", "/").lower()
        self.check("temporary tag checkout removed", not self.checkout.exists() and not listed,
                   "git worktree remove --force + prune; path gone and not listed")
        if self.workdir.exists():
            check_tmp_path(self.workdir)
            shutil.rmtree(self.workdir, ignore_errors=True)

    def body(self) -> None:
        check_container_name(self.name)
        self.check("container is a throwaway, never the live one", True,
                   f"meas-verify-<hex> != {iso.DB_CONTAINER}")
        self.add_worktree()
        port = self.start_container()
        live = iso.parse_db_url(fake_live_url(port, self.password))
        self.secrets = [self.password]

        # (a) seed fake_live with the tag's ohlcv_daily DDL
        base_child = iso.build_child_env(os.environ, {"PYTHONUTF8": "1"})
        ddl_res = self._child_in_tag(DDL_CODE, base_child, 120)
        self.require("tag ohlcv_daily DDL compiled from the tag model", ddl_res.returncode == 0
                     and "CREATE TABLE ohlcv_daily" in ddl_res.stdout, f"exit {ddl_res.returncode}")
        today = dt.date.today()
        cutoff = cutoff_for(today, PRUNE_YEARS)
        self.pg.superuser_sql(ddl_res.stdout.strip() + "\n" + seed_sql(SYMBOLS, SEED_START, today, FAKE_ALEMBIC),
                              dbname=FAKE_LIVE_DB, read_only=False, what="seed fake_live",
                              secret_values=self.secrets)
        live_before = self.stats(FAKE_LIVE_DB, cutoff)
        expected = expected_seed_rows(SEED_START, today, len(SYMBOLS))
        self.facts["seed"] = (f"{len(SYMBOLS)} symbols, weekdays {SEED_START.isoformat()}..{today.isoformat()}, "
                              f"{live_before['count']} rows")
        self.facts["prune cutoff (tag rule, 6*365 days)"] = cutoff.isoformat()
        self.require("fake_live seeded", live_before["count"] == expected and live_before["older"] > 0,
                     f"rows {live_before['count']} (expected {expected}), older than cutoff {live_before['older']}, "
                     f"min {live_before['min']}, max {live_before['max']}")

        # (b) setup, copy, verify: the orchestrator's own functions
        self.workdir.mkdir(parents=True, exist_ok=False)
        secret_file = self.workdir / "meas_db.secret"
        result = iso.setup(live, secret_file, pg=self.pg, log=self.log)
        self.meas_password = iso.read_secret_file(secret_file)
        self.secrets = [self.password, self.meas_password]
        self.require("isolated_day.setup against fake_live", result.get("live_user_connects") is True
                     and all(r["ok"] for r in result["g2"]),
                     f"role {result['role']}, database {result['database']}, REVOKE CONNECT on fake_live, "
                     f"G2 in setup {[r['rule'] for r in result['g2'] if r['ok']]}")
        iso.copy_live_to_meas(live, pg=self.pg)
        copy_ver = iso.verify_copy(live, pg=self.pg)
        copy_before = self.stats(iso.MEAS_DBNAME, cutoff)
        self.require("copy_live_to_meas + verify_copy", copy_before["count"] == live_before["count"]
                     and copy_before["min"] == live_before["min"],
                     f"tables {copy_ver['tables']}, ohlcv_daily copy {copy_before['count']} = live "
                     f"{live_before['count']}, alembic_version {copy_ver['alembic_version']}")
        self.check("psql accepts the SQL isolated_day sends on stdin from this platform",
                   True, f"setup/copy/verify sessions succeeded; stdin newline here is "
                         f"{'CRLF' if os.linesep == chr(13) + chr(10) else 'LF'} ({platform.system()})")

        # (c) G2 against fake_live
        g2 = iso.check_live_db_refused(live, self.meas_password, pg=self.pg)
        self.check("G2 check_live_db_refused against fake_live", all(r.ok for r in g2),
                   "; ".join(f"{r.rule}={'ok' if r.ok else 'FAIL'}" for r in g2))

        # (d) G3: no session -> fails; tag code holding a session on the copy -> passes
        g3_none = iso.meas_connections_ok(pg=self.pg)
        self.check("G3 meas_connections_ok fails with no meas_runner session", not g3_none.ok, g3_none.detail)
        meas_url = iso.build_meas_url(live, self.meas_password)
        meas_env = iso.meas_dotenv_values(DUMMY_MARKET_ENV, meas_url)
        iso.write_meas_dotenv(self.checkout / ".env", meas_env, expected_database_url=meas_url)
        child_env = iso.build_child_env(os.environ, {**meas_env, "PYTHONUTF8": "1"})
        self.hold_and_probe(child_env)

        # (e) the tag's prune on the copy
        prune = self._child_in_tag(PRUNE_CODE, child_env, 300)
        pruned = parse_marker(prune.stdout, "PRUNED")
        self.require("tag _prune_old_rows(6) ran from the tag checkout", prune.returncode == 0
                     and parse_marker(prune.stdout, "APP_INSIDE_CWD") == "1" and pruned is not None,
                     f"exit {prune.returncode}, app from the tag checkout "
                     f"{parse_marker(prune.stdout, 'APP_INSIDE_CWD')}, deleted {pruned}"
                     + ("" if prune.returncode == 0 else f": {prune.stderr.strip()[-300:]}"))
        copy_after = self.stats(iso.MEAS_DBNAME, cutoff)
        live_after = self.stats(FAKE_LIVE_DB, cutoff)
        self.facts["copy rows before / after prune"] = f"{copy_before['count']} / {copy_after['count']}"
        self.facts["copy rows older than cutoff before / after"] = f"{copy_before['older']} / {copy_after['older']}"
        self.facts["copy min date before / after"] = f"{copy_before['min']} / {copy_after['min']}"
        self.facts["fake_live rows before / after"] = f"{live_before['count']} / {live_after['count']}"
        self.facts["fake_live min date before / after"] = f"{live_before['min']} / {live_after['min']}"
        self.check("copy lost every row older than 6*365 days",
                   copy_after["older"] == 0 and copy_after["min"] is not None
                   and copy_after["min"] >= cutoff.isoformat()
                   and int(pruned) == copy_before["older"]
                   and copy_after["count"] == copy_before["count"] - copy_before["older"],
                   f"deleted {pruned} (expected {copy_before['older']}), older rows after {copy_after['older']}, "
                   f"min after {copy_after['min']} >= cutoff {cutoff.isoformat()}")
        self.check("fake_live unchanged by the prune", live_after == live_before,
                   f"count {live_after['count']}, min {live_after['min']}, max {live_after['max']}, "
                   f"older {live_after['older']}")

        # (f) tag code pointed at fake_live as meas_runner is refused
        cross_env = iso.build_child_env(os.environ, {
            "DATABASE_URL": iso.build_meas_url(live, self.meas_password, dbname=FAKE_LIVE_DB), "PYTHONUTF8": "1"})
        cross = self._child_in_tag(CONNECT_CODE, cross_env, 120)
        err = parse_marker(cross.stdout, "CONNECT_ERROR")
        self.check("tag code with DATABASE_URL=fake_live as meas_runner cannot connect",
                   cross.returncode == 3 and parse_marker(cross.stdout, "PERMISSION") == "1"
                   and parse_marker(cross.stdout, "CONNECTED") is None,
                   f"exit {cross.returncode}, error class {err}, permission refusal "
                   f"{parse_marker(cross.stdout, 'PERMISSION')}")

        # G2 still holds after everything
        g2_end = iso.check_live_db_refused(live, self.meas_password, pg=self.pg)
        self.check("G2 still holds at the end", all(r.ok for r in g2_end),
                   "; ".join(f"{r.rule}={'ok' if r.ok else 'FAIL'}" for r in g2_end))

        # (g) G1 matrix
        meas_db = iso.parse_db_url(meas_url)
        for c in g1_matrix(live, meas_db, checkout=self.checkout, repo_root=REPO_ROOT):
            self.check(c.name, c.ok, c.detail)

    def hold_and_probe(self, child_env: Mapping[str, str]) -> None:
        proc = subprocess.Popen([self.python, "-c", HOLD_CODE], cwd=str(self.checkout / "backend"),
                                env=dict(child_env), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        holding, inside = None, None
        try:
            deadline = time.monotonic() + 120
            assert proc.stdout is not None
            while time.monotonic() < deadline and holding is None:
                line = proc.stdout.readline()
                if not line:
                    break
                inside = parse_marker(line, "APP_INSIDE_CWD") or inside
                holding = parse_marker(line, "HOLDING") or holding
            g3 = iso.meas_connections_ok(pg=self.pg)
            self.check("tag code holds a session on the copy as meas_runner",
                       holding == f"{iso.MEAS_DBNAME}|{iso.MEAS_USER}" and inside == "1",
                       f"current_database|current_user = {holding}, app from the tag checkout {inside}")
            self.check("G3 meas_connections_ok passes while the tag code is connected", g3.ok, g3.detail)
        finally:
            try:
                assert proc.stdin is not None
                proc.stdin.write("\n")
                proc.stdin.close()
            except OSError:
                pass
            try:
                proc.wait(timeout=60)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=30)

    def execute(self) -> int:
        try:
            self.body()
        except iso.GuardRefusal as exc:
            self.check("run completed", False, str(exc))
        except Exception as exc:   # type + redacted text only, never a traceback
            self.check("run completed", False, f"unexpected {type(exc).__name__}: {exc}")
        finally:
            try:
                if self.container_started:
                    self.stop_container()
            finally:
                self.remove_worktree()
        self.facts["python"] = platform.python_version()
        self.facts["platform"] = platform.system()
        return exit_code_for(self.checks)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="MEAS isolation verification on a throwaway Postgres container.")
    ap.add_argument("--container-name", default=None, help="meas-verify-<hex> (default: random)")
    ap.add_argument("--no-report", action="store_true", help="do not write the markdown report")
    args = ap.parse_args(argv)
    name = args.container_name or new_container_name()
    try:
        check_container_name(name)
    except iso.GuardRefusal as exc:
        print(f"REFUSED: {exc}", flush=True)
        return EXIT_REFUSED
    run = _Run(name, python=sys.executable, log=lambda line: print(line, flush=True))
    code = run.execute()
    passed = sum(1 for c in run.checks if c.ok)
    print(f"SUMMARY: {passed}/{len(run.checks)} checks passed; exit {code}", flush=True)
    if not args.no_report:
        today = dt.date.today()
        text = render_report(run.checks, run.facts, date=today, secrets=run.secrets)
        out = REPORT_DIR / f"isolation-verification-{today.isoformat()}.md"
        out.write_text(text, encoding="utf-8", newline="\n")
        print(f"report: docs/superpowers/measurements/{out.name}", flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
