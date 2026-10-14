"""Tests for scripts/meas/isolated_day.py: the DB layer (#282, plan
docs/superpowers/plans/2026-10-13-meas-live-db-isolation-plan.md §2.2, §2.3 G2
and the DB half of G3, §2.5, T2).

Every database action goes through ``docker exec`` into the Postgres container.
These tests never run docker: a fake runner records each call (argv, stdin,
subprocess env) and answers from an in-memory "world". The assertions pin the
command shapes the plan requires:

- superuser commands use the container's own ``$POSTGRES_USER`` (no credential
  in argv); SQL travels on stdin;
- the meas password reaches docker only through the subprocess env behind
  ``docker exec -e PGPASSWORD`` (never argv, never a result or a log line);
- the live database name appears only in ``pg_dump``, in read-only SELECT
  sessions, in setup's single ``REVOKE`` and in the G2 connect attempt;
- every refusal rule of §2.5 / G2 / G3 refuses, and the happy paths pass.

All credentials are synthetic. scripts/ is not a package, so the module is
loaded by path, matching test_meas_isolated_day_config.py.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import pytest

_SCRIPT_PATH = Path(__file__).parent.parent.parent / "scripts" / "meas" / "isolated_day.py"
if "meas_isolated_day" in sys.modules:
    iso = sys.modules["meas_isolated_day"]
else:
    _spec = importlib.util.spec_from_file_location("meas_isolated_day", _SCRIPT_PATH)
    iso = importlib.util.module_from_spec(_spec)
    sys.modules["meas_isolated_day"] = iso  # dataclasses resolve their module by name
    _spec.loader.exec_module(iso)  # type: ignore[union-attr]


LIVE_PW = "LivePw-Synthetic-123"
MEAS_PW = "MeasPw_synthetic_TOKEN_abcdef0123456789"
LIVE_DB = "TradingAssistantDB"
LIVE_URL = f"postgresql+asyncpg://bamendjou:{LIVE_PW}@localhost:5433/{LIVE_DB}"
SECRETS = [LIVE_PW, MEAS_PW]

PERMISSION_DENIED = (
    'psql: error: connection to server at "127.0.0.1", port 5432 failed: '
    f'FATAL:  permission denied for database "{LIVE_DB}"\n'
    "DETAIL:  User does not have CONNECT privilege.\n"
)


def _live():
    return iso.parse_db_url(LIVE_URL)


# ── fake docker runner ───────────────────────────────────────────────────────

@dataclass
class Call:
    argv: list[str]
    input: str | None
    env: dict[str, str] | None
    timeout: float | None

    @property
    def script(self) -> str | None:
        """The ``sh -c`` script of a superuser call, else None."""
        if len(self.argv) >= 2 and self.argv[-2] == "-c" and "sh" in self.argv:
            return self.argv[-1]
        return None

    @property
    def tag(self) -> str | None:
        m = re.search(r"/\* (meas:[a-z0-9-]+) \*/", self.input or "")
        return m.group(1) if m else None

    @property
    def db(self) -> str | None:
        tokens = shlex.split(self.script) if self.script else self.argv
        if self.script and "pg_dump" in self.script:
            return None
        for i, tok in enumerate(tokens):
            if tok == "-d" and i + 1 < len(tokens):
                return tokens[i + 1]
        return None


def _ok(stdout: str = "") -> Any:
    return iso.CmdResult(0, stdout, "")


def _fail(stderr: str, rc: int = 2) -> Any:
    return iso.CmdResult(rc, "", stderr)


@dataclass
class World:
    """In-memory container: answers the orchestrator's tagged SQL."""

    live_user_super: bool = True
    live_user_owner: bool = False
    live_db_exists: bool = True
    role_exists: bool = False
    role_super: bool = False
    meas_db_exists: bool = False
    live_tables: dict[str, int] = field(default_factory=lambda: {
        "alembic_version": 1, "ohlcv_daily": 1000, "scan_runs": 40, "audit_events": 7})
    copy_tables: dict[str, int] = field(default_factory=lambda: {
        "alembic_version": 1, "ohlcv_daily": 1000, "scan_runs": 40, "audit_events": 7})
    live_ohlcv: dict[str, Any] = field(default_factory=lambda: {
        "count": 1000, "min": "2009-01-02", "max": "2026-10-13"})
    copy_ohlcv: dict[str, Any] = field(default_factory=lambda: {
        "count": 1000, "min": "2009-01-02", "max": "2026-10-13"})
    live_alembic: list[str] = field(default_factory=lambda: ["8ee11537abcd"])
    copy_alembic: list[str] = field(default_factory=lambda: ["8ee11537abcd"])
    restore_rc: int = 0
    meas_connect: Any = None  # CmdResult for the G2 connect attempt
    activity: dict[str, int] = field(default_factory=lambda: {"bamendjou_meas": 3})
    live_connect_ok: bool = True
    fail_tags: dict[str, Any] = field(default_factory=dict)
    raise_on: Callable[[Call], bool] | None = None
    calls: list[Call] = field(default_factory=list)

    def run(self, argv, *, input=None, env=None, timeout=None):
        call = Call(list(argv), input, dict(env) if env is not None else None, timeout)
        self.calls.append(call)
        if self.raise_on and self.raise_on(call):
            raise FileNotFoundError("docker")
        if call.tag in self.fail_tags:
            return self.fail_tags[call.tag]
        if call.script and "pg_dump" in call.script:
            return _ok() if self.restore_rc == 0 else _fail("pg_restore: error: boom", self.restore_rc)
        if "meas_runner" in argv and "-U" in argv:  # G2 connect attempt
            return self.meas_connect or _fail(PERMISSION_DENIED)
        return self._sql(call)

    def _sql(self, call: Call):
        tag, db = call.tag, call.db
        is_live = db == LIVE_DB
        if tag == "meas:setup-precheck":
            return _ok(json.dumps({
                "live_db_exists": self.live_db_exists, "live_user_super": self.live_user_super,
                "live_user_owner": self.live_user_owner, "role_exists": self.role_exists,
                "meas_db_exists": self.meas_db_exists}))
        if tag in ("meas:create-role", "meas:alter-role"):
            self.role_exists = True
            return _ok()
        if tag in ("meas:create-db", "meas:alter-db-owner"):
            self.meas_db_exists = True
            return _ok()
        if tag == "meas:revoke":
            return _ok()
        if tag == "meas:live-connect":
            if not self.live_connect_ok:
                return _fail(f'FATAL:  permission denied for database "{LIVE_DB}"')
            return _ok(json.dumps({"one": 1, "live_user_can_connect": True}))
        if tag == "meas:drop-create":
            return _ok()
        if tag == "meas:g2-role":
            return _ok(json.dumps({"exists": True, "rolsuper": self.role_super}))
        if tag == "meas:g3-activity":
            return _ok(json.dumps(self.activity))
        if tag == "meas:tables":
            tables = self.live_tables if is_live else self.copy_tables
            return _ok(json.dumps(sorted(tables)))
        if tag == "meas:counts":
            return _ok(json.dumps(self.live_tables if is_live else self.copy_tables))
        if tag == "meas:ohlcv":
            return _ok(json.dumps(self.live_ohlcv if is_live else self.copy_ohlcv))
        if tag == "meas:alembic":
            return _ok(json.dumps(self.live_alembic if is_live else self.copy_alembic))
        raise AssertionError(f"unexpected call: tag={tag} argv={call.argv}")


def _pg(world: World, **kw):
    return iso.PgDocker(runner=world.run, **kw)


def _strip_comments(sql: str) -> str:
    return re.sub(r"/\*.*?\*/", "", sql, flags=re.S)


def _statements(sql: str) -> list[str]:
    return [s.strip() for s in _strip_comments(sql).split(";") if s.strip()]


def _is_select_only_session(call: Call) -> bool:
    sql = call.input or ""
    if not sql.startswith(iso.READ_ONLY_PREFIX):
        return False
    stmts = _statements(sql[len(iso.READ_ONLY_PREFIX):])
    return bool(stmts) and all(s.upper().startswith("SELECT") for s in stmts)


def _is_g2_connect(call: Call) -> bool:
    a = call.argv
    return ("meas_runner" in a and a[a.index("-U") + 1] == "meas_runner"
            and a[-2:] == ["-c", "SELECT 1"] and call.input is None)


def _is_pg_dump(call: Call) -> bool:
    s = call.script or ""
    if "pg_dump" not in s:
        return False
    head, _, tail = s.partition("|")
    return "pg_dump" in head and LIVE_DB in head and LIVE_DB not in tail


def _is_revoke(call: Call) -> bool:
    return _statements(call.input or "") == [f'REVOKE CONNECT ON DATABASE "{LIVE_DB}" FROM PUBLIC']


def _live_db_mentions(calls: list[Call]) -> list[str]:
    """Classify every call that names the live DB; anything unclassified fails."""
    kinds = []
    for c in calls:
        blob = " ".join(c.argv) + "\n" + (c.input or "")
        if LIVE_DB not in blob:
            continue
        if _is_pg_dump(c):
            kinds.append("pg_dump")
        elif _is_g2_connect(c):
            kinds.append("g2_connect")
        elif _is_revoke(c):
            kinds.append("revoke")
        elif _is_select_only_session(c):
            kinds.append("select")
        else:
            raise AssertionError(f"live DB named outside pg_dump/SELECT/REVOKE/G2: {c.argv} {c.input!r}")
    return kinds


def _assert_no_secret_anywhere(world: World, *extra: Any) -> None:
    for c in world.calls:
        iso.assert_no_secret(c.argv, SECRETS)
        if c.tag not in ("meas:create-role", "meas:alter-role"):  # the only stdin carrying it
            iso.assert_no_secret(c.input or "", SECRETS)
        else:
            assert LIVE_PW not in c.input
        if c.env is not None:  # only the G2 attempt carries PGPASSWORD, in env
            assert _is_g2_connect(c), c.argv
            assert set(c.env) - set(os.environ) <= {"PGPASSWORD"}
            assert c.env["PGPASSWORD"] == MEAS_PW
            assert "-e" in c.argv and c.argv[c.argv.index("-e") + 1] == "PGPASSWORD"
    for obj in extra:
        iso.assert_no_secret(obj, SECRETS)


# ── hardening: libpq variables never reach the frozen backend ────────────────

def test_child_env_strips_libpq_variables_case_insensitively():
    base = {
        "PATH": "/bin", "PYTHONPATH": "p", "XPGHOST": "keep",
        "PGPASSWORD": MEAS_PW, "pgpassword": LIVE_PW, "PgHost": "db", "PGPORT": "5433",
        "PGUSER": "bamendjou", "PGDATABASE": LIVE_DB, "PGSERVICE": "live", "PGSERVICEFILE": "f",
        "PGPASSFILE": "pass", "PGSSLMODE": "disable", "PGOPTIONS": "-c x=y", "PGAPPNAME": "a",
    }
    child = iso.build_child_env(base, {"DATABASE_URL": "postgresql://meas_runner:x@h:1/bamendjou_meas"})
    assert child == {"PATH": "/bin", "PYTHONPATH": "p", "XPGHOST": "keep",
                     "DATABASE_URL": "postgresql://meas_runner:x@h:1/bamendjou_meas"}


# ── the docker seam ──────────────────────────────────────────────────────────

def test_container_name_constant_and_override():
    assert iso.DB_CONTAINER == "tradingassistant-db"
    assert iso.PgDocker().container == "tradingassistant-db"
    w = World()
    iso.meas_connections_ok(pg=_pg(w, container="throwaway-pg"))
    assert w.calls[0].argv[:4] == ["docker", "exec", "-i", "throwaway-pg"]


def test_superuser_session_shape_uses_container_env_and_stdin():
    w = World()
    iso.meas_connections_ok(pg=_pg(w))
    (c,) = w.calls
    assert c.argv[:4] == ["docker", "exec", "-i", "tradingassistant-db"]
    assert c.argv[4:6] == ["sh", "-c"]
    tokens = shlex.split(c.script)
    assert tokens[:2] == ["exec", "psql"]
    assert tokens[tokens.index("-U") + 1] == "$POSTGRES_USER" or '"$POSTGRES_USER"' in c.script
    assert '-U "$POSTGRES_USER"' in c.script
    assert "ON_ERROR_STOP=1" in c.script
    assert "-c" not in tokens  # SQL never in argv
    assert c.input and "pg_stat_activity" in c.input
    assert c.env is None


def test_subprocess_runner_wraps_subprocess(monkeypatch):
    seen = {}

    def fake_run(argv, **kw):
        seen.update(kw, argv=argv)
        return subprocess.CompletedProcess(argv, 3, "out", "err")

    monkeypatch.setattr(iso.subprocess, "run", fake_run)
    r = iso.subprocess_runner(["docker", "ps"], input="x", env={"A": "1"}, timeout=5)
    assert (r.returncode, r.stdout, r.stderr) == (3, "out", "err")
    assert seen["input"] == "x" and seen["env"] == {"A": "1"} and seen["timeout"] == 5
    assert seen["capture_output"] is True and seen["text"] is True


def test_quote_ident_and_literal():
    assert iso.quote_ident(LIVE_DB) == '"TradingAssistantDB"'
    assert iso.quote_ident('we"ird') == '"we""ird"'
    assert iso.quote_literal("it's") == "'it''s'"


# ── setup (§2.3 G2 one-time) ─────────────────────────────────────────────────

def _setup(tmp_path, w, **kw):
    logs: list[str] = []
    secret = tmp_path / "meas_db.secret"
    kw.setdefault("token_factory", lambda: MEAS_PW)
    result = iso.setup(_live(), secret, pg=_pg(w), log=logs.append,
                       restrict_acl=lambda p: None, **kw)
    return result, logs, secret


def test_setup_happy_path(tmp_path):
    w = World()
    result, logs, secret = _setup(tmp_path, w)

    assert iso.read_secret_file(secret) == MEAS_PW
    tags = [c.tag for c in w.calls if c.tag]
    assert tags[:5] == ["meas:setup-precheck", "meas:create-role", "meas:create-db",
                        "meas:revoke", "meas:live-connect"]
    assert "meas:g2-role" in tags

    role = next(c for c in w.calls if c.tag == "meas:create-role")
    stmts = _statements(role.input)
    assert stmts == [f"CREATE ROLE meas_runner WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                     f"NOREPLICATION NOBYPASSRLS PASSWORD '{MEAS_PW}'"]
    assert role.db == "postgres"

    db = next(c for c in w.calls if c.tag == "meas:create-db")
    assert _statements(db.input) == ['CREATE DATABASE "bamendjou_meas" OWNER "meas_runner"']

    revoke = [c for c in w.calls if c.tag == "meas:revoke"]
    assert len(revoke) == 1 and _is_revoke(revoke[0]) and revoke[0].db == "postgres"

    live_check = next(c for c in w.calls if c.tag == "meas:live-connect")
    assert live_check.db == LIVE_DB and _is_select_only_session(live_check)

    reverse = f'GRANT CONNECT ON DATABASE "{LIVE_DB}" TO PUBLIC'
    assert result["reverse_command"] == reverse
    assert any(reverse in line for line in logs)
    assert result["role"] == "created" and result["database"] == "created"
    assert result["live_user_connects"] is True
    assert all(g["ok"] for g in result["g2"])

    _assert_no_secret_anywhere(w, result, logs)
    assert sorted(set(_live_db_mentions(w.calls))) == ["g2_connect", "revoke", "select"]
    assert _live_db_mentions(w.calls).count("revoke") == 1


def test_setup_is_idempotent_with_existing_role_db_and_secret(tmp_path):
    w = World(role_exists=True, meas_db_exists=True)
    secret = tmp_path / "meas_db.secret"
    iso.write_secret_file(secret, restrict_acl=lambda p: None, token_factory=lambda: MEAS_PW)
    result, _logs, _ = _setup(tmp_path, w, token_factory=lambda: "SHOULD-NOT-BE-USED")
    assert iso.read_secret_file(secret) == MEAS_PW
    tags = [c.tag for c in w.calls if c.tag]
    assert "meas:create-role" not in tags and "meas:create-db" not in tags
    alter = next(c for c in w.calls if c.tag == "meas:alter-role")
    assert _statements(alter.input) == [f"ALTER ROLE meas_runner WITH LOGIN NOSUPERUSER NOCREATEDB "
                                        f"NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD '{MEAS_PW}'"]
    owner = next(c for c in w.calls if c.tag == "meas:alter-db-owner")
    assert _statements(owner.input) == ['ALTER DATABASE "bamendjou_meas" OWNER TO "meas_runner"']
    assert result["role"] == "updated" and result["database"] == "exists"
    _assert_no_secret_anywhere(w, result)


def test_setup_rotate_generates_a_new_password(tmp_path):
    w = World(role_exists=True, meas_db_exists=True)
    secret = tmp_path / "meas_db.secret"
    iso.write_secret_file(secret, restrict_acl=lambda p: None, token_factory=lambda: "OldPw_synthetic_1234")
    _setup(tmp_path, w, rotate=True)
    assert iso.read_secret_file(secret) == MEAS_PW
    alter = next(c for c in w.calls if c.tag == "meas:alter-role")
    assert MEAS_PW in alter.input and "OldPw_synthetic_1234" not in alter.input


def test_setup_refuses_before_revoke_if_live_user_would_be_locked_out(tmp_path):
    w = World(live_user_super=False, live_user_owner=False)
    with pytest.raises(iso.GuardRefusal, match="lock"):
        _setup(tmp_path, w)
    assert not any(c.tag == "meas:revoke" for c in w.calls)


def test_setup_allows_owner_live_user(tmp_path):
    w = World(live_user_super=False, live_user_owner=True)
    result, _, _ = _setup(tmp_path, w)
    assert result["live_user_connects"] is True


def test_setup_refuses_when_live_db_missing(tmp_path):
    w = World(live_db_exists=False)
    with pytest.raises(iso.GuardRefusal, match="live database"):
        _setup(tmp_path, w)
    assert not any(c.tag in ("meas:create-role", "meas:revoke") for c in w.calls)


def test_setup_refuses_and_prints_reverse_when_live_connect_fails(tmp_path):
    w = World(live_connect_ok=False)
    with pytest.raises(iso.GuardRefusal) as exc:
        _setup(tmp_path, w)
    assert f'GRANT CONNECT ON DATABASE "{LIVE_DB}" TO PUBLIC' in str(exc.value)


def test_setup_refuses_when_g2_fails_afterwards(tmp_path):
    w = World(meas_connect=_ok("1\n"))
    with pytest.raises(iso.GuardRefusal, match="G2"):
        _setup(tmp_path, w)


def test_setup_sql_error_is_redacted(tmp_path):
    leak = f"ERROR:  boom\nLINE 1: CREATE ROLE meas_runner ... PASSWORD '{MEAS_PW}'"
    w = World(fail_tags={"meas:create-role": _fail(leak, 3)})
    with pytest.raises(iso.GuardRefusal) as exc:
        _setup(tmp_path, w)
    assert MEAS_PW not in str(exc.value)
    assert not any(c.tag == "meas:revoke" for c in w.calls)


@pytest.mark.parametrize("url", [
    f"postgresql://bamendjou:{LIVE_PW}@localhost:5433/bamendjou_meas",
    f"postgresql://bamendjou:{LIVE_PW}@localhost:5433/BAMENDJOU_MEAS",
    f"postgresql://meas_runner:{LIVE_PW}@localhost:5433/{LIVE_DB}",
])
def test_setup_refuses_when_live_identity_collides_with_meas(tmp_path, url):
    w = World()
    with pytest.raises(iso.GuardRefusal):
        iso.setup(iso.parse_db_url(url), tmp_path / "s", pg=_pg(w), log=lambda s: None,
                  restrict_acl=lambda p: None, token_factory=lambda: MEAS_PW)
    assert w.calls == []


def test_setup_refuses_conninfo_like_live_dbname(tmp_path):
    w = World()
    with pytest.raises(iso.GuardRefusal):
        iso.setup(iso.parse_db_url(f"postgresql://u:{LIVE_PW}@h:1/host%3Devil"), tmp_path / "s",
                  pg=_pg(w), log=lambda s: None, restrict_acl=lambda p: None,
                  token_factory=lambda: MEAS_PW)
    assert w.calls == []


# ── copy (§2.5) ──────────────────────────────────────────────────────────────

def test_copy_command_shapes():
    w = World()
    out = iso.copy_live_to_meas(_live(), pg=_pg(w, copy_timeout=1234))
    drop, dump = w.calls
    assert drop.db == "postgres"
    assert _statements(drop.input) == ['DROP DATABASE IF EXISTS "bamendjou_meas" WITH (FORCE)',
                                       'CREATE DATABASE "bamendjou_meas" OWNER "meas_runner"']
    assert LIVE_DB not in drop.input

    s = dump.script
    assert dump.argv[:5] == ["docker", "exec", "tradingassistant-db", "sh", "-c"]
    assert dump.timeout == 1234
    assert dump.input is None and dump.env is None
    head, _, tail = s.partition("|")
    assert f"pg_dump -U \"$POSTGRES_USER\" -Fc --no-acl --no-owner -d {LIVE_DB}" in head
    assert ("pg_restore -U \"$POSTGRES_USER\" --no-acl --no-owner --role=meas_runner "
            "--exit-on-error -d bamendjou_meas") in tail
    assert LIVE_DB not in tail
    assert _live_db_mentions(w.calls) == ["pg_dump"]
    assert out == {"database": "bamendjou_meas", "dump_restore": "ok"}
    _assert_no_secret_anywhere(w, out)


@pytest.mark.parametrize("rc", [1, 91, 92, 137])
def test_copy_refuses_on_non_zero_exit(rc):
    w = World(restore_rc=rc)
    with pytest.raises(iso.GuardRefusal, match="dump/restore"):
        iso.copy_live_to_meas(_live(), pg=_pg(w))


def test_copy_refuses_when_drop_create_fails():
    w = World(fail_tags={"meas:drop-create": _fail("ERROR: database is being accessed")})
    with pytest.raises(iso.GuardRefusal):
        iso.copy_live_to_meas(_live(), pg=_pg(w))
    assert len(w.calls) == 1  # no dump after a failed drop/create


def test_copy_refuses_when_docker_cannot_run():
    w = World(raise_on=lambda c: True)
    with pytest.raises(iso.GuardRefusal):
        iso.copy_live_to_meas(_live(), pg=_pg(w))


def test_copy_refuses_when_live_is_the_meas_db():
    w = World()
    with pytest.raises(iso.GuardRefusal):
        iso.copy_live_to_meas(iso.parse_db_url(f"postgresql://u:{LIVE_PW}@h:1/bamendjou_meas"), pg=_pg(w))
    assert w.calls == []


_SH = shutil.which("sh")


@pytest.mark.skipif(_SH is None, reason="needs a POSIX sh")
@pytest.mark.parametrize("dump_rc,restore_rc,expect_ok", [
    (0, 0, True), (1, 0, False), (0, 1, False), (2, 3, False)])
def test_copy_pipeline_enforces_both_exit_codes_in_a_real_shell(tmp_path, dump_rc, restore_rc, expect_ok):
    """Run the generated pipeline under a real sh with stub pg_dump/pg_restore."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    marker = tmp_path / "restored"
    (bindir / "pg_dump").write_text(f"#!/bin/sh\necho DUMPDATA\nexit {dump_rc}\n", newline="\n")
    (bindir / "pg_restore").write_text(
        f"#!/bin/sh\ncat > '{marker.as_posix()}'\nexit {restore_rc}\n", newline="\n")
    for f in bindir.iterdir():
        f.chmod(0o755)
    script = iso.dump_restore_script(LIVE_DB)
    env = {**os.environ, "POSTGRES_USER": "superuser",
           "PATH": str(bindir) + os.pathsep + os.environ.get("PATH", "")}
    proc = subprocess.run([_SH, "-c", script], env=env, capture_output=True, text=True, timeout=60)
    assert (proc.returncode == 0) is expect_ok, (proc.returncode, proc.stderr)
    assert marker.read_text().strip() == "DUMPDATA"


# ── verification (§2.5 (a)-(c)) ──────────────────────────────────────────────

def test_verify_copy_happy_path_records_counts_and_differences():
    w = World()
    w.live_tables["audit_events"] = 9   # live kept writing: recorded, not refused
    w.live_tables["scan_runs"] = 39     # copy above live on a non-ohlcv table: recorded too
    out = iso.verify_copy(_live(), pg=_pg(w))
    assert out["tables"] == ["alembic_version", "audit_events", "ohlcv_daily", "scan_runs"]
    assert out["row_counts"]["audit_events"] == {"copy": 7, "live": 9}
    assert out["row_counts"]["ohlcv_daily"] == {"copy": 1000, "live": 1000}
    assert sorted(out["count_differences"]) == ["audit_events", "scan_runs"]
    assert out["ohlcv_daily"]["copy"] == {"count": 1000, "min": "2009-01-02", "max": "2026-10-13"}
    assert out["alembic_version"] == ["8ee11537abcd"]
    json.dumps(out)  # isolation.json-ready
    _assert_no_secret_anywhere(w, out)


def test_verify_copy_reads_are_select_only_and_copy_before_live():
    w = World()
    iso.verify_copy(_live(), pg=_pg(w))
    for c in w.calls:
        assert _is_select_only_session(c), c.input
        assert c.db in (LIVE_DB, "bamendjou_meas")
    counts = [c.db for c in w.calls if c.tag == "meas:counts"]
    assert counts == ["bamendjou_meas", LIVE_DB]
    assert set(_live_db_mentions(w.calls)) == {"select"}
    count_sql = next(c.input for c in w.calls if c.tag == "meas:counts")
    assert 'FROM public."ohlcv_daily"' in count_sql and 'FROM public."audit_events"' in count_sql


def test_verify_copy_counts_query_quotes_awkward_table_names():
    w = World()
    for d in (w.live_tables, w.copy_tables):
        d['we"ird table'] = 1
    out = iso.verify_copy(_live(), pg=_pg(w))
    assert out["row_counts"]['we"ird table'] == {"copy": 1, "live": 1}
    count_sql = next(c.input for c in w.calls if c.tag == "meas:counts")
    assert 'FROM public."we""ird table"' in count_sql
    assert "'we\"ird table'" in count_sql


@pytest.mark.parametrize("mutate,match", [
    (lambda w: w.copy_tables.pop("scan_runs"), "table set"),
    (lambda w: w.copy_tables.update(extra=1), "table set"),
    (lambda w: w.copy_tables.update(scan_runs=0), "empty in the copy"),
    (lambda w: (w.copy_tables.update(ohlcv_daily=1001), w.copy_ohlcv.update(count=1001)), "ohlcv_daily"),
    (lambda w: w.copy_ohlcv.update(max="2026-10-14"), "ohlcv_daily"),
    (lambda w: w.copy_ohlcv.update(min="2020-10-10"), "ohlcv_daily"),
    (lambda w: w.copy_ohlcv.update(min=None), "ohlcv_daily"),
    (lambda w: w.copy_alembic.__setitem__(0, "other"), "alembic_version"),
    (lambda w: (w.live_alembic.clear(), w.copy_alembic.clear()), "alembic_version"),
    (lambda w: (w.live_tables.pop("ohlcv_daily"), w.copy_tables.pop("ohlcv_daily")), "ohlcv_daily"),
    (lambda w: (w.live_tables.clear(), w.copy_tables.clear()), "no tables"),
])
def test_verify_copy_refusals(mutate, match):
    w = World()
    mutate(w)
    with pytest.raises(iso.GuardRefusal, match=match):
        iso.verify_copy(_live(), pg=_pg(w))


def test_verify_copy_ohlcv_below_live_is_recorded_not_refused():
    w = World()
    w.live_tables["ohlcv_daily"] = 1010
    w.live_ohlcv.update(count=1010, max="2026-10-14")
    out = iso.verify_copy(_live(), pg=_pg(w))
    assert "ohlcv_daily" in out["count_differences"]


def test_verify_copy_refuses_on_psql_failure():
    w = World(fail_tags={"meas:counts": _fail("psql: error: connection refused")})
    with pytest.raises(iso.GuardRefusal):
        iso.verify_copy(_live(), pg=_pg(w))


def test_verify_copy_refuses_on_unparseable_output():
    w = World(fail_tags={"meas:tables": _ok("not json")})
    with pytest.raises(iso.GuardRefusal):
        iso.verify_copy(_live(), pg=_pg(w))


# ── G2 (§2.3) ────────────────────────────────────────────────────────────────

def _g2(w):
    return iso.check_live_db_refused(_live(), MEAS_PW, pg=_pg(w))


def _bad(results):
    return {r.rule for r in results if not r.ok}


def test_g2_passes_on_permission_denied_and_not_superuser():
    w = World()
    results = _g2(w)
    assert _bad(results) == set()
    connect = next(c for c in w.calls if _is_g2_connect(c))
    a = connect.argv
    assert a[:4] == ["docker", "exec", "-e", "PGPASSWORD"]
    assert a[a.index("-d") + 1] == LIVE_DB and a[a.index("-h") + 1] == "127.0.0.1"
    assert "-w" in a
    _assert_no_secret_anywhere(w, [r.to_dict() for r in results])
    assert set(_live_db_mentions(w.calls)) == {"g2_connect"}


def test_g2_accepts_not_allowed_to_connect_message():
    w = World(meas_connect=_fail("FATAL:  role is not allowed to connect to this database"))
    assert _bad(_g2(w)) == set()


def test_g2_refuses_when_meas_runner_connects_to_live():
    w = World(meas_connect=_ok("1\n"))
    results = _g2(w)
    assert _bad(results) == {"g2_live_db_refused"}
    assert "CONNECTED" in next(r.detail for r in results if r.rule == "g2_live_db_refused")


@pytest.mark.parametrize("stderr,phrase", [
    ('psql: error: FATAL:  password authentication failed for user "meas_runner"', "not a permission"),
    ("Error response from daemon: container abc is not running", "not a permission"),
    ("", "not a permission"),
])
def test_g2_refuses_other_connect_failures_with_a_different_message(stderr, phrase):
    w = World(meas_connect=_fail(stderr + f" {MEAS_PW}", 1))
    results = _g2(w)
    assert _bad(results) == {"g2_live_db_refused"}
    detail = next(r.detail for r in results if r.rule == "g2_live_db_refused")
    assert phrase in detail and "permission denied" not in detail.split("(")[0]
    assert MEAS_PW not in detail


def test_g2_refuses_when_docker_cannot_run():
    w = World(raise_on=lambda c: True)
    results = _g2(w)
    assert _bad(results) == {"g2_live_db_refused", "g2_meas_role_not_superuser"}


def test_g2_refuses_when_meas_runner_is_superuser():
    w = World(role_super=True)
    assert _bad(_g2(w)) == {"g2_meas_role_not_superuser"}


def test_g2_refuses_when_role_missing():
    w = World(fail_tags={"meas:g2-role": _ok(json.dumps({"exists": False, "rolsuper": None}))})
    assert _bad(_g2(w)) == {"g2_meas_role_not_superuser"}


def test_enforce_guard_raises_with_rules():
    w = World(role_super=True)
    with pytest.raises(iso.GuardRefusal, match="G2 refused: g2_meas_role_not_superuser"):
        iso.enforce_guard("G2", _g2(w))
    iso.enforce_guard("G2", _g2(World()))


# ── G3 DB probe (§2.3) ───────────────────────────────────────────────────────

def test_g3_passes_when_every_meas_connection_is_on_the_copy():
    w = World()
    r = iso.meas_connections_ok(pg=_pg(w))
    assert r.ok and r.rule == "g3_meas_connections_on_copy"
    (c,) = w.calls
    assert _is_select_only_session(c) and c.db == "postgres"
    assert "usename = 'meas_runner'" in c.input and "GROUP BY" in c.input


@pytest.mark.parametrize("activity", [{}, {"bamendjou_meas": 2, LIVE_DB: 1}, {LIVE_DB: 1}, {"": 1}])
def test_g3_refuses(activity):
    w = World(activity=activity)
    assert not iso.meas_connections_ok(pg=_pg(w)).ok


def test_g3_refuses_on_psql_failure_or_docker_error():
    w = World(fail_tags={"meas:g3-activity": _fail("container down")})
    assert not iso.meas_connections_ok(pg=_pg(w)).ok
    w2 = World(raise_on=lambda c: True)
    assert not iso.meas_connections_ok(pg=_pg(w2)).ok
