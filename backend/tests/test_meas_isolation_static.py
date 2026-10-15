"""MEAS-LIVE-DB-ISOLATION T4 (#284, plan
docs/superpowers/plans/2026-10-13-meas-live-db-isolation-plan.md §2.5, §3, §4 T4).

Two parts:

1. A static proof over ``scripts/meas/isolated_day.py`` that no write statement
   (INSERT / UPDATE / DELETE / TRUNCATE / DROP / ALTER / CREATE / GRANT /
   REVOKE / COPY ... FROM) can reach the live database except setup's single
   ``REVOKE CONNECT ... FROM PUBLIC``. It follows how the module builds SQL:

   - every SQL session is ``PgDocker.superuser_sql`` (directly, or through
     ``select_json``, which always passes ``read_only=True`` so the session
     starts with ``SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY``);
   - every ``read_only=False`` session runs on the maintenance database, and
     each of its statements matches a closed allowlist that targets only the
     meas role / meas database, plus the one REVOKE on the live database;
   - every read-only session's SQL text holds no write keyword;
   - every docker argv the module runs is one of a closed set; the live
     database name reaches argv only in ``pg_dump`` (read) and the G2 connect
     attempt (``-c 'SELECT 1'`` as ``meas_runner``);
   - any SQL-looking write text anywhere else in the module is only a message
     (log line, refusal text, ``what=`` label, the reverse command string).

   SQL the analyser cannot resolve makes the test fail (fail closed), and
   mutation tests prove each rule fires. A dynamic sweep with a recording fake
   docker runner complements the static proof.

2. Unit tests of the pure helpers of ``scripts/meas/verify_isolation_disposable.py``
   (no Docker in CI: importing that script must not need Docker).

All credentials are synthetic. scripts/ is not a package, so modules are
loaded by path, matching the T1-T3 test files.
"""
from __future__ import annotations

import ast
import datetime as dt
import importlib.util
import json
import re
import shlex
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

_MEAS_DIR = Path(__file__).parent.parent.parent / "scripts" / "meas"
_SCRIPT_PATH = _MEAS_DIR / "isolated_day.py"
_VERIFY_PATH = _MEAS_DIR / "verify_isolation_disposable.py"


def _load(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclasses resolve their module by name
    try:
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return mod


iso = _load("meas_isolated_day", _SCRIPT_PATH)
SRC = _SCRIPT_PATH.read_text(encoding="utf-8")

LIVE_PW = "LivePw-Synthetic-123"
MEAS_PW = "MeasPw_synthetic_TOKEN_abcdef0123456789"
LIVE_DB = "TradingAssistantDB"
LIVE_URL = f"postgresql+asyncpg://bamendjou:{LIVE_PW}@localhost:5433/{LIVE_DB}"


# ═════════════════════════════════════════════════════════════════════════════
# Part 1: static analyser
# ═════════════════════════════════════════════════════════════════════════════

WRITE_WORD_RE = re.compile(r"\b(INSERT|UPDATE|DELETE|TRUNCATE|DROP|ALTER|CREATE|GRANT|REVOKE|COPY)\b",
                           re.IGNORECASE)
# SQL-shaped write text (uppercase keyword + an SQL object word): the catch-all.
SQL_WRITE_TEXT_RE = re.compile(
    r"\b(INSERT\s+INTO|UPDATE\s+\S+\s+SET|DELETE\s+FROM|TRUNCATE\b|DROP\s+(DATABASE|TABLE|ROLE|SCHEMA|OWNED)"
    r"|ALTER\s+(ROLE|DATABASE|TABLE|SCHEMA|DEFAULT)|CREATE\s+(ROLE|DATABASE|TABLE|SCHEMA|USER)"
    r"|GRANT\s|REVOKE\s|COPY\s)")
COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)

SQL_ENTRY_METHODS = ("superuser_sql", "select_json")

# The closed allowlist of statements a read_only=False (maintenance-DB) session
# may hold. ``{expr}`` is the f-string interpolation, by its source text.
ALLOWED_WRITE_STATEMENTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("role", re.compile(r"^\{verb\} ROLE \{MEAS_USER\} WITH \{MEAS_ROLE_ATTRIBUTES\} "
                        r"PASSWORD \{quote_literal\(password\)\}$")),
    ("alter-db-owner", re.compile(r"^ALTER DATABASE \{quote_ident\(MEAS_DBNAME\)\} "
                                  r"OWNER TO \{quote_ident\(MEAS_USER\)\}$")),
    ("create-db", re.compile(r"^CREATE DATABASE \{quote_ident\(MEAS_DBNAME\)\} OWNER \{quote_ident\(MEAS_USER\)\}$")),
    ("drop-db", re.compile(r"^DROP DATABASE IF EXISTS \{quote_ident\(MEAS_DBNAME\)\} WITH \(FORCE\)$")),
    ("revoke", re.compile(r"^REVOKE CONNECT ON DATABASE \{quote_ident\(live\.dbname\)\} FROM PUBLIC$")),
)

# Every docker argv expression passed to ``<pg>.run(...)`` in the module.
ALLOWED_RUN_ARGV = {
    "self.superuser_argv(dbname)",                      # superuser psql, SQL on stdin
    "pg.meas_runner_connect_argv(live.dbname)",         # G2 connect attempt, -c 'SELECT 1'
    "[pg.docker, 'exec', pg.container, 'sh', '-c', dump_restore_script(live.dbname)]",  # pg_dump | pg_restore
    "[pg.docker, 'info']",
    "[pg.docker, 'inspect', '-f', fmt, pg.container]",
}

# Calls whose string arguments are messages, never SQL that is executed.
MESSAGE_CALLS = {"GuardRefusal", "emit", "log", "say", "print", "GuardResult", "append"}


class Unresolved(AssertionError):
    pass


class Analysis:
    """Parse one source text; collect SQL sessions, docker argv and write-looking text."""

    def __init__(self, source: str):
        self.tree = ast.parse(source)
        self.parent: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(self.tree):
            for child in ast.iter_child_nodes(node):
                self.parent[child] = node
        self.docstrings = self._docstring_nodes()

    # ── tree helpers ─────────────────────────────────────────────────────────
    def _docstring_nodes(self) -> set[ast.AST]:
        out: set[ast.AST] = set()
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                body = node.body
                if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                        and isinstance(body[0].value.value, str):
                    out.add(body[0].value)
        return out

    def ancestors(self, node: ast.AST):
        cur = self.parent.get(node)
        while cur is not None:
            yield cur
            cur = self.parent.get(cur)

    def scopes(self, node: ast.AST) -> list[ast.AST]:
        """Enclosing functions, outermost first."""
        fns = [a for a in self.ancestors(node) if isinstance(a, (ast.FunctionDef, ast.AsyncFunctionDef))]
        return list(reversed(fns))

    def enclosing_class(self, node: ast.AST) -> str | None:
        for a in self.ancestors(node):
            if isinstance(a, ast.ClassDef):
                return a.name
        return None

    def function(self, name: str, cls: str | None = None) -> ast.FunctionDef:
        for node in ast.walk(self.tree):
            if isinstance(node, ast.FunctionDef) and node.name == name and self.enclosing_class(node) == cls:
                return node
        raise AssertionError(f"function {cls + '.' if cls else ''}{name} not found")

    # ── SQL resolution ───────────────────────────────────────────────────────
    def resolve(self, node: ast.AST, scopes: list[ast.AST], depth: int = 0) -> list[tuple[str, Any]]:
        """Flatten a SQL expression to [("lit", Constant node) | ("expr", source)]."""
        if depth > 8:
            raise Unresolved("resolution too deep")
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [("lit", node)]
        if isinstance(node, ast.JoinedStr):
            out: list[tuple[str, Any]] = []
            for v in node.values:
                if isinstance(v, ast.Constant):
                    out.append(("lit", v))
                elif isinstance(v, ast.FormattedValue):
                    out.append(("expr", ast.unparse(v.value)))
                else:
                    raise Unresolved(ast.unparse(v))
            return out
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return self.resolve(node.left, scopes, depth + 1) + self.resolve(node.right, scopes, depth + 1)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "join" \
                and len(node.args) == 1 and isinstance(node.args[0], (ast.GeneratorExp, ast.ListComp)):
            # "<sep>".join(<template> for ...): template + separator, all literal parts checked
            return (self.resolve(node.func.value, scopes, depth + 1)
                    + self.resolve(node.args[0].elt, scopes, depth + 1))
        if isinstance(node, ast.Name):
            for i in range(len(scopes) - 1, -1, -1):
                fn = scopes[i]
                values = [a.value for a in ast.walk(fn) if isinstance(a, ast.Assign)
                          and any(isinstance(t, ast.Name) and t.id == node.id for t in a.targets)]
                if values:
                    return [f for v in values for f in self.resolve(v, scopes[: i + 1], depth + 1)]
                params = [a.arg for a in fn.args.args + fn.args.kwonlyargs]
                if node.id in params:
                    if i == 0:
                        raise Unresolved(f"parameter {node.id} of top-level function {fn.name}")
                    idx = fn.args.args and [a.arg for a in fn.args.args].index(node.id) \
                        if node.id in [a.arg for a in fn.args.args] else None
                    calls = [c for c in ast.walk(scopes[i - 1]) if isinstance(c, ast.Call)
                             and isinstance(c.func, ast.Name) and c.func.id == fn.name]
                    if not calls:
                        raise Unresolved(f"no call of nested function {fn.name}")
                    out = []
                    for c in calls:
                        arg = next((k.value for k in c.keywords if k.arg == node.id), None)
                        if arg is None and idx is not None and idx < len(c.args):
                            arg = c.args[idx]
                        if arg is None:
                            raise Unresolved(f"cannot bind {node.id} in a call of {fn.name}")
                        out += self.resolve(arg, scopes[:i], depth + 1)
                    return out
            raise Unresolved(f"name {node.id} has no assignment in scope")
        raise Unresolved(ast.unparse(node))

    # ── SQL sessions ─────────────────────────────────────────────────────────
    def sql_calls(self) -> list[dict[str, Any]]:
        """Every superuser_sql / select_json call outside the PgDocker plumbing."""
        out = []
        for node in ast.walk(self.tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in SQL_ENTRY_METHODS):
                continue
            if self.enclosing_class(node) == "PgDocker":
                continue   # plumbing, checked structurally
            kw = {k.arg: k.value for k in node.keywords}
            sql_node = node.args[0] if node.args else kw.get("sql")
            if sql_node is None:
                raise Unresolved(f"{node.func.attr} call without SQL at line {node.lineno}")
            if node.func.attr == "select_json":
                read_only: Any = True
            else:
                ro = kw.get("read_only")
                if not (isinstance(ro, ast.Constant) and isinstance(ro.value, bool)):
                    raise Unresolved(f"superuser_sql at line {node.lineno}: read_only is not a literal bool")
                read_only = ro.value
            scopes = self.scopes(node)
            frags = self.resolve(sql_node, scopes)
            out.append({
                "node": node, "line": node.lineno, "method": node.func.attr, "read_only": read_only,
                "dbname": ast.unparse(kw["dbname"]) if "dbname" in kw else None,
                "frags": frags, "function": scopes[0].name if scopes else None,
            })
        return out

    @staticmethod
    def template(frags: list[tuple[str, Any]]) -> str:
        return "".join(f[1].value if f[0] == "lit" else "{" + f[1] + "}" for f in frags)

    @staticmethod
    def statements(template: str) -> list[str]:
        text = COMMENT_RE.sub(" ", template)
        return [" ".join(s.split()) for s in text.split(";") if s.strip()]

    def run_argv(self) -> list[str]:
        """Source of every argv given to ``<pg>.run(...)`` (pg / deps.pg / self in PgDocker)."""
        out = []
        for node in ast.walk(self.tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "run"):
                continue
            owner = ast.unparse(node.func.value)
            if owner in ("pg", "deps.pg", "self.deps.pg") or (owner == "self"
                                                                and self.enclosing_class(node) == "PgDocker"):
                argv = node.args[0]
                if isinstance(argv, ast.Name):
                    vals = self.resolve_value(argv, self.scopes(node))
                    out += vals
                else:
                    out.append(ast.unparse(argv))
        return out

    def resolve_value(self, name: ast.Name, scopes: list[ast.AST]) -> list[str]:
        for fn in reversed(scopes):
            vals = [ast.unparse(a.value) for a in ast.walk(fn) if isinstance(a, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == name.id for t in a.targets)]
            if vals:
                return vals
        raise Unresolved(f"argv name {name.id} unresolved")

    def string_constants(self):
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node not in self.docstrings:
                yield node


def violations(source: str) -> list[str]:
    """Every rule of the static proof; returns human-readable violations (empty = proven)."""
    a = Analysis(source)
    found: list[str] = []
    try:
        calls = a.sql_calls()
    except Unresolved as exc:
        return [f"unresolved SQL: {exc}"]

    accounted: set[int] = set()
    revokes = 0
    for c in calls:
        tpl = a.template(c["frags"])
        for kind, val in c["frags"]:
            if kind == "lit":
                accounted.add(id(val))
        if c["read_only"]:
            lits = COMMENT_RE.sub(" ", "".join(v.value for k, v in c["frags"] if k == "lit"))
            m = WRITE_WORD_RE.search(lits)
            if m:
                found.append(f"line {c['line']}: read-only session holds write keyword {m.group(0)!r}")
            if "SELECT" not in lits.upper():
                found.append(f"line {c['line']}: read-only session without SELECT")
            continue
        # read_only=False: only on the maintenance database
        if c["dbname"] is None or not c["dbname"].endswith("maintenance_db"):
            found.append(f"line {c['line']}: write session on dbname={c['dbname']} (must be the maintenance DB)")
        for stmt in a.statements(tpl):
            kinds = [k for k, rx in ALLOWED_WRITE_STATEMENTS if rx.match(stmt)]
            if not kinds:
                found.append(f"line {c['line']}: write statement not in the allowlist: {stmt!r}")
                continue
            if kinds[0] == "revoke":
                revokes += 1
                if c["function"] != "setup":
                    found.append(f"line {c['line']}: REVOKE on the live database outside setup")
        for kind, val in c["frags"]:
            if kind == "expr" and re.search(r"\blive\b", val) and "REVOKE CONNECT ON DATABASE" not in tpl:
                found.append(f"line {c['line']}: live identity {val!r} interpolated into a write session")
        # every function that writes checks the live identity first (live != meas names)
        fn = a.scopes(c["node"])[0] if a.scopes(c["node"]) else None
        guard_lines = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call)
                       and isinstance(n.func, ast.Name) and n.func.id == "_check_live_identity"] if fn else []
        if not guard_lines or min(guard_lines) > c["line"]:
            found.append(f"line {c['line']}: write session in {c['function']} without a prior _check_live_identity")
    if revokes != 1:
        found.append(f"expected exactly one REVOKE on the live database, found {revokes}")

    # docker argv: a closed set
    try:
        for argv in a.run_argv():
            if argv not in ALLOWED_RUN_ARGV:
                found.append(f"docker argv not in the allowlist: {argv}")
    except Unresolved as exc:
        found.append(f"unresolved docker argv: {exc}")

    # catch-all: SQL-shaped write text outside an accounted write session is a message only
    for const in a.string_constants():
        if not SQL_WRITE_TEXT_RE.search(const.value) or id(const) in accounted:
            continue
        if not _is_message_context(a, const):
            found.append(f"line {const.lineno}: SQL-shaped write text outside a checked session: "
                         f"{const.value.strip()[:80]!r}")
    return found


def _is_message_context(a: Analysis, const: ast.Constant) -> bool:
    for anc in a.ancestors(const):
        if isinstance(anc, ast.keyword) and anc.arg in ("what", "help", "description"):
            return True
        if isinstance(anc, ast.Call):
            fn = anc.func
            name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else None
            if name in MESSAGE_CALLS:
                return True
        if isinstance(anc, ast.FunctionDef) and anc.name == "reverse_revoke_command":
            return True
        if isinstance(anc, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SETUP_WARNING"
                                               for t in anc.targets):
            return True
    return False


# ── the proof over the real module ───────────────────────────────────────────

def test_isolated_day_sends_no_write_to_the_live_database():
    assert violations(SRC) == []


def test_the_analyser_sees_every_session_kind():
    """Guard against a vacuous pass: the analyser must find the module's sessions."""
    calls = Analysis(SRC).sql_calls()
    tags = {t for c in calls for t in re.findall(r"meas:([a-z0-9-]+)", Analysis.template(c["frags"]))}
    assert {"setup-precheck", "revoke", "live-connect", "drop-create", "tables", "counts", "ohlcv",
            "alembic", "g2-role", "g3-activity", "create-db", "alter-db-owner", "drop"} <= tags
    writes = [c for c in calls if not c["read_only"]]
    reads = [c for c in calls if c["read_only"]]
    assert len(writes) >= 5 and len(reads) >= 5   # verify_copy's 4 reads share one call site (both)


def test_select_json_is_always_a_read_only_session():
    a = Analysis(SRC)
    sj = a.function("select_json", "PgDocker")
    inner = [n for n in ast.walk(sj) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "superuser_sql"]
    assert len(inner) == 1
    kw = {k.arg: k.value for k in inner[0].keywords}
    assert isinstance(kw["read_only"], ast.Constant) and kw["read_only"].value is True
    su = a.function("superuser_sql", "PgDocker")
    src = ast.unparse(su)
    assert "text = (READ_ONLY_PREFIX if read_only else '') + sql" in src
    assert "input=text" in src
    assert iso.READ_ONLY_PREFIX == "SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY;\n"
    # superuser_argv is the only psql shell, used only by superuser_sql
    users = [n for n in ast.walk(a.tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "superuser_argv"]
    assert [a.scopes(u)[-1].name for u in users] == ["superuser_sql"]


def test_db_clients_appear_only_in_their_argv_builders():
    a = Analysis(SRC)
    owners: dict[str, set[str]] = {}
    for const in a.string_constants():
        for tool in ("psql", "pg_dump", "pg_restore"):
            if re.search(rf"\b{tool}\b", const.value):
                scopes = a.scopes(const)
                fn = scopes[-1].name if scopes else "<module>"
                if not _is_message_context(a, const):
                    owners.setdefault(tool, set()).add(fn)
    assert owners == {
        "psql": {"superuser_argv", "meas_runner_connect_argv"},
        "pg_dump": {"dump_restore_script"},
        "pg_restore": {"dump_restore_script"},
    }


def test_dump_restore_reads_live_and_writes_only_the_copy():
    a = Analysis(SRC)
    fn = a.function("dump_restore_script")
    live_strs, restore_strs = [], []
    for node in ast.walk(fn):
        if isinstance(node, ast.JoinedStr):
            exprs = [ast.unparse(v.value) for v in node.values if isinstance(v, ast.FormattedValue)]
            head = node.values[0].value if node.values and isinstance(node.values[0], ast.Constant) else ""
            if any("live_dbname" in e for e in exprs):
                live_strs.append(head)
            if head.startswith("pg_restore"):
                restore_strs.append((head, exprs))
    assert live_strs == ["pg_dump -U \"$POSTGRES_USER\" -Fc --no-acl --no-owner -d "]
    assert len(restore_strs) == 1 and "MEAS_DBNAME" in restore_strs[0][1]
    script = iso.dump_restore_script(LIVE_DB)
    dump_line = next(ln for ln in script.splitlines() if "pg_dump" in ln and LIVE_DB in ln)
    assert dump_line.count(LIVE_DB) == 1
    restore_part = dump_line.split("|", 1)[1]
    assert LIVE_DB not in restore_part and f"-d {iso.MEAS_DBNAME}" in restore_part
    assert "--clean" not in script and "--create" not in script


def test_g2_connect_attempt_only_selects():
    argv = iso.PgDocker(container="c").meas_runner_connect_argv(LIVE_DB)
    assert argv[argv.index("-U") + 1] == iso.MEAS_USER
    assert argv[argv.index("-c") + 1] == "SELECT 1"
    assert argv.count(LIVE_DB) == 1


# ── mutation tests: each rule fires ──────────────────────────────────────────

_MUTATIONS = {
    "write in a live read session": (
        "both(\"/* meas:tables */ SELECT coalesce(",
        "both(\"/* meas:tables */ DELETE FROM ohlcv_daily; SELECT coalesce(",
    ),
    "write session on the live database": (
        "dbname=pg.maintenance_db, read_only=False, what='REVOKE CONNECT on the live database'",
        "dbname=live.dbname, read_only=False, what='REVOKE CONNECT on the live database'",
    ),
    "drop the live database": (
        r"DROP DATABASE IF EXISTS {quote_ident(MEAS_DBNAME)} WITH (FORCE);\nCREATE",
        r"DROP DATABASE IF EXISTS {quote_ident(live.dbname)} WITH (FORCE);\nCREATE",
    ),
    "grant instead of revoke": (
        r"REVOKE CONNECT ON DATABASE {quote_ident(live.dbname)} FROM PUBLIC;\n'",
        r"GRANT CONNECT ON DATABASE {quote_ident(live.dbname)} TO PUBLIC;\n'",
    ),
    "non-literal read_only": (
        "dbname=pg.maintenance_db, read_only=False, what=f'drop/create {MEAS_DBNAME}'",
        "dbname=pg.maintenance_db, read_only=bool(0), what=f'drop/create {MEAS_DBNAME}'",
    ),
    "a new docker argv": (
        "res = pg.run(argv, what='dump/restore', timeout=pg.copy_timeout)",
        "res = pg.run(argv, what='dump/restore', timeout=pg.copy_timeout)\n"
        "    pg.run([pg.docker, 'exec', pg.container, 'psql', '-d', live.dbname, '-c', 'TRUNCATE x'], what='x')",
    ),
    "raw SQL text outside a session": (
        "DB_CONTAINER = 'tradingassistant-db'",
        "DB_CONTAINER = 'tradingassistant-db'\nSNEAKY = 'DELETE FROM ohlcv_daily'",
    ),
    "a second revoke": (
        "    emit(f'REVOKE CONNECT ON DATABASE {quote_ident(live.dbname)} FROM PUBLIC done. To undo: {reverse}')",
        "    pg.superuser_sql(f'/* meas:revoke */ REVOKE CONNECT ON DATABASE {quote_ident(live.dbname)} "
        r"FROM PUBLIC;\n', dbname=pg.maintenance_db, read_only=False, what='again')" "\n"
        "    emit(f'REVOKE CONNECT ON DATABASE {quote_ident(live.dbname)} FROM PUBLIC done. To undo: {reverse}')",
    ),
    "a write session without the live-identity check": (
        "    _check_live_identity(live, pg)\n    pg.superuser_sql(f'/* meas:drop-create */",
        "    pg.superuser_sql(f'/* meas:drop-create */",
    ),
}


def _mutate(old: str, new: str) -> str:
    # Mutations are applied to the ast.unparse form (stable quoting).
    src = ast.unparse(ast.parse(SRC))
    assert old in src, f"mutation anchor not found: {old[:60]}"
    return src.replace(old, new, 1)


def test_unparsed_source_is_still_proven():
    assert violations(ast.unparse(ast.parse(SRC))) == []


@pytest.mark.parametrize("name", sorted(_MUTATIONS))
def test_each_mutation_is_detected(name):
    old, new = _MUTATIONS[name]
    assert violations(_mutate(old, new)), f"mutation {name!r} was not detected"


# ── dynamic sweep with a recording fake docker ───────────────────────────────

class RecordingDocker:
    """Answers the module's SQL by its ``/* meas:<tag> */`` and records every call."""

    ANSWERS = {
        "setup-precheck": {"live_db_exists": True, "live_user_super": True, "live_user_owner": True,
                           "role_exists": False, "meas_db_exists": False},
        "live-connect": {"one": 1, "live_user_can_connect": True},
        "g2-role": {"exists": True, "rolsuper": False},
        "tables": ["alembic_version", "ohlcv_daily"],
        "counts": {"alembic_version": 1, "ohlcv_daily": 10},
        "ohlcv": {"count": 10, "min": "2020-01-02", "max": "2026-10-13"},
        "alembic": ["fake0001"],
        "g3-activity": {"bamendjou_meas": 1},
    }

    def __init__(self):
        self.calls: list[dict[str, Any]] = []

    def __call__(self, argv, *, input=None, env=None, timeout=None):
        self.calls.append({"argv": list(argv), "input": input})
        if "PGPASSWORD" in argv:
            return iso.CmdResult(2, "", f'FATAL:  permission denied for database "{LIVE_DB}"\n')
        if input is None:
            return iso.CmdResult(0, "", "")
        m = re.search(r"/\* meas:([a-z0-9-]+) \*/", input)
        tag = m.group(1) if m else ""
        if tag in self.ANSWERS:
            return iso.CmdResult(0, json.dumps(self.ANSWERS[tag]) + "\n", "")
        return iso.CmdResult(0, "", "")


def _session_db(argv: list[str]) -> str | None:
    if argv[-3:-1] == ["sh", "-c"] and "psql" in argv[-1]:
        words = shlex.split(argv[-1])
        return words[words.index("-d") + 1]
    return None


def test_dynamic_sweep_only_reads_the_live_database(tmp_path):
    rec = RecordingDocker()
    pg = iso.PgDocker(container="fake", runner=rec)
    live = iso.parse_db_url(LIVE_URL)
    iso.setup(live, tmp_path / "s.secret", pg=pg, log=lambda _l: None,
              restrict_acl=lambda _p: None, token_factory=lambda: MEAS_PW)
    iso.copy_live_to_meas(live, pg=pg)
    iso.verify_copy(live, pg=pg)
    iso.check_live_db_refused(live, MEAS_PW, pg=pg)
    iso.meas_connections_ok(pg=pg)

    live_sessions = maint_writes = 0
    for call in rec.calls:
        argv, stdin = call["argv"], call["input"] or ""
        db = _session_db(argv)
        if db == LIVE_DB:
            live_sessions += 1
            assert stdin.startswith(iso.READ_ONLY_PREFIX)
            assert not WRITE_WORD_RE.search(COMMENT_RE.sub(" ", stdin[len(iso.READ_ONLY_PREFIX):]))
        elif db == iso.MEAS_DBNAME:
            assert stdin.startswith(iso.READ_ONLY_PREFIX)      # verify_copy reads the copy too
        elif db is not None:
            assert db == iso.MAINTENANCE_DB
            body = COMMENT_RE.sub(" ", stdin)
            if not stdin.startswith(iso.READ_ONLY_PREFIX) and LIVE_DB in body:
                maint_writes += 1
                assert " ".join(body.split()) == f'REVOKE CONNECT ON DATABASE "{LIVE_DB}" FROM PUBLIC;'
        elif "PGPASSWORD" in argv:
            assert argv[argv.index("-c") + 1] == "SELECT 1"
        else:
            script = argv[-1]
            assert "pg_dump" in script
            assert script.count(LIVE_DB) == 1
            assert re.search(rf"pg_dump [^|]*-d {LIVE_DB}", script)
    assert live_sessions >= 5
    assert maint_writes == 1


# ═════════════════════════════════════════════════════════════════════════════
# Part 2: verify_isolation_disposable.py pure helpers (no Docker)
# ═════════════════════════════════════════════════════════════════════════════

class _LazyVerify:
    """Loaded on first use, so Part 1 runs even if the script is broken."""

    def __getattr__(self, name: str):
        return getattr(_load("meas_verify_isolation_disposable", _VERIFY_PATH), name)


ver = _LazyVerify()


def test_verify_script_imports_without_docker_and_reuses_isolated_day():
    assert ver.iso is iso
    assert ver.IMAGE == "postgres:15-alpine"
    assert ver.FAKE_LIVE_DB != iso.MEAS_DBNAME


def test_container_names_are_random_throwaways():
    a, b = ver.new_container_name(), ver.new_container_name()
    assert a != b
    for n in (a, b):
        assert re.fullmatch(r"meas-verify-[0-9a-f]{12}", n)
        ver.check_container_name(n)


@pytest.mark.parametrize("bad", ["tradingassistant-db", "TradingAssistant-DB", "postgres", "meas-verify-",
                                 "meas-verify-XYZ", "meas-verify-abc;rm", "sonos-network-db", ""])
def test_container_name_refuses_anything_else(bad):
    with pytest.raises(iso.GuardRefusal):
        ver.check_container_name(bad)


def test_docker_run_argv_is_throwaway_and_secret_free():
    name = "meas-verify-0123456789ab"
    argv = ver.docker_run_argv(name)
    assert argv[:2] == ["docker", "run"]
    assert "--rm" in argv and argv[argv.index("--pull") + 1] == "never"
    assert argv[argv.index("--name") + 1] == name
    assert argv[argv.index("-p") + 1] == "127.0.0.1::5432"
    assert argv[-1] == "postgres:15-alpine"
    envs = [argv[i + 1] for i, v in enumerate(argv) if v == "-e"]
    assert "POSTGRES_PASSWORD" in envs                       # value from the docker CLI env only
    assert f"POSTGRES_DB={ver.FAKE_LIVE_DB}" in envs and "POSTGRES_USER=postgres" in envs
    assert not any(e.startswith("POSTGRES_PASSWORD=") for e in envs)
    with pytest.raises(iso.GuardRefusal):
        ver.docker_run_argv(iso.DB_CONTAINER)
    with pytest.raises(iso.GuardRefusal):
        ver.docker_stop_argv(iso.DB_CONTAINER)
    assert ver.docker_stop_argv(name)[-1] == name


def test_docker_env_carries_the_password_only_in_env():
    env = ver.docker_env({"PATH": "x", "POSTGRES_PASSWORD": "old"}, "pw-123")
    assert env["POSTGRES_PASSWORD"] == "pw-123" and env["PATH"] == "x"


@pytest.mark.parametrize("text,port", [("127.0.0.1:55012\n", 55012),
                                       ("127.0.0.1:49153\r\n", 49153)])
def test_parse_port_output(text, port):
    assert ver.parse_port_output(text) == port


@pytest.mark.parametrize("text", ["", "0.0.0.0:5433\n", "garbage", "127.0.0.1:abc"])
def test_parse_port_output_refuses(text):
    with pytest.raises(iso.GuardRefusal):
        ver.parse_port_output(text)


def test_cutoff_matches_the_tag_rule():
    assert ver.cutoff_for(dt.date(2026, 10, 14), 6) == dt.date(2026, 10, 14) - dt.timedelta(days=6 * 365)


def test_expected_seed_rows_counts_weekdays():
    # 2026-10-12 (Mon) .. 2026-10-18 (Sun): 5 weekdays x 3 symbols
    assert ver.expected_seed_rows(dt.date(2026, 10, 12), dt.date(2026, 10, 18), 3) == 15
    assert ver.expected_seed_rows(dt.date(2026, 10, 17), dt.date(2026, 10, 18), 3) == 0


def test_seed_sql_shape():
    sql = ver.seed_sql(("VRFA", "VRFB"), dt.date(2009, 10, 1), dt.date(2026, 10, 14), "fake0001")
    assert "INSERT INTO ohlcv_daily" in sql and "'VRFA'" in sql and "'VRFB'" in sql
    assert "DATE '2009-10-01'" in sql and "DATE '2026-10-14'" in sql
    assert "isodow" in sql and "INSERT INTO alembic_version" in sql and "'fake0001'" in sql


def test_fake_live_url_identity():
    url = ver.fake_live_url(55012, "p@ss/w:rd")
    live = iso.parse_db_url(url)
    assert live.identity() == {"host": "127.0.0.1", "port": 55012, "dbname": ver.FAKE_LIVE_DB, "user": "postgres"}
    assert live.password == "p@ss/w:rd"
    assert url.startswith("postgresql+asyncpg://")


def test_tmp_checkout_must_be_outside_the_repo(tmp_path):
    ver.check_tmp_path(tmp_path / "meas-verify-0123456789ab", repo_root=ver.REPO_ROOT)
    with pytest.raises(iso.GuardRefusal):
        ver.check_tmp_path(ver.REPO_ROOT / ".claude" / "meas-verify-0123456789ab", repo_root=ver.REPO_ROOT)
    with pytest.raises(iso.GuardRefusal):
        ver.check_tmp_path(tmp_path / "other-name", repo_root=ver.REPO_ROOT)


def test_parse_markers():
    out = "noise\nPRUNED=42\nHOLDING=bamendjou_meas|meas_runner\r\n"
    assert ver.parse_marker(out, "PRUNED") == "42"
    assert ver.parse_marker(out, "HOLDING") == "bamendjou_meas|meas_runner"
    assert ver.parse_marker(out, "MISSING") is None


def test_child_code_snippets_compile_and_use_the_tag_code():
    for code in (ver.PRUNE_CODE, ver.HOLD_CODE, ver.CONNECT_CODE, ver.DDL_CODE):
        compile(code, "<snippet>", "exec")
    assert "from app.services.ingestion_job import _prune_old_rows" in ver.PRUNE_CODE
    assert f"_prune_old_rows({ver.PRUNE_YEARS})" in ver.PRUNE_CODE and ver.PRUNE_YEARS == 6
    assert "from app.models.ohlcv_daily import OhlcvDailyModel" in ver.DDL_CODE
    for code in (ver.PRUNE_CODE, ver.HOLD_CODE, ver.CONNECT_CODE):
        assert "APP_INSIDE_CWD=" in code      # proves the tag's app package was imported


def test_g1_matrix_passes_the_valid_config_and_refuses_each_violation(tmp_path):
    live = iso.parse_db_url(LIVE_URL)
    meas = iso.parse_db_url(iso.build_meas_url(live, MEAS_PW))
    checkout = tmp_path / "meas-verify-0123456789ab"
    checkout.mkdir()
    checks = ver.g1_matrix(live, meas, checkout=checkout, repo_root=ver.REPO_ROOT)
    names = [c.name for c in checks]
    assert names[0].startswith("G1 passes")
    for label in ("same dbname", "wrong meas user", "port 8000", "meas checkout inside the repo"):
        assert any(label in n for n in names), label
    assert all(c.ok for c in checks), [c for c in checks if not c.ok]


def test_g1_matrix_reports_a_guard_that_fails_to_refuse(tmp_path, monkeypatch):
    live = iso.parse_db_url(LIVE_URL)
    meas = iso.parse_db_url(iso.build_meas_url(live, MEAS_PW))
    checkout = tmp_path / "meas-verify-0123456789ab"
    checkout.mkdir()
    monkeypatch.setattr(ver.iso, "enforce_g1", lambda results: None)   # a broken guard
    checks = ver.g1_matrix(live, meas, checkout=checkout, repo_root=ver.REPO_ROOT)
    assert any(not c.ok for c in checks if "refuses" in c.name)


def test_report_is_counts_and_verdicts_only():
    checks = [ver.Check("copy pruned", True, "older rows 0"), ver.Check("live unchanged", False, "count 3 != 4")]
    facts = {"tag_commit": "61a03e4", "python": "3.11.9", "postgres": "15.8", "live_rows_before": 4}
    text = ver.render_report(checks, facts, date=dt.date(2026, 10, 14), secrets=["pw-xyz"])
    assert "PASS" in text and "FAIL" in text and "copy pruned" in text and "61a03e4" in text
    assert "1/2 checks passed" in text
    assert ver.exit_code_for(checks) == 1
    assert ver.exit_code_for(checks[:1]) == 0
    with pytest.raises(iso.GuardRefusal):
        ver.render_report([ver.Check("x", True, "pw-xyz leaked")], facts, date=dt.date(2026, 10, 14),
                          secrets=["pw-xyz"])
    with pytest.raises(iso.GuardRefusal):
        ver.render_report([ver.Check("x", True, r"C:\Users\someone\x")], facts, date=dt.date(2026, 10, 14),
                          secrets=[])
