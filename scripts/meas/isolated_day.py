"""Isolated MEAS day orchestrator: config layer and the G1 config guard.

Plan: docs/superpowers/plans/2026-10-13-meas-live-db-isolation-plan.md (#230).
This module is ticket T1 (#281): §2.2 fixed names, §2.3 G1, §2.4 the files the
orchestrator writes into the meas checkout, the child environment, the secret
file and the confidence-cache seed/carry-over (§2.4 [v3 R2-1], §2.7). Ticket T2
(#282) adds the DB layer at the end of the file: one-time ``setup`` (§2.3 G2),
the per-run copy and its verification (§2.5), the G2 probe and the G3 DB probe.
Ticket T3 (#283) adds the run sequence on top of it (§2.6, G3 process identity,
the evidence copy and ``isolation.json``) and the CLI: ``setup`` / ``check`` /
``run`` / ``cleanup``.

Rules for everything in here:
- stdlib + PyYAML only; never import ``app.*`` (the frozen code must not be
  loaded into the orchestrator).
- Every OS-specific or side-effecting call (listener enumeration, TCP probes,
  icacls, subprocess) is an injectable callable so it can be faked in tests
  (CI is Linux; the real orchestrator runs on Windows).
- No password ever leaves this layer in a log line, an argv list, a guard
  result or anything meant for ``isolation.json``: ``DbUrl`` hides it in
  repr/str, guard details never include it, and ``redact`` /
  ``assert_no_secret`` are the last line before anything is emitted.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import getpass
import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import quote, quote_plus, unquote, urlsplit

import yaml

# ── §2.2 fixed names ─────────────────────────────────────────────────────────

TAG = "meas-freeze-1"
MEAS_DBNAME = "bamendjou_meas"
MEAS_USER = "meas_runner"
MEAS_PORT = 8100
LIVE_PORT = 8000
IBKR_PORTS: tuple[int, ...] = (5000, 7499)
IBKR_PROBE_HOSTS: tuple[str, ...] = ("127.0.0.1", "::1")

REPO_ROOT = Path(__file__).resolve().parents[2]
JOBS_DIR = Path.home() / "bamendjou-jobs"
MEAS_CHECKOUT = JOBS_DIR / TAG
SECRET_FILE = JOBS_DIR / "meas_db.secret"

SETTINGS_REL = Path("backend") / "config" / "settings.yaml"
CONFIDENCE_CACHE_REL = Path("backend") / "data" / "confidence_cache.db"

# Keys copied from the live .env into the meas .env (market data, unchanged
# from days 1-2). Never Telegram / Gmail.
MARKET_DATA_ENV_KEYS: tuple[str, ...] = ("TRADIER_API_TOKEN", "TRADIER_BASE_URL", "TIINGO_API_TOKEN")
MEAS_MARKER_KEY = "BAMENDJOU_MEAS_ISOLATED"
MEAS_DOTENV_KEYS: tuple[str, ...] = ("DATABASE_URL", *MARKET_DATA_ENV_KEYS, MEAS_MARKER_KEY)

# Child environment: every key matching this is removed (case-insensitively,
# Windows env keys are case-insensitive) before the meas keys are added.
# ``PG`` covers every libpq variable (PGPASSWORD, PGHOST, PGPORT, PGUSER,
# PGDATABASE, PGSERVICE, PGPASSFILE, ...): asyncpg reads them when a URL part is
# missing, and the DB layer (T2) puts PGPASSWORD into docker's subprocess env.
_CHILD_ENV_STRIP_RE = re.compile(
    r"^(?:DATABASE_URL$|BAMENDJOU_|TRADIER_|TIINGO_|ALPACA_|TASTY|IBKR_|POSTGRES_|PG)", re.IGNORECASE
)
_NOTIFICATION_KEY_RE = re.compile(r"TELEGRAM|GMAIL", re.IGNORECASE)


class GuardRefusal(RuntimeError):
    """A guard refused: the run must stop, exit non-zero, live untouched."""


# ── .env reading ─────────────────────────────────────────────────────────────

def read_env_file(path: Path | str) -> dict[str, str]:
    """Parse a dotenv file into {key: value}. Values are secrets: never log them."""
    env: dict[str, str] = {}
    text = Path(path).read_text(encoding="utf-8-sig")
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if value[:1] in ("'", '"'):
            q = value[0]
            end = value.find(q, 1)
            val = value[1:] if end == -1 else value[1:end]
            if q == '"':
                val = val.replace("\\n", "\n").replace('\\"', '"')
        else:
            val = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        env[key] = val
    return env


# ── DATABASE_URL parsing ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class DbUrl:
    scheme: str
    user: str
    password: str = field(repr=False)
    host: str
    port: int | None
    dbname: str
    query: str = ""

    def identity(self) -> dict[str, Any]:
        """(host, port, dbname, user): safe to log and to put in isolation.json."""
        return {"host": self.host, "port": self.port, "dbname": self.dbname, "user": self.user}

    def redacted(self) -> str:
        port = f":{self.port}" if self.port is not None else ""
        query = f"?{self.query}" if self.query else ""
        return f"{self.scheme}://{self.user}:***@{self.host}{port}/{self.dbname}{query}"

    def __str__(self) -> str:  # never the password
        return self.redacted()


def parse_db_url(url: str) -> DbUrl:
    parts = urlsplit(url)
    if not parts.scheme or not parts.hostname:
        raise GuardRefusal("DATABASE_URL is not a URL with a scheme and host")
    try:
        port = parts.port
    except ValueError as exc:
        raise GuardRefusal("DATABASE_URL has an invalid port") from exc
    return DbUrl(
        scheme=parts.scheme,
        user=unquote(parts.username or ""),
        password=unquote(parts.password or ""),
        host=parts.hostname,
        port=port,
        dbname=unquote(parts.path.lstrip("/")),
        query=parts.query,
    )


def live_db_url(repo_root: Path | str = REPO_ROOT) -> DbUrl:
    """The live identity, from DATABASE_URL in the repo-root .env (by key only)."""
    env_path = Path(repo_root) / ".env"
    if not env_path.is_file():
        raise GuardRefusal("repo-root .env not found: cannot establish the live database identity")
    url = read_env_file(env_path).get("DATABASE_URL", "")
    if not url:
        raise GuardRefusal("repo-root .env has no DATABASE_URL: cannot establish the live database identity")
    live = parse_db_url(url)
    if not live.dbname or not live.user:
        raise GuardRefusal("live DATABASE_URL has no database name or user")
    return live


def build_meas_url(live: DbUrl, password: str, *, dbname: str = MEAS_DBNAME, user: str = MEAS_USER) -> str:
    """Meas URL: the live scheme/host/port, the meas role and database."""
    port = f":{live.port}" if live.port is not None else ""
    host = f"[{live.host}]" if ":" in live.host else live.host
    query = f"?{live.query}" if live.query else ""
    return (f"{live.scheme}://{quote(user, safe='')}:{quote(password, safe='')}"
            f"@{host}{port}/{quote(dbname, safe='')}{query}")


# ── G1 config guard (§2.3) ───────────────────────────────────────────────────

@dataclass(frozen=True)
class GuardResult:
    rule: str
    ok: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"rule": self.rule, "ok": self.ok, "detail": self.detail}


ListListeners = Callable[[], Iterable[tuple[str, Any]]]
TcpConnect = Callable[..., bool]


def _resolved_parts(p: Path | str) -> list[str]:
    resolved = Path(os.path.abspath(p)).resolve(strict=False)
    return [part.casefold() for part in resolved.parts]


def path_is_inside(child: Path | str, parent: Path | str) -> bool:
    """True if ``child`` is ``parent`` or below it (resolved, case-insensitive)."""
    c, p = _resolved_parts(child), _resolved_parts(parent)
    return len(c) >= len(p) and c[: len(p)] == p


def _port_of_base(base: str) -> int | None:
    parts = urlsplit(base)
    try:
        port = parts.port
    except ValueError:
        return None
    if port is None:
        return {"http": 80, "https": 443}.get(parts.scheme.lower())
    return port


def g1_checks(
    live: DbUrl,
    meas: DbUrl,
    *,
    meas_port: int,
    meas_base: str,
    meas_checkout: Path | str,
    repo_root: Path | str,
    list_listeners: ListListeners | None = None,
    tcp_connect: TcpConnect | None = None,
) -> list[GuardResult]:
    """Evaluate every G1 rule; returns one result per rule (never raises)."""
    list_listeners = list_listeners or list_listening_tcp
    tcp_connect = tcp_connect or tcp_connect_probe
    results: list[GuardResult] = []

    def add(rule: str, ok: bool, detail: str) -> None:
        results.append(GuardResult(rule, bool(ok), detail))

    same = meas.dbname.casefold() == live.dbname.casefold()
    add("same_dbname", not same,
        "meas and live name the same database" if same else "meas and live databases differ")
    add("meas_dbname", meas.dbname == MEAS_DBNAME,
        f"meas database is {meas.dbname!r}, expected {MEAS_DBNAME!r}")
    add("meas_user", meas.user == MEAS_USER, f"meas user is {meas.user!r}, expected {MEAS_USER!r}")
    same_user = meas.user.casefold() == live.user.casefold()
    add("meas_user_is_live_user", not same_user,
        "meas user equals the live user" if same_user else "meas user differs from the live user")

    base_port = _port_of_base(meas_base)
    port_ok = meas_port != LIVE_PORT and base_port != LIVE_PORT and base_port is not None
    add("meas_port", port_ok, f"meas port {meas_port}, base port {base_port}; live port is {LIVE_PORT}")

    inside = path_is_inside(meas_checkout, repo_root)
    add("checkout_outside_repo", not inside,
        "meas checkout is inside the repo root" if inside else "meas checkout is outside the repo root")

    checkout_resolved = Path(os.path.abspath(meas_checkout)).resolve(strict=False)
    levels = [i for i, anc in enumerate(checkout_resolved.parents, start=1) if (anc / ".env").exists()]
    add("no_dotenv_above_checkout", not levels,
        (f"a .env exists {', '.join(map(str, levels))} level(s) above the meas checkout"
         if levels else "no .env above the meas checkout"))

    try:
        hits = sorted({int(port) for _addr, port in list_listeners() if int(port) in IBKR_PORTS})
        add("ibkr_ports_not_listening", not hits,
            (f"TCP listener on IBKR port(s) {hits}" if hits else f"no TCP listener on {list(IBKR_PORTS)}"))
    except Exception as exc:  # fail closed: we could not verify
        add("ibkr_ports_not_listening", False, f"listener enumeration failed ({type(exc).__name__})")

    connected: list[str] = []
    for host in IBKR_PROBE_HOSTS:
        for port in IBKR_PORTS:
            try:
                ok = tcp_connect(host, port, timeout=1.0)
            except Exception:
                ok = True  # fail closed
            if ok:
                connected.append(f"{host}:{port}")
    add("ibkr_ports_not_connectable", not connected,
        (f"TCP connect succeeded to {connected}" if connected else "no TCP connect to IBKR ports succeeded"))
    return results


def enforce_g1(results: Iterable[GuardResult]) -> None:
    failed = [r for r in results if not r.ok]
    if failed:
        raise GuardRefusal("G1 refused: " + "; ".join(f"{r.rule} ({r.detail})" for r in failed))


# ── real seams: listeners and TCP probes ─────────────────────────────────────

_PS_LISTENERS = (
    "Get-NetTCPConnection -State Listen | Select-Object LocalAddress,LocalPort | ConvertTo-Json -Compress"
)


def parse_listeners_json(text: str) -> list[tuple[str, int]]:
    """Parse ``Get-NetTCPConnection | ConvertTo-Json`` output (object or list)."""
    if not text or not text.strip():
        raise ValueError("empty listener output")
    data = json.loads(text)
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise ValueError("unexpected listener output")
    out: list[tuple[str, int]] = []
    for item in data:
        if not isinstance(item, dict) or "LocalPort" not in item or "LocalAddress" not in item:
            raise ValueError("unexpected listener entry")
        out.append((str(item["LocalAddress"]), int(item["LocalPort"])))
    return out


def list_listeners_windows(run: Callable[..., Any] = subprocess.run) -> list[tuple[str, int]]:
    """Every TCP LISTEN socket (any address). Locale-independent (enum names, JSON)."""
    proc = run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_LISTENERS],
               capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise OSError(f"Get-NetTCPConnection failed (exit {proc.returncode})")
    try:
        listeners = parse_listeners_json(proc.stdout)
    except ValueError as exc:
        raise OSError(f"cannot parse listener list: {exc}") from exc
    if not listeners:  # Windows always listens on something (RPC 135): nothing = cannot verify
        raise OSError("listener enumeration returned nothing")
    return listeners


def list_listeners_procfs(root: Path = Path("/proc/net")) -> list[tuple[str, int]]:
    """Linux fallback: LISTEN (state 0A) sockets from /proc/net/tcp{,6}."""
    out: list[tuple[str, int]] = []
    found = False
    for name in ("tcp", "tcp6"):
        f = root / name
        if not f.exists():
            continue
        found = True
        for line in f.read_text().splitlines()[1:]:
            cols = line.split()
            if len(cols) > 3 and cols[3] == "0A":
                addr, port_hex = cols[1].rsplit(":", 1)
                out.append((addr, int(port_hex, 16)))
    if not found:
        raise OSError("no /proc/net/tcp")
    return out


def list_listening_tcp() -> list[tuple[str, int]]:
    if sys.platform == "win32":
        return list_listeners_windows()
    return list_listeners_procfs()


def tcp_connect_probe(host: str, port: int, timeout: float = 1.0) -> bool:
    """True if a TCP connection to (host, port) succeeds."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# ── child environment (§2.4) ─────────────────────────────────────────────────

def build_child_env(base_env: Mapping[str, str], meas_env: Mapping[str, str]) -> dict[str, str]:
    """``base_env`` minus every DB/credential key (case-insensitive), plus ``meas_env``."""
    child = {k: v for k, v in base_env.items() if not _CHILD_ENV_STRIP_RE.match(k)}
    child.update(meas_env)
    return child


# ── meas .env writer (§2.4) ──────────────────────────────────────────────────

def meas_dotenv_values(live_env: Mapping[str, str], meas_url: str) -> dict[str, str]:
    """The meas .env content: meas DATABASE_URL, market-data keys, the marker."""
    values = {"DATABASE_URL": meas_url}
    for key in MARKET_DATA_ENV_KEYS:
        if live_env.get(key):
            values[key] = live_env[key]
    values[MEAS_MARKER_KEY] = "1"
    return values


_SAFE_DOTENV_VALUE = re.compile(r"^[A-Za-z0-9_\-.:/@%+=?&,~]*$")


def _dotenv_line(key: str, value: str) -> str:
    if _SAFE_DOTENV_VALUE.match(value):
        return f"{key}={value}"
    if any(c in value for c in ("'", "\\", "\n", "\r")):
        raise GuardRefusal(f"value for {key} cannot be written to a .env safely")
    return f"{key}='{value}'"


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path = Path(path)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def write_meas_dotenv(path: Path | str, values: Mapping[str, str], *,
                      expected_database_url: str | None = None) -> None:
    for key in values:
        if _NOTIFICATION_KEY_RE.search(key):
            raise GuardRefusal(f"refusing to write a notification key ({key}) to the meas .env")
        if key not in MEAS_DOTENV_KEYS:
            raise GuardRefusal(f"refusing to write unexpected key {key} to the meas .env")
    if "DATABASE_URL" not in values:
        raise GuardRefusal("meas .env needs DATABASE_URL")
    if expected_database_url is not None and values["DATABASE_URL"] != expected_database_url:
        raise GuardRefusal("meas .env DATABASE_URL is not the meas URL")
    text = "".join(_dotenv_line(k, v) + "\n" for k, v in values.items())
    _atomic_write_bytes(Path(path), text.encode("utf-8"))


# ── settings.yaml sanitizer (§2.4) ───────────────────────────────────────────

NOTIFICATION_SECRET_KEYS = frozenset({"smtp_password", "bot_token", "chat_id", "smtp_user", "to"})


def _blank_secrets(node: Any) -> None:
    if isinstance(node, dict):
        for k in list(node):
            if k in NOTIFICATION_SECRET_KEYS:
                node[k] = ""
            else:
                _blank_secrets(node[k])
    elif isinstance(node, list):
        for item in node:
            _blank_secrets(item)


def _disable_schedule(node: Any) -> None:
    if isinstance(node, dict):
        for k in list(node):
            if isinstance(k, str) and (k == "enabled" or k.startswith("enabled_")):
                node[k] = False
            else:
                _disable_schedule(node[k])
    elif isinstance(node, list):
        for item in node:
            _disable_schedule(item)


def _section(parent: dict, key: str) -> dict:
    node = parent.setdefault(key, {})
    if node is None:
        node = parent[key] = {}
    if not isinstance(node, dict):
        raise GuardRefusal(f"settings.yaml: {key!r} is not a mapping; cannot sanitize")
    return node


def sanitize_settings(data: Any) -> dict:
    """Notifications, master switch and scan schedules off; secrets blanked; rest equal."""
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise GuardRefusal("settings.yaml is not a mapping; cannot sanitize")
    out = copy.deepcopy(data)
    _section(out, "alert_delivery")["masterEnabled"] = False
    notifications = _section(out, "notifications")
    for channel in ("gmail", "telegram"):
        _section(notifications, channel)["enabled"] = False
    _blank_secrets(notifications)
    scan = out.get("scan")
    if isinstance(scan, dict) and "schedule" in scan:
        _disable_schedule(scan["schedule"])
    return out


def sanitize_settings_file(src: Path | str, dst: Path | str) -> dict[str, str | None]:
    """Write the sanitized copy of ``src`` to ``dst``; return both sha256 values."""
    src = Path(src)
    if src.exists():
        raw = src.read_bytes()
        source_sha = hashlib.sha256(raw).hexdigest()
        data = yaml.safe_load(raw.decode("utf-8-sig"))
    else:
        source_sha, data = None, {}
    out = sanitize_settings(data)
    text = yaml.safe_dump(out, sort_keys=False, default_flow_style=False, allow_unicode=True)
    blob = text.encode("utf-8")
    _atomic_write_bytes(Path(dst), blob)
    return {"source_sha256": source_sha, "sanitized_sha256": hashlib.sha256(blob).hexdigest()}


# ── secret file (§2.2 [v2 F5]) ───────────────────────────────────────────────

def restrict_acl_icacls(path: Path | str, *, run: Callable[..., Any] = subprocess.run,
                        user: str | None = None) -> None:
    """Windows: remove inherited ACEs and grant only the current user full control."""
    if user is None:
        name = os.environ.get("USERNAME") or getpass.getuser()
        domain = os.environ.get("USERDOMAIN")
        user = f"{domain}\\{name}" if domain else name
    proc = run(["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
               capture_output=True, text=True)
    if proc.returncode != 0:
        raise OSError(f"icacls failed (exit {proc.returncode}): {(proc.stderr or '').strip()}")


def default_restrict_acl(path: Path | str) -> None:
    if sys.platform == "win32":
        restrict_acl_icacls(path)
    else:
        os.chmod(path, 0o600)


def write_secret_file(path: Path | str, *, rotate: bool = False,
                      restrict_acl: Callable[[Path], None] | None = None,
                      token_factory: Callable[[], str] | None = None) -> str:
    """Generate the meas DB password into ``path`` (one line, user-only ACL).

    Refuses to overwrite an existing file unless ``rotate``. The ACL is applied
    to a temp file before it is moved into place, so the secret never sits at
    ``path`` with inherited permissions. Returns the password: callers must
    never log it.
    """
    path = Path(path)
    if path.exists() and not rotate:
        raise GuardRefusal("meas secret file already exists; use --rotate to replace it")
    password = (token_factory or (lambda: secrets.token_urlsafe(32)))()
    if not password or "\n" in password or "\r" in password:
        raise GuardRefusal("generated secret is empty or multi-line")
    restrict = restrict_acl or default_restrict_acl
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write((password + "\n").encode("utf-8"))
        restrict(tmp)
        if path.exists() and not rotate:
            raise GuardRefusal("meas secret file appeared concurrently; refusing to overwrite")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    return password


def read_secret_file(path: Path | str) -> str:
    path = Path(path)
    if not path.is_file():
        raise GuardRefusal("meas secret file is missing; run setup")
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8-sig").splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    if len(lines) != 1 or not lines[0]:
        raise GuardRefusal("meas secret file must hold exactly one non-empty line")
    return lines[0]


# ── redaction ────────────────────────────────────────────────────────────────

_DSN_PASSWORD_RE = re.compile(r"([A-Za-z][A-Za-z0-9+.\-]*://[^:/@\s]*:)[^@\s/]*(?=@)")


def _secret_forms(secret_values: Iterable[str]) -> list[str]:
    forms: set[str] = set()
    for s in secret_values:
        if s:
            forms.update({s, quote(s, safe=""), quote_plus(s, safe="")})
    return sorted(forms, key=len, reverse=True)


def redact_text(text: str, secret_values: Iterable[str]) -> str:
    text = _DSN_PASSWORD_RE.sub(r"\1***", text)
    for form in _secret_forms(secret_values):
        text = text.replace(form, "***")
    return text


def redact(obj: Any, secret_values: Iterable[str]) -> Any:
    """Deep copy of ``obj`` with every secret (raw or URL-quoted) and DSN password masked."""
    secret_values = list(secret_values)
    if isinstance(obj, str):
        return redact_text(obj, secret_values)
    if isinstance(obj, dict):
        return {redact(k, secret_values): redact(v, secret_values) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v, secret_values) for v in obj]
    if isinstance(obj, tuple):
        return tuple(redact(v, secret_values) for v in obj)
    return obj


def _strings(obj: Any) -> Iterable[str]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(k)
            yield from _strings(v)
    elif isinstance(obj, (list, tuple, set, frozenset)):
        for v in obj:
            yield from _strings(v)
    elif obj is not None:
        yield obj if isinstance(obj, str) else str(obj)


def assert_no_secret(obj: Any, secret_values: Iterable[str]) -> None:
    """Refuse (without echoing it) if any secret appears anywhere in ``obj``."""
    forms = _secret_forms(secret_values)
    for s in _strings(obj):
        if any(form in s for form in forms):
            raise GuardRefusal("secret material found in output; refusing to emit it")


# ── confidence cache seed / carry-over (§2.4 [v3 R2-1]) ──────────────────────

def _ro_uri(path: Path | str) -> str:
    return Path(os.path.abspath(path)).as_uri() + "?mode=ro"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cache_stats(path: Path | str, *, run_start: float) -> dict[str, Any]:
    """sha256, total rows and tag-hittable rows (5-field keys not expired at run start)."""
    path = Path(path)
    sha = _sha256_file(path)
    conn = sqlite3.connect(_ro_uri(path), uri=True, timeout=30)
    try:
        try:
            rows = conn.execute("SELECT cache_key, expires_at FROM confidence_cache").fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            rows = []
    finally:
        conn.close()
    hittable = [float(exp) for key, exp in rows
                if isinstance(key, str) and len(key.split("|")) == 5
                and exp is not None and float(exp) > run_start]
    return {
        "sha256": sha,
        "total_rows": len(rows),
        "tag_hittable_rows": len(hittable),
        "tag_hittable_oldest_expires_at": min(hittable) if hittable else None,
        "tag_hittable_newest_expires_at": max(hittable) if hittable else None,
    }


def prepare_confidence_cache(live_cache: Path | str, meas_cache: Path | str, *,
                             run_start: float) -> dict[str, Any]:
    """Seed the meas cache from live once (SQLite backup API, source read-only);
    an existing meas cache is carried over and never overwritten; no live file
    means a cold start (the frozen backend creates its own file)."""
    live_cache, meas_cache = Path(live_cache), Path(meas_cache)
    if meas_cache.exists():
        origin = "carried-over"
    elif live_cache.is_file():
        meas_cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = meas_cache.with_name(f"{meas_cache.name}.{os.getpid()}.tmp")
        if tmp.exists():
            tmp.unlink()
        try:
            src = sqlite3.connect(_ro_uri(live_cache), uri=True, timeout=30)
            try:
                dst = sqlite3.connect(str(tmp))
                try:
                    src.backup(dst)
                finally:
                    dst.close()
            finally:
                src.close()
            if meas_cache.exists():
                raise GuardRefusal("meas confidence cache appeared during seeding; not overwriting it")
            os.replace(tmp, meas_cache)
        except BaseException:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass
            raise
        origin = "seeded-from-live"
    else:
        return {"origin": "cold", "sha256": None, "total_rows": 0, "tag_hittable_rows": 0,
                "tag_hittable_oldest_expires_at": None, "tag_hittable_newest_expires_at": None}
    return {"origin": origin, **cache_stats(meas_cache, run_start=run_start)}


# ── DB layer (T2, #282): §2.3 G2, §2.5 copy + verification, G3 DB probe ──────
#
# Every database action is a ``docker exec`` into the Postgres container,
# through one injectable runner (``PgDocker.runner``) so tests never run docker.
# - Superuser sessions use the container's own ``$POSTGRES_USER`` (expanded by
#   ``sh`` inside the container) and read SQL from stdin: no credential and no
#   SQL in argv. Admin statements run on the maintenance database
#   (``postgres``), never in a session on the live database.
# - Every session on the live database is read-only (``READ_ONLY_PREFIX``) and
#   SELECT-only; the live database name appears only in ``pg_dump``, in those
#   SELECT sessions, in setup's single ``REVOKE`` and in the G2 connect attempt.
# - The meas password reaches docker only as ``docker exec -e PGPASSWORD`` with
#   the value in the docker subprocess env, and in setup's role statement on
#   stdin. Every error text is redacted before it is put in an exception.

DB_CONTAINER = "tradingassistant-db"
MAINTENANCE_DB = "postgres"
READ_ONLY_PREFIX = "SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY;\n"
MEAS_ROLE_ATTRIBUTES = "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
# libpq / psql connection-failure texts that mean "authenticated, but not allowed
# into this database". Anything else (bad password, container down, no output)
# is not proof of G2 and refuses with a different message.
G2_PERMISSION_PATTERNS: tuple[str, ...] = ("permission denied for database", "not allowed to connect")


@dataclass(frozen=True)
class CmdResult:
    returncode: int
    stdout: str
    stderr: str


DockerRunner = Callable[..., CmdResult]


def subprocess_runner(argv: list[str], *, input: str | None = None,
                      env: Mapping[str, str] | None = None, timeout: float | None = None) -> CmdResult:
    """The real runner: ``subprocess.run`` with captured text output."""
    proc = subprocess.run(list(argv), input=input, env=None if env is None else dict(env),
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout)
    return CmdResult(proc.returncode, proc.stdout or "", proc.stderr or "")


def quote_ident(name: str) -> str:
    if not name or "\x00" in name:
        raise GuardRefusal("empty or NUL-containing SQL identifier")
    return '"' + name.replace('"', '""') + '"'


def quote_literal(value: str) -> str:
    if "\x00" in value:
        raise GuardRefusal("NUL in SQL literal")
    return "'" + value.replace("'", "''") + "'"


def _check_dbname(name: str) -> None:
    """psql/pg_dump treat a ``-d`` value with ``=`` or a URI prefix as a conninfo string."""
    if not name or "\x00" in name or "=" in name or "://" in name:
        raise GuardRefusal("database name is empty or looks like a connection string")


def _redacted_tail(res: CmdResult, secret_values: Iterable[str], limit: int = 400) -> str:
    """stderr+stdout, redacted first (so a cut can never expose part of a secret), then cut."""
    text = redact_text(f"{res.stderr or ''}\n{res.stdout or ''}".strip(), secret_values)
    return text[-limit:] if len(text) > limit else text


@dataclass(frozen=True)
class PgDocker:
    """``docker exec`` access to the Postgres container (the test / T4 seam)."""

    container: str = DB_CONTAINER
    runner: DockerRunner = subprocess_runner
    docker: str = "docker"
    maintenance_db: str = MAINTENANCE_DB
    timeout: float = 120.0
    copy_timeout: float = 4 * 3600.0

    def run(self, argv: list[str], *, what: str, input: str | None = None,
            env: Mapping[str, str] | None = None, timeout: float | None = None) -> CmdResult:
        try:
            return self.runner(argv, input=input, env=env, timeout=timeout or self.timeout)
        except Exception as exc:  # docker missing, timeout, ...: fail closed, never echo output
            raise GuardRefusal(f"{what}: could not run docker ({type(exc).__name__})") from None

    def superuser_argv(self, dbname: str) -> list[str]:
        _check_dbname(dbname)
        script = ("exec psql -X -q -A -t -v ON_ERROR_STOP=1 -v VERBOSITY=terse "
                  f'-U "$POSTGRES_USER" -d {shlex.quote(dbname)}')
        return [self.docker, "exec", "-i", self.container, "sh", "-c", script]

    def superuser_sql(self, sql: str, *, dbname: str, read_only: bool, what: str,
                      secret_values: Iterable[str] = ()) -> str:
        text = (READ_ONLY_PREFIX if read_only else "") + sql
        res = self.run(self.superuser_argv(dbname), what=what, input=text)
        if res.returncode != 0:
            raise GuardRefusal(f"{what} failed (exit {res.returncode}): {_redacted_tail(res, secret_values)}")
        return res.stdout

    def select_json(self, sql: str, *, dbname: str, what: str) -> Any:
        """One read-only SELECT session returning a single JSON value."""
        out = self.superuser_sql(sql, dbname=dbname, read_only=True, what=what)
        lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
        if not lines:
            raise GuardRefusal(f"{what}: no output")
        try:
            return json.loads(lines[-1])
        except ValueError:
            raise GuardRefusal(f"{what}: unexpected output") from None

    def meas_runner_connect_argv(self, dbname: str) -> list[str]:
        """Connect as meas_runner over TCP inside the container (password auth, then
        the CONNECT privilege); ``-e PGPASSWORD`` takes the value from docker's env."""
        _check_dbname(dbname)
        return [self.docker, "exec", "-e", "PGPASSWORD", self.container,
                "psql", "-X", "-q", "-A", "-t", "-w", "-h", "127.0.0.1",
                "-U", MEAS_USER, "-d", dbname, "-c", "SELECT 1"]


def _check_live_identity(live: DbUrl, pg: PgDocker) -> None:
    """The live identity must never collide with the meas names or the admin DB."""
    if not live.dbname or not live.user:
        raise GuardRefusal("live DATABASE_URL has no database name or user")
    _check_dbname(live.dbname)
    _check_dbname(pg.maintenance_db)
    if live.dbname.casefold() == MEAS_DBNAME.casefold():
        raise GuardRefusal("the live database is the meas database; refusing")
    if live.user.casefold() == MEAS_USER.casefold():
        raise GuardRefusal("the live user is the meas role; refusing")
    if pg.maintenance_db.casefold() in (live.dbname.casefold(), MEAS_DBNAME.casefold()):
        raise GuardRefusal("the maintenance database must be neither the live nor the meas database")


def reverse_revoke_command(live: DbUrl) -> str:
    """Undo setup's only change to the live database."""
    return f"GRANT CONNECT ON DATABASE {quote_ident(live.dbname)} TO PUBLIC"


def enforce_guard(name: str, results: Iterable[GuardResult]) -> None:
    failed = [r for r in results if not r.ok]
    if failed:
        raise GuardRefusal(f"{name} refused: " + "; ".join(f"{r.rule} ({r.detail})" for r in failed))


# ── one-time setup (§2.3 G2; runs only after Kenneth's explicit yes) ─────────

def setup(live: DbUrl, secret_file: Path | str, *, rotate: bool = False, pg: PgDocker | None = None,
          log: Callable[[str], None] = print,
          restrict_acl: Callable[[Path], None] | None = None,
          token_factory: Callable[[], str] | None = None) -> dict[str, Any]:
    """Create ``meas_runner`` (password from the secret file) and ``bamendjou_meas``,
    ``REVOKE CONNECT ON DATABASE <live> FROM PUBLIC``, verify the live user still
    connects and that G2 now holds. Idempotent; returns a secret-free summary
    with the reverse command (also logged)."""
    pg = pg or PgDocker()
    _check_live_identity(live, pg)
    reverse = reverse_revoke_command(live)
    lit_db, lit_user = quote_literal(live.dbname), quote_literal(live.user)

    pre = pg.select_json(
        "/* meas:setup-precheck */ SELECT json_build_object("
        f"'live_db_exists', EXISTS (SELECT 1 FROM pg_database WHERE datname = {lit_db}), "
        f"'live_user_super', COALESCE((SELECT rolsuper FROM pg_roles WHERE rolname = {lit_user}), false), "
        "'live_user_owner', EXISTS (SELECT 1 FROM pg_database d JOIN pg_roles r ON r.oid = d.datdba "
        f"WHERE d.datname = {lit_db} AND r.rolname = {lit_user}), "
        f"'role_exists', EXISTS (SELECT 1 FROM pg_roles WHERE rolname = {quote_literal(MEAS_USER)}), "
        f"'meas_db_exists', EXISTS (SELECT 1 FROM pg_database WHERE datname = {quote_literal(MEAS_DBNAME)}));\n",
        dbname=pg.maintenance_db, what="setup pre-check")
    if not isinstance(pre, dict):
        raise GuardRefusal("setup pre-check: unexpected output")
    if pre.get("live_db_exists") is not True:
        raise GuardRefusal(f"the live database {live.dbname!r} does not exist in the container; refusing")
    if pre.get("live_user_super") is not True and pre.get("live_user_owner") is not True:
        raise GuardRefusal(f"live user {live.user!r} is neither superuser nor owner of the live database: "
                           "REVOKE CONNECT FROM PUBLIC would lock it out; refusing")

    # The secret comes after the pre-check. The file is written before the role
    # is changed and every setup re-syncs the role to the file, so a failure in
    # between heals on the next run.
    secret_path = Path(secret_file)
    if secret_path.exists() and not rotate:
        password = read_secret_file(secret_path)
    else:
        password = write_secret_file(secret_path, rotate=rotate, restrict_acl=restrict_acl,
                                     token_factory=token_factory)
    secret_values = [password, live.password]

    def emit(line: str) -> None:
        assert_no_secret(line, secret_values)
        log(line)

    verb = "ALTER" if pre.get("role_exists") is True else "CREATE"
    pg.superuser_sql(
        f"/* meas:{verb.lower()}-role */ {verb} ROLE {MEAS_USER} WITH {MEAS_ROLE_ATTRIBUTES} "
        f"PASSWORD {quote_literal(password)};\n",
        dbname=pg.maintenance_db, read_only=False, what=f"{verb} ROLE {MEAS_USER}",
        secret_values=secret_values)

    if pre.get("meas_db_exists") is True:
        db_sql = (f"/* meas:alter-db-owner */ ALTER DATABASE {quote_ident(MEAS_DBNAME)} "
                  f"OWNER TO {quote_ident(MEAS_USER)};\n")
        db_state = "exists"
    else:
        db_sql = (f"/* meas:create-db */ CREATE DATABASE {quote_ident(MEAS_DBNAME)} "
                  f"OWNER {quote_ident(MEAS_USER)};\n")
        db_state = "created"
    pg.superuser_sql(db_sql, dbname=pg.maintenance_db, read_only=False,
                     what=f"database {MEAS_DBNAME}", secret_values=secret_values)

    pg.superuser_sql(f"/* meas:revoke */ REVOKE CONNECT ON DATABASE {quote_ident(live.dbname)} FROM PUBLIC;\n",
                     dbname=pg.maintenance_db, read_only=False, what="REVOKE CONNECT on the live database",
                     secret_values=secret_values)
    emit(f"REVOKE CONNECT ON DATABASE {quote_ident(live.dbname)} FROM PUBLIC done. To undo: {reverse}")

    try:
        chk = pg.select_json(
            "/* meas:live-connect */ SELECT json_build_object('one', 1, 'live_user_can_connect', "
            f"has_database_privilege({lit_user}, {lit_db}, 'CONNECT'));\n",
            dbname=live.dbname, what="live connect check")
    except GuardRefusal as exc:
        raise GuardRefusal(f"{exc}. The live database may be unreachable; to undo run: {reverse}") from None
    if not isinstance(chk, dict) or chk.get("one") != 1 or chk.get("live_user_can_connect") is not True:
        raise GuardRefusal(f"live user {live.user!r} lost CONNECT on the live database; to undo run: {reverse}")

    g2 = check_live_db_refused(live, password, pg=pg)
    try:
        enforce_guard("G2", g2)
    except GuardRefusal as exc:
        raise GuardRefusal(f"{exc} (after setup); to undo the REVOKE run: {reverse}") from None

    result = {
        "meas_role": MEAS_USER,
        "meas_db": MEAS_DBNAME,
        "role": "created" if verb == "CREATE" else "updated",
        "database": db_state,
        "revoked_connect_on": live.dbname,
        "live_user_connects": True,
        "reverse_command": reverse,
        "g2": [r.to_dict() for r in g2],
    }
    assert_no_secret(result, secret_values)
    emit(f"setup complete; G2 holds. Reverse command (run as the container superuser): {reverse}")
    return result


# ── per-run copy (§2.5; the live DB is only read) ────────────────────────────

def dump_restore_script(live_dbname: str) -> str:
    """``pg_dump | pg_restore`` inside the container; both exit codes enforced.

    POSIX equivalent of ``set -o pipefail`` (works in busybox ash and dash):
    pg_dump's status goes to a temp file, pg_restore's is ``$?`` of the pipe.
    A missing or empty status counts as failure.
    """
    _check_dbname(live_dbname)
    dump = f'pg_dump -U "$POSTGRES_USER" -Fc --no-acl --no-owner -d {shlex.quote(live_dbname)}'
    restore = (f'pg_restore -U "$POSTGRES_USER" --no-acl --no-owner --role={MEAS_USER} '
               f"--exit-on-error -d {MEAS_DBNAME}")
    return (
        "st=$(mktemp)\n"
        'if [ -z "$st" ]; then echo "mktemp failed" >&2; exit 90; fi\n'
        f'{{ {dump}; echo $? > "$st"; }} | {restore}\n'
        "rr=$?\n"
        'dr=$(cat "$st" 2>/dev/null); rm -f "$st"\n'
        'if [ "$dr" != 0 ]; then echo "pg_dump failed (exit ${dr:-unknown})" >&2; exit 91; fi\n'
        'if [ "$rr" != 0 ]; then echo "pg_restore failed (exit $rr)" >&2; exit 92; fi\n'
        "exit 0\n"
    )


def copy_live_to_meas(live: DbUrl, *, pg: PgDocker | None = None) -> dict[str, Any]:
    """Drop and recreate ``bamendjou_meas``, then restore a ``pg_dump`` of live into it."""
    pg = pg or PgDocker()
    _check_live_identity(live, pg)
    pg.superuser_sql(
        "/* meas:drop-create */\n"
        f"DROP DATABASE IF EXISTS {quote_ident(MEAS_DBNAME)} WITH (FORCE);\n"
        f"CREATE DATABASE {quote_ident(MEAS_DBNAME)} OWNER {quote_ident(MEAS_USER)};\n",
        dbname=pg.maintenance_db, read_only=False, what=f"drop/create {MEAS_DBNAME}",
        secret_values=[live.password])
    argv = [pg.docker, "exec", pg.container, "sh", "-c", dump_restore_script(live.dbname)]
    res = pg.run(argv, what="dump/restore", timeout=pg.copy_timeout)
    if res.returncode != 0:
        raise GuardRefusal(f"dump/restore failed (exit {res.returncode}): "
                           f"{_redacted_tail(res, [live.password])}")
    return {"database": MEAS_DBNAME, "dump_restore": "ok"}


def _str_list(value: Any, what: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise GuardRefusal(f"{what}: unexpected output")
    return value


def _count_map(value: Any, tables: list[str], what: str) -> dict[str, int]:
    if (not isinstance(value, dict) or set(value) != set(tables)
            or not all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in value.values())):
        raise GuardRefusal(f"{what}: unexpected output")
    return value


def _ohlcv_stats(value: Any, what: str) -> dict[str, Any]:
    if (not isinstance(value, dict) or set(value) != {"count", "min", "max"}
            or not isinstance(value["count"], int) or isinstance(value["count"], bool)
            or not all(v is None or isinstance(v, str) for v in (value["min"], value["max"]))):
        raise GuardRefusal(f"{what}: unexpected output")
    return value


def verify_copy(live: DbUrl, *, pg: PgDocker | None = None) -> dict[str, Any]:
    """§2.5 (a)-(c), SELECT-only. Each read is done on the copy first, then on
    live (live can only gain rows meanwhile). Returns the secret-free part for
    isolation.json; refuses on the plan's rules, records other differences."""
    pg = pg or PgDocker()
    _check_live_identity(live, pg)
    pair = ((MEAS_DBNAME, "copy"), (live.dbname, "live"))

    def both(sql: str, what: str) -> dict[str, Any]:
        return {side: pg.select_json(sql, dbname=db, what=f"{what} ({side})") for db, side in pair}

    # (a) the set of public tables
    t = both("/* meas:tables */ SELECT coalesce(json_agg(tablename ORDER BY tablename), '[]'::json) "
             "FROM pg_tables WHERE schemaname = 'public';\n", "table list")
    copy_tables, live_tables = _str_list(t["copy"], "table list"), _str_list(t["live"], "table list")
    if set(copy_tables) != set(live_tables):
        missing = sorted(set(live_tables) - set(copy_tables))
        extra = sorted(set(copy_tables) - set(live_tables))
        raise GuardRefusal(f"copy verification: table set differs (missing in copy {missing}, "
                           f"extra in copy {extra})")
    tables = sorted(live_tables)
    if not tables:
        raise GuardRefusal("copy verification: no tables in schema public")
    for required in ("ohlcv_daily", "alembic_version"):
        if required not in tables:
            raise GuardRefusal(f"copy verification: {required} table missing")

    # (b) per-table row counts, and the ohlcv_daily bounds
    selects = "\nUNION ALL\n".join(
        f"SELECT {quote_literal(name)} AS t, count(*) AS n FROM public.{quote_ident(name)}" for name in tables)
    c = both(f"/* meas:counts */ SELECT coalesce(json_object_agg(t, n), '{{}}'::json) FROM (\n{selects}\n) s;\n",
             "row counts")
    copy_n, live_n = _count_map(c["copy"], tables, "row counts"), _count_map(c["live"], tables, "row counts")
    for name in tables:
        if copy_n[name] == 0 and live_n[name] > 0:
            raise GuardRefusal(f"copy verification: table {name} is empty in the copy but has rows in live")

    o = both("/* meas:ohlcv */ SELECT json_build_object('count', count(*), 'min', min(date)::text, "
             "'max', max(date)::text) FROM public.ohlcv_daily;\n", "ohlcv_daily stats")
    co, lo = _ohlcv_stats(o["copy"], "ohlcv_daily stats"), _ohlcv_stats(o["live"], "ohlcv_daily stats")
    if co["count"] > lo["count"]:
        raise GuardRefusal(f"copy verification: ohlcv_daily count in copy ({co['count']}) "
                           f"above live ({lo['count']})")
    if co["max"] is not None and (lo["max"] is None or co["max"] > lo["max"]):
        raise GuardRefusal(f"copy verification: ohlcv_daily max(date) in copy ({co['max']}) "
                           f"above live ({lo['max']})")
    if co["min"] != lo["min"]:
        raise GuardRefusal(f"copy verification: ohlcv_daily min(date) differs "
                           f"(copy {co['min']}, live {lo['min']})")

    # (c) alembic_version
    a = both("/* meas:alembic */ SELECT coalesce(json_agg(version_num ORDER BY version_num), '[]'::json) "
             "FROM public.alembic_version;\n", "alembic_version")
    copy_av, live_av = _str_list(a["copy"], "alembic_version"), _str_list(a["live"], "alembic_version")
    if not live_av or copy_av != live_av:
        raise GuardRefusal(f"copy verification: alembic_version differs or is empty "
                           f"(copy {copy_av}, live {live_av})")

    result = {
        "database": MEAS_DBNAME,
        "tables": tables,
        "row_counts": {name: {"copy": copy_n[name], "live": live_n[name]} for name in tables},
        "count_differences": [name for name in tables if copy_n[name] != live_n[name]],
        "ohlcv_daily": {"copy": co, "live": lo},
        "alembic_version": live_av,
    }
    assert_no_secret(result, [live.password])
    return result


# ── G2 probe (§2.3; on every check and run) ──────────────────────────────────

def check_live_db_refused(live: DbUrl, password: str, *, pg: PgDocker | None = None) -> list[GuardResult]:
    """G2: ``meas_runner`` is not a superuser, and connecting as it to the live
    database fails with a permission refusal. Never raises: any other outcome
    (it connects, wrong password, container down) is a failed result."""
    pg = pg or PgDocker()
    secret_values = [password, live.password]
    results: list[GuardResult] = []

    try:
        info = pg.select_json(
            "/* meas:g2-role */ SELECT json_build_object('exists', count(*) > 0, 'rolsuper', bool_or(rolsuper)) "
            f"FROM pg_roles WHERE rolname = {quote_literal(MEAS_USER)};\n",
            dbname=pg.maintenance_db, what="G2 role check")
        if not isinstance(info, dict) or info.get("exists") is not True:
            results.append(GuardResult("g2_meas_role_not_superuser", False,
                                       f"role {MEAS_USER} does not exist; run setup"))
        elif info.get("rolsuper") is not False:
            results.append(GuardResult("g2_meas_role_not_superuser", False, f"role {MEAS_USER} is a superuser"))
        else:
            results.append(GuardResult("g2_meas_role_not_superuser", True, f"role {MEAS_USER} is not a superuser"))
    except GuardRefusal as exc:
        results.append(GuardResult("g2_meas_role_not_superuser", False,
                                   redact_text(f"could not check the meas role: {exc}", secret_values)))

    try:
        res = pg.run(pg.meas_runner_connect_argv(live.dbname), what="G2 connect attempt",
                     env={**os.environ, "PGPASSWORD": password})
        if res.returncode == 0:
            results.append(GuardResult("g2_live_db_refused", False,
                                       f"{MEAS_USER} CONNECTED to the live database {live.dbname!r}"))
        else:
            text = _redacted_tail(res, secret_values)
            if any(p in text.lower() for p in G2_PERMISSION_PATTERNS):
                results.append(GuardResult("g2_live_db_refused", True,
                                           f"{MEAS_USER} is refused by the live database (permission)"))
            else:
                results.append(GuardResult(
                    "g2_live_db_refused", False,
                    "could not verify: the connect attempt failed, but not a permission refusal "
                    f"(exit {res.returncode}): {text or 'no output'}"))
    except GuardRefusal as exc:
        results.append(GuardResult("g2_live_db_refused", False,
                                   redact_text(f"could not verify: {exc}", secret_values)))
    return results


# ── G3 DB probe (§2.3; after the frozen backend is healthy, and at the end) ──

def meas_connections_ok(*, pg: PgDocker | None = None) -> GuardResult:
    """Every ``meas_runner`` connection is on the copy, and there is at least one."""
    pg = pg or PgDocker()
    rule = "g3_meas_connections_on_copy"
    try:
        counts = pg.select_json(
            "/* meas:g3-activity */ SELECT coalesce(json_object_agg(d, n), '{}'::json) FROM ("
            "SELECT coalesce(datname, '') AS d, count(*) AS n FROM pg_stat_activity "
            f"WHERE usename = {quote_literal(MEAS_USER)} GROUP BY datname) s;\n",
            dbname=pg.maintenance_db, what="G3 pg_stat_activity")
    except GuardRefusal as exc:
        return GuardResult(rule, False, f"could not query pg_stat_activity: {exc}")
    if not isinstance(counts, dict):
        return GuardResult(rule, False, "pg_stat_activity: unexpected output")
    if not counts:
        return GuardResult(rule, False, f"no {MEAS_USER} connection at all (the backend is not using the copy)")
    others = sorted(k for k in counts if k != MEAS_DBNAME)
    if others:
        return GuardResult(rule, False, f"{MEAS_USER} connected to other database(s) {others}: {counts}")
    return GuardResult(rule, True, f"{MEAS_USER} connections by database: {counts}")


# ── run sequence (T3, #283): §2.6, G3 process identity, evidence ─────────────
#
# Rules for the run sequence:
# - Every side effect is a ``RunDeps`` seam (clock and sleep, docker/Postgres
#   through T2's ``PgDocker``, process launch, health GETs, listener/PID-owner
#   enumeration, parent-PID lookup, the forced tree kill, git, the tag runner),
#   so tests never start, stop or connect to anything real.
# - The frozen backend is stopped only by the PID this orchestrator launched,
#   with ``taskkill /F /T /PID`` (forced tree kill): never by port, never by
#   name, and the live backend on :8000 is only ever read (its health PID).
# - Every refusal after the start goes through the same stop (try/finally).
# - ``isolation.json`` is redacted, checked with ``assert_no_secret`` and holds
#   no absolute path (paths relative to the job folder or the repo).

EXIT_OK = 0
EXIT_FAILED = 1     # the measurement ran, but something after the start failed
EXIT_REFUSED = 2    # a guard refused; the runner never started

MEAS_HOST = "127.0.0.1"
MEAS_BASE = f"http://{MEAS_HOST}:{MEAS_PORT}"
LIVE_BASE = f"http://127.0.0.1:{LIVE_PORT}"
HEALTH_PATH = "/api/config/health"
RUN_AT_ET = dt.time(13, 0, 30)
MAX_PARENT_DEPTH = 16

DOTENV_REL = Path(".env")
LOCAL_CREDENTIALS_REL = Path("backend") / "config" / "local_credentials.yaml"
RUNNER_REL = Path("docs") / "superpowers" / "measurements" / "run_measurement_day.py"
SCANS_REL = Path("docs") / "superpowers" / "measurements" / "scans"
# Written into the meas checkout each run; each must be gitignored there.
# scan_schedule.yaml is deliberately NOT copied (the tag's scheduler stays empty).
RUNTIME_FILES: tuple[Path, ...] = (DOTENV_REL, SETTINGS_REL, LOCAL_CREDENTIALS_REL, CONFIDENCE_CACHE_REL)
DOCKER_DESKTOP_EXE = r"C:\Program Files\Docker\Docker\Docker Desktop.exe"
_SECRET_ENV_KEY_RE = re.compile(r"TOKEN|PASSWORD|PASS|SECRET|KEY|DATABASE_URL|TELEGRAM|GMAIL|CHAT", re.I)

SETUP_WARNING = (
    "setup changes privileges on the LIVE database: it runs REVOKE CONNECT ON DATABASE <live> FROM PUBLIC "
    f"and creates the role {MEAS_USER} and the database {MEAS_DBNAME}. It runs only after Kenneth's "
    "explicit yes in chat: re-run with --i-have-kenneths-approval. It is reversible "
    "(GRANT CONNECT ON DATABASE <live> TO PUBLIC)."
)


def venv_python(repo_root: Path | str) -> Path:
    """The repo venv interpreter (same venv as days 1-2)."""
    root = Path(repo_root) / "backend" / ".venv"
    return root / "Scripts" / "python.exe" if sys.platform == "win32" else root / "bin" / "python"


def _nth_sunday(year: int, month: int, n: int) -> dt.date:
    d = dt.date(year, month, 1)
    d += dt.timedelta(days=(6 - d.weekday()) % 7)
    return d + dt.timedelta(weeks=n - 1)


def to_et(t_utc: dt.datetime) -> dt.datetime:
    """UTC-aware datetime -> naive US Eastern wall time (the tag runner's own rule)."""
    y = t_utc.year
    dst_start = dt.datetime.combine(_nth_sunday(y, 3, 2), dt.time(7, 0))
    dst_end = dt.datetime.combine(_nth_sunday(y, 11, 1), dt.time(6, 0))
    naive = t_utc.astimezone(dt.timezone.utc).replace(tzinfo=None)
    offset = -4 if dst_start <= naive < dst_end else -5
    return naive + dt.timedelta(hours=offset)


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(t: dt.datetime | None) -> str | None:
    return t.astimezone(dt.timezone.utc).isoformat() if t is not None else None


# ── real seams: PowerShell JSON, processes, listeners with owners ────────────

def _powershell(command: str, runner: Callable[..., CmdResult]) -> CmdResult:
    return runner(["powershell", "-NoProfile", "-NonInteractive", "-Command", command], timeout=60)


_PS_LISTENER_OWNERS = (
    "Get-NetTCPConnection -State Listen | Select-Object LocalAddress,LocalPort,OwningProcess "
    "| ConvertTo-Json -Compress"
)


def parse_listener_owners_json(text: str) -> list[tuple[str, int, int]]:
    """``Get-NetTCPConnection | Select LocalAddress,LocalPort,OwningProcess | ConvertTo-Json``."""
    if not text or not text.strip():
        raise ValueError("empty listener output")
    data = json.loads(text)
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise ValueError("unexpected listener output")
    out: list[tuple[str, int, int]] = []
    for item in data:
        if not isinstance(item, dict) or not {"LocalAddress", "LocalPort", "OwningProcess"} <= set(item):
            raise ValueError("unexpected listener entry")
        out.append((str(item["LocalAddress"]), int(item["LocalPort"]), int(item["OwningProcess"])))
    return out


def list_listener_owners_windows(runner: Callable[..., CmdResult] = subprocess_runner
                                 ) -> list[tuple[str, int, int]]:
    proc = _powershell(_PS_LISTENER_OWNERS, runner)
    if proc.returncode != 0:
        raise OSError(f"Get-NetTCPConnection failed (exit {proc.returncode})")
    try:
        owners = parse_listener_owners_json(proc.stdout)
    except ValueError as exc:
        raise OSError(f"cannot parse listener list: {exc}") from exc
    if not owners:
        raise OSError("listener enumeration returned nothing")
    return owners


def list_listener_owners() -> list[tuple[str, int, int | None]]:
    """Every TCP LISTEN socket with its owning PID (None where it cannot be known:
    the identity checks then fail closed)."""
    if sys.platform == "win32":
        return list(list_listener_owners_windows())
    return [(addr, port, None) for addr, port in list_listeners_procfs()]


def parse_process_json(text: str) -> int | None:
    """``Get-CimInstance Win32_Process | Select ProcessId,ParentProcessId | ConvertTo-Json``:
    the parent PID, or None when no such process exists (empty output)."""
    if not text or not text.strip():
        return None
    data = json.loads(text)
    if not isinstance(data, dict) or "ParentProcessId" not in data:
        raise ValueError("unexpected Win32_Process output")
    return int(data["ParentProcessId"])


def parent_pid_windows(pid: int, runner: Callable[..., CmdResult] = subprocess_runner) -> int | None:
    pid = int(pid)
    proc = _powershell(f"Get-CimInstance Win32_Process -Filter 'ProcessId={pid}' "
                       "| Select-Object ProcessId,ParentProcessId | ConvertTo-Json -Compress", runner)
    if proc.returncode != 0:
        raise OSError(f"Get-CimInstance Win32_Process failed (exit {proc.returncode})")
    return parse_process_json(proc.stdout)


def _parent_pid_procfs(pid: int) -> int | None:
    try:
        stat = Path(f"/proc/{int(pid)}/stat").read_text()
    except OSError:
        return None
    return int(stat.rsplit(")", 1)[1].split()[1])


def parent_pid(pid: int) -> int | None:
    """Parent PID of ``pid`` (Win32_Process.ParentProcessId), None if it does not exist."""
    return parent_pid_windows(pid) if sys.platform == "win32" else _parent_pid_procfs(pid)


def pid_exists(pid: int) -> bool:
    if sys.platform == "win32":
        return parent_pid_windows(pid) is not None
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def taskkill_argv(pid: int) -> list[str]:
    """Forced tree kill of exactly one PID (a windowless Python ignores the non-forced form)."""
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise GuardRefusal("refusing to kill: not a launched process id")
    return ["taskkill", "/F", "/T", "/PID", str(pid)]


def kill_process_tree(pid: int, *, runner: Callable[..., CmdResult] = subprocess_runner) -> CmdResult:
    argv = taskkill_argv(pid)
    if sys.platform == "win32":
        return runner(argv, timeout=60)
    import signal
    try:
        os.kill(pid, signal.SIGKILL)
        return CmdResult(0, "", "")
    except OSError as exc:
        return CmdResult(1, "", type(exc).__name__)


def is_descendant_or_self(pid: int | None, ancestor: int, parent_of: Callable[[int], int | None],
                          *, max_depth: int = MAX_PARENT_DEPTH) -> bool:
    """Walk parent PIDs from ``pid`` up to ``ancestor`` (bounded; loops and errors are False)."""
    cur, seen = pid, set()
    for _ in range(max_depth + 1):
        if cur == ancestor:
            return True
        if cur is None or cur <= 0 or cur in seen:
            return False
        seen.add(cur)
        try:
            cur = parent_of(cur)
        except Exception:
            return False
    return False


_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http_get_json(url: str, timeout: float = 5.0) -> Any:
    """GET a local health endpoint (no proxy); an HTTP error body is still parsed."""
    try:
        with _NO_PROXY_OPENER.open(url, timeout=timeout) as resp:
            body = resp.read()
    except urllib.error.HTTPError as exc:
        body = exc.read()
    return json.loads(body.decode("utf-8", errors="replace"))


_LAUNCHED: list[subprocess.Popen] = []


def launch_process(argv: list[str], *, cwd: Path | str, env: Mapping[str, str], log_path: Path | str) -> int:
    """Start ``argv`` detached from the console, stdout+stderr to ``log_path``; returns its PID."""
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    with open(log_path, "ab") as log_file:
        proc = subprocess.Popen(list(argv), cwd=str(cwd), env=dict(env), stdin=subprocess.DEVNULL,
                                stdout=log_file, stderr=subprocess.STDOUT, creationflags=flags)
    _LAUNCHED.append(proc)
    return proc.pid


def run_logged(argv: list[str], *, cwd: Path | str, env: Mapping[str, str], log_path: Path | str,
               echo: Callable[[str], None] | None = None) -> int:
    """Run ``argv`` to completion, output to ``log_path`` and echoed; returns its exit code."""
    echo = echo or (lambda line: print(line, flush=True))
    with open(log_path, "ab") as log_file:
        proc = subprocess.Popen(list(argv), cwd=str(cwd), env=dict(env), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        assert proc.stdout is not None
        for raw in proc.stdout:
            log_file.write(raw)
            log_file.flush()
            echo(raw.decode("utf-8", errors="replace").rstrip())
        return proc.wait()


def git_runner(args: list[str]) -> CmdResult:
    return subprocess_runner(["git", *args], timeout=600)


def start_docker_desktop() -> None:
    if sys.platform != "win32":
        raise OSError("Docker Desktop can only be started on Windows")
    subprocess.Popen([DOCKER_DESKTOP_EXE], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)


def _log_stdout(line: str) -> None:
    print(f"[{_utcnow().strftime('%Y-%m-%d %H:%M:%S')}Z] {line}", flush=True)


@dataclass
class RunDeps:
    """Every side-effecting seam of check / run / cleanup (tests replace them all)."""

    now: Callable[[], dt.datetime] = _utcnow
    sleep: Callable[[float], None] = time.sleep
    pg: PgDocker = field(default_factory=PgDocker)
    launch: Callable[..., int] = launch_process
    http_get_json: Callable[..., Any] = http_get_json
    list_listener_owners: Callable[[], Iterable[tuple[str, int, int | None]]] = list_listener_owners
    parent_pid: Callable[[int], int | None] = parent_pid
    pid_exists: Callable[[int], bool] = pid_exists
    kill_tree: Callable[[int], CmdResult] = kill_process_tree
    git: Callable[[list[str]], CmdResult] = git_runner
    run_runner: Callable[..., int] = run_logged
    cmd: Callable[..., CmdResult] = subprocess_runner
    start_docker_desktop: Callable[[], None] = start_docker_desktop
    tcp_connect: TcpConnect = tcp_connect_probe
    environ: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    log: Callable[[str], None] = _log_stdout
    health_timeout_seconds: float = 180.0
    health_poll_seconds: float = 2.0
    docker_wait_seconds: float = 300.0
    container_wait_seconds: float = 120.0
    stop_verify_seconds: float = 30.0


@dataclass
class RunResult:
    exit_code: int
    error: str | None = None
    isolation: dict[str, Any] | None = None
    evidence_dir: Path | None = None


# ── evidence copy (§2.6 step 8; never overwrites) ────────────────────────────

def copy_evidence(src: Path | str, dest_root: Path | str, day: str, stamp: str, *,
                  log: Callable[[str], None] = print) -> Path:
    """Copy the meas day folder to ``dest_root/<day>``; if that exists and is not
    empty, to ``<day>-isolated-<stamp>`` instead (logged). Never writes into an
    existing non-empty folder: ``copytree`` creates the destination itself."""
    src, dest_root = Path(src), Path(dest_root)
    dest = dest_root / day
    if dest.exists() or dest.is_symlink():
        if dest.is_dir() and not dest.is_symlink() and not any(dest.iterdir()):
            dest.rmdir()   # empty: copytree recreates it; fails if anything appeared meanwhile
        else:
            alt = dest_root / f"{day}-isolated-{stamp}"
            log(f"evidence: scans/{day} already exists and is not empty; copying to scans/{alt.name} instead")
            dest = alt
            if dest.exists() or dest.is_symlink():
                raise GuardRefusal(f"evidence folder scans/{dest.name} already exists; refusing to overwrite it")
    dest_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest)
    return dest


# ── path scrubbing for isolation.json ────────────────────────────────────────

_DRIVE_PATH_RE = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]")


def _path_forms(p: Path) -> list[str]:
    forms = {str(p), p.as_posix()}
    try:
        r = Path(os.path.abspath(p)).resolve(strict=False)
        forms.update({str(r), r.as_posix()})
    except OSError:
        pass
    return sorted((f for f in forms if f and f not in (".", "/")), key=len, reverse=True)


def scrub_paths(obj: Any, roots: Iterable[tuple[Path, str]]) -> Any:
    """Replace every absolute form of each root (case-insensitive) with its label."""
    pairs = sorted(((form, label) for root, label in roots for form in _path_forms(Path(root))),
                   key=lambda fl: len(fl[0]), reverse=True)

    def fix(s: str) -> str:
        for form, label in pairs:
            s = re.sub(re.escape(form), lambda _m: label, s, flags=re.IGNORECASE)
        return s

    def walk(o: Any) -> Any:
        if isinstance(o, str):
            return fix(o)
        if isinstance(o, dict):
            return {walk(k): walk(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [walk(v) for v in o]
        return o

    return walk(obj)


def assert_no_absolute_path(text: str, roots: Iterable[Path]) -> None:
    lowered = text.lower()
    for root in roots:
        for form in _path_forms(Path(root)):
            if form.lower() in lowered or json.dumps(form)[1:-1].lower() in lowered:
                raise GuardRefusal("absolute path found in isolation.json; refusing to write it")
    if _DRIVE_PATH_RE.search(text) or "/home/" in text or "/Users/" in text:
        raise GuardRefusal("absolute path found in isolation.json; refusing to write it")


def _rel(path: Path | str, base: Path | str) -> str:
    try:
        return Path(os.path.abspath(path)).relative_to(Path(os.path.abspath(base))).as_posix()
    except ValueError:
        return Path(path).name


# ── shared guard steps ───────────────────────────────────────────────────────

def _docker_ready(deps: RunDeps, say: Callable[[str], None], *, allow_start: bool) -> str:
    """Docker engine up (optionally start Docker Desktop), DB container running + healthy."""
    pg = deps.pg

    def engine_ok() -> bool:
        try:
            return pg.run([pg.docker, "info"], what="docker info", timeout=60).returncode == 0
        except GuardRefusal:
            return False

    if not engine_ok():
        if not allow_start:
            raise GuardRefusal("the Docker engine is not running")
        say("Docker engine not running: starting Docker Desktop")
        try:
            deps.start_docker_desktop()
        except Exception as exc:
            raise GuardRefusal(f"could not start Docker Desktop ({type(exc).__name__})") from None
        deadline = deps.now() + dt.timedelta(seconds=deps.docker_wait_seconds)
        while not engine_ok():
            if deps.now() >= deadline:
                raise GuardRefusal(f"the Docker engine did not come up in {deps.docker_wait_seconds:.0f} s")
            deps.sleep(10)
    fmt = "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}"
    deadline = deps.now() + dt.timedelta(seconds=deps.container_wait_seconds)
    while True:
        res = pg.run([pg.docker, "inspect", "-f", fmt, pg.container], what="docker inspect", timeout=60)
        state = res.stdout.strip() if res.returncode == 0 else f"inspect exit {res.returncode}"
        if state.split() in (["running", "healthy"], ["running", "none"]):
            say(f"container {pg.container}: {state}")
            return state
        if deps.now() >= deadline:
            raise GuardRefusal(f"container {pg.container} is not healthy ({state})")
        deps.sleep(5)


def _identity(repo_root: Path, secret_file: Path) -> tuple[DbUrl, str, str, DbUrl]:
    live = live_db_url(repo_root)
    password = read_secret_file(secret_file)
    meas_url = build_meas_url(live, password)
    return live, password, meas_url, parse_db_url(meas_url)


def _secret_values(repo_root: Path, *extra: str) -> list[str]:
    values = [v for v in extra if v]
    try:
        env = read_env_file(Path(repo_root) / ".env")
    except OSError:
        env = {}
    values += [v for k, v in env.items() if _SECRET_ENV_KEY_RE.search(k) and len(v) >= 6]
    return values


def _g1(live: DbUrl, meas: DbUrl, meas_checkout: Path, repo_root: Path, deps: RunDeps) -> list[GuardResult]:
    return g1_checks(live, meas, meas_port=MEAS_PORT, meas_base=MEAS_BASE, meas_checkout=meas_checkout,
                     repo_root=repo_root,
                     list_listeners=lambda: [(a, p) for a, p, _o in deps.list_listener_owners()],
                     tcp_connect=deps.tcp_connect)


def _port_owners(deps: RunDeps, port: int) -> list[tuple[str, int, int | None]]:
    return [(a, int(p), o) for a, p, o in deps.list_listener_owners() if int(p) == port]


def _port_free(deps: RunDeps, port: int = MEAS_PORT) -> GuardResult:
    rule = "meas_port_free"
    try:
        owners = _port_owners(deps, port)
    except Exception as exc:
        return GuardResult(rule, False, f"listener enumeration failed ({type(exc).__name__})")
    connected = []
    for host in ("127.0.0.1", "::1"):
        try:
            if deps.tcp_connect(host, port, timeout=1.0):
                connected.append(host)
        except Exception:
            connected.append(host)
    if owners or connected:
        pids = sorted({o for _a, _p, o in owners if o is not None})
        return GuardResult(rule, False, f"port {port} is in use (listener pid(s) {pids}, connect ok {connected})")
    return GuardResult(rule, True, f"port {port} is free")


def _health_pid(deps: RunDeps, base: str, *, require_ok: bool = False) -> int | None:
    try:
        data = deps.http_get_json(base + HEALTH_PATH, timeout=5.0)
    except Exception:
        return None
    if not isinstance(data, dict) or (require_ok and data.get("ok") is not True):
        return None
    pid = data.get("pid")
    return pid if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0 else None


def _tag_commit(repo_root: Path, deps: RunDeps) -> str:
    res = deps.git(["-C", str(repo_root), "rev-parse", "--verify", f"{TAG}^{{commit}}"])
    sha = res.stdout.strip()
    if res.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise GuardRefusal(f"cannot resolve the tag {TAG} in the repo")
    return sha


def _verify_worktree(meas: Path, tag_commit: str, deps: RunDeps) -> None:
    st = deps.git(["-C", str(meas), "status", "--porcelain", "--untracked-files=no"])
    if st.returncode != 0:
        raise GuardRefusal(f"git status failed in the meas checkout (exit {st.returncode})")
    if st.stdout.strip():
        raise GuardRefusal("the meas checkout has modified tracked files; refusing")
    head = deps.git(["-C", str(meas), "rev-parse", "HEAD"])
    if head.returncode != 0 or head.stdout.strip() != tag_commit:
        raise GuardRefusal(f"the meas checkout HEAD is not the {TAG} commit; refusing")


def _verify_ignored(meas: Path, deps: RunDeps) -> None:
    for rel in RUNTIME_FILES:
        res = deps.git(["-C", str(meas), "check-ignore", "-q", "--", rel.as_posix()])
        if res.returncode == 1:
            raise GuardRefusal(f"{rel.as_posix()} is not gitignored in the meas checkout; refusing to write it")
        if res.returncode != 0:
            raise GuardRefusal(f"git check-ignore failed for {rel.as_posix()} (exit {res.returncode})")


# ── the run (§2.6 steps 1-9) ─────────────────────────────────────────────────

class _IsolatedRun:
    def __init__(self, repo_root: Path, jobs_dir: Path, meas: Path, secret_file: Path, deps: RunDeps):
        self.repo, self.jobs, self.meas, self.secret_file, self.deps = repo_root, jobs_dir, meas, secret_file, deps
        self.secrets: list[str] = _secret_values(repo_root)
        self.start = deps.now()
        self.stamp = self.start.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.python = venv_python(repo_root)
        logs = jobs_dir / "logs"
        self.backend_log = logs / f"meas-{self.stamp}-backend.log"
        self.runner_log = logs / f"meas-{self.stamp}-runner.log"
        self.launched: int | None = None
        self.health_pid: int | None = None
        self.live_before: int | None = None
        self.runner_started = False
        self.runner_start_at: dt.datetime | None = None
        self.day_preexisted: bool | None = None
        self.refusal: str | None = None
        self.failures: list[str] = []
        self.evidence_dir: Path | None = None
        self.et_date: str | None = None
        self.rec: dict[str, Any] = {
            "schema": 1, "tag": TAG, "meas_db": MEAS_DBNAME, "meas_user": MEAS_USER,
            "ports": {"meas": MEAS_PORT, "live": LIVE_PORT, "ibkr": list(IBKR_PORTS)},
            "guards": {}, "timestamps": {"start_utc": _iso(self.start)},
            "paths": {"meas_checkout": _rel(meas, jobs_dir), "backend_log": _rel(self.backend_log, jobs_dir),
                      "runner_log": _rel(self.runner_log, jobs_dir)},
            "live_backend_pid": {"before": None, "after": None},
        }

    # logging
    def say(self, line: str) -> None:
        self.deps.log(redact_text(line, self.secrets))

    def stamp_now(self, key: str) -> None:
        self.rec["timestamps"][key] = _iso(self.deps.now())

    def guards(self, key: str, results: list[GuardResult]) -> list[GuardResult]:
        self.rec["guards"][key] = [r.to_dict() for r in results]
        for r in results:
            self.say(f"{key}: {'ok ' if r.ok else 'FAIL'} {r.rule}: {r.detail}")
        return results

    # step 1
    def step_weekday_and_docker(self) -> None:
        et = to_et(self.start)
        if et.weekday() >= 5:
            raise GuardRefusal(f"{et.date()} is a weekend in New York; no measurement day")
        self.say(f"ET now {et:%Y-%m-%d %H:%M:%S} (weekday)")
        self.rec["docker"] = _docker_ready(self.deps, self.say, allow_start=True)

    # step 2
    def step_guards(self) -> None:
        live, password, meas_url, meas_db = _identity(self.repo, self.secret_file)
        self.live, self.password, self.meas_url = live, password, meas_url
        self.secrets = _secret_values(self.repo, password, live.password)
        self.rec["live_db"] = live.identity()
        self.meas_db = meas_db
        enforce_g1(self.guards("g1", _g1(live, meas_db, self.meas, self.repo, self.deps)))
        enforce_guard("G2", self.guards("g2", check_live_db_refused(live, password, pg=self.deps.pg)))
        enforce_guard("port", self.guards("port", [_port_free(self.deps)]))
        self.live_before = _health_pid(self.deps, LIVE_BASE)
        self.rec["live_backend_pid"]["before"] = self.live_before
        if self.live_before is None:
            self.say(f"live backend on :{LIVE_PORT} absent (no health answer); allowed, continuing")
        else:
            self.say(f"live backend on :{LIVE_PORT} health pid {self.live_before}")

    # step 3
    def step_checkout_files_and_copy(self) -> None:
        deps = self.deps
        self.tag_commit = _tag_commit(self.repo, deps)
        self.rec["tag_commit"] = self.tag_commit
        if not self.meas.exists():
            self.say(f"creating the meas worktree at {self.meas} ({TAG})")
            res = deps.git(["-C", str(self.repo), "worktree", "add", "--detach", str(self.meas), TAG])
            if res.returncode != 0:
                raise GuardRefusal(f"git worktree add failed (exit {res.returncode})")
        _verify_worktree(self.meas, self.tag_commit, deps)
        _verify_ignored(self.meas, deps)

        live_env = read_env_file(self.repo / ".env")
        self.meas_env = meas_dotenv_values(live_env, self.meas_url)
        write_meas_dotenv(self.meas / DOTENV_REL, self.meas_env, expected_database_url=self.meas_url)
        (self.meas / SETTINGS_REL).parent.mkdir(parents=True, exist_ok=True)
        shas = sanitize_settings_file(self.repo / SETTINGS_REL, self.meas / SETTINGS_REL)
        self.rec["settings_sha256"] = {"live": shas["source_sha256"], "sanitized": shas["sanitized_sha256"]}
        src, dst = self.repo / LOCAL_CREDENTIALS_REL, self.meas / LOCAL_CREDENTIALS_REL
        if src.is_file():
            _atomic_write_bytes(dst, src.read_bytes())   # content never printed
            self.rec["local_credentials"] = "copied"
        else:
            dst.unlink(missing_ok=True)
            self.rec["local_credentials"] = "absent in live"
        self.say(f"meas files written (.env, sanitized settings.yaml, local_credentials.yaml: "
                 f"{self.rec['local_credentials']})")
        cache = prepare_confidence_cache(self.repo / CONFIDENCE_CACHE_REL, self.meas / CONFIDENCE_CACHE_REL,
                                         run_start=self.start.timestamp())
        self.rec["confidence_cache"] = cache
        self.say(f"confidence cache: {cache['origin']}, {cache['tag_hittable_rows']} tag-hittable row(s)")

        copy_live_to_meas(self.live, pg=deps.pg)
        self.rec["copy"] = verify_copy(self.live, pg=deps.pg)
        self.say(f"{MEAS_DBNAME} copied and verified; differing counts: {self.rec['copy']['count_differences']}")

    # step 4 (before launch): interpreter facts
    def record_python(self) -> None:
        if not self.python.is_file():
            raise GuardRefusal("the repo venv python is missing")
        ver = self.deps.cmd([str(self.python), "-c", "import sys; print(sys.version)"], timeout=120)
        freeze = self.deps.cmd([str(self.python), "-m", "pip", "freeze"], timeout=600)
        self.rec["python"] = {
            "version": ver.stdout.strip() if ver.returncode == 0 else None,
            "pip_freeze_sha256": (hashlib.sha256(freeze.stdout.encode("utf-8")).hexdigest()
                                  if freeze.returncode == 0 else None),
        }
        if ver.returncode != 0 or freeze.returncode != 0:
            self.say("WARNING: python version or pip freeze unavailable; recorded as null")

    def child_env(self) -> dict[str, str]:
        return build_child_env(self.deps.environ, {**self.meas_env, "PYTHONUTF8": "1"})

    def wait_health(self) -> int:
        deps = self.deps
        deadline = deps.now() + dt.timedelta(seconds=deps.health_timeout_seconds)
        while True:
            pid = _health_pid(deps, MEAS_BASE, require_ok=True)
            if pid is not None:
                return pid
            if deps.now() >= deadline:
                raise GuardRefusal(f"the frozen backend did not report healthy on :{MEAS_PORT} "
                                   f"within {deps.health_timeout_seconds:.0f} s")
            deps.sleep(deps.health_poll_seconds)

    # G3 (§2.3)
    def g3(self, key: str) -> list[GuardResult]:
        deps = self.deps
        out: list[GuardResult] = []
        pid = _health_pid(deps, MEAS_BASE)
        if pid is None:
            out.append(GuardResult("g3_health_pid_descendant", False, f"no health pid on :{MEAS_PORT}"))
        else:
            ok = is_descendant_or_self(pid, self.launched, deps.parent_pid)
            out.append(GuardResult("g3_health_pid_descendant", ok,
                                   f"health pid {pid} {'is' if ok else 'is NOT'} the launched pid "
                                   f"{self.launched} or a descendant of it"))
        out.append(GuardResult("g3_health_pid_stable", pid is not None and pid == self.health_pid,
                               f"health pid {pid}, at start {self.health_pid}"))
        try:
            owners = _port_owners(deps, MEAS_PORT)
            ok = (pid is not None and bool(owners) and all(o == pid for _a, _p, o in owners)
                  and any(a == MEAS_HOST for a, _p, _o in owners))
            out.append(GuardResult("g3_listener_owner", ok,
                                   f"{MEAS_HOST}:{MEAS_PORT} listeners {[(a, o) for a, _p, o in owners]}, "
                                   f"health pid {pid}"))
        except Exception as exc:
            out.append(GuardResult("g3_listener_owner", False, f"listener enumeration failed ({type(exc).__name__})"))
        out.append(meas_connections_ok(pg=deps.pg))
        live_now = _health_pid(deps, LIVE_BASE)
        self.rec["live_backend_pid"]["after"] = live_now
        if self.live_before is None:
            out.append(GuardResult("g3_live_backend_pid_unchanged", True,
                                   f"live backend was absent before the run (now {live_now})"))
        else:
            out.append(GuardResult("g3_live_backend_pid_unchanged", live_now == self.live_before,
                                   f"live :{LIVE_PORT} health pid {live_now}, before the run {self.live_before}"))
        out += [r for r in _g1(self.live, self.meas_db, self.meas, self.repo, deps) if r.rule.startswith("ibkr_")]
        return self.guards(key, out)

    def wait_until_run_time(self) -> None:
        deps = self.deps
        et_now = to_et(deps.now())
        target = dt.datetime.combine(et_now.date(), RUN_AT_ET)
        if et_now >= target:
            self.say(f"already past 13:00:30 ET ({et_now:%H:%M:%S}); skipping the wait")
            return
        self.say(f"waiting {(target - et_now).total_seconds():.0f} s for 13:00:30 ET")
        while et_now < target:
            deps.sleep(min((target - et_now).total_seconds(), 60.0))
            et_now = to_et(deps.now())

    def run_runner(self) -> int:
        runner = self.meas / RUNNER_REL
        argv = [str(self.python), str(runner), "core", "--base", MEAS_BASE, "--repo", str(self.meas)]
        self.runner_start_at = self.deps.now()
        self.et_date = to_et(self.runner_start_at).date().isoformat()
        self.rec["et_date"] = self.et_date
        self.rec["runner"] = {"argv": ["<repo venv python>", f"<meas>/{RUNNER_REL.as_posix()}", "core",
                                       "--base", MEAS_BASE, "--repo", "<meas>"], "exit_code": None}
        # F1: only a day folder the runner creates in THIS run is evidence of this run
        self.day_preexisted = (self.meas / SCANS_REL / self.et_date).exists()
        self.rec["timestamps"]["runner_start_utc"] = _iso(self.runner_start_at)
        self.runner_started = True
        self.say("starting the tag runner (core)")
        code = self.deps.run_runner(argv, cwd=self.meas, env=self.child_env(), log_path=self.runner_log)
        self.stamp_now("runner_end_utc")
        self.rec["runner"]["exit_code"] = code
        self.say(f"tag runner exit code {code}")
        if code != 0:
            self.failures.append(f"the tag runner exited with {code}")
        return code

    # step 7: the only stop path
    def stop(self) -> None:
        deps, launched = self.deps, self.launched
        assert launched is not None
        results: list[GuardResult] = []
        self.say(f"stopping the frozen backend: taskkill /F /T /PID {launched}")
        try:
            kr = deps.kill_tree(launched)
            results.append(GuardResult("stop_taskkill", kr.returncode == 0,
                                       f"forced tree kill of launched pid {launched}: exit {kr.returncode}"))
        except Exception as exc:
            results.append(GuardResult("stop_taskkill", False, f"kill of pid {launched} failed "
                                                               f"({type(exc).__name__})"))
        pids = sorted({p for p in (launched, self.health_pid) if p})
        deadline = deps.now() + dt.timedelta(seconds=deps.stop_verify_seconds)
        while True:
            try:
                owners: list | None = _port_owners(deps, MEAS_PORT)
            except Exception:
                owners = None
            alive = []
            for p in pids:
                try:
                    if deps.pid_exists(p):
                        alive.append(p)
                except Exception:
                    alive.append(p)
            if owners == [] and not alive:
                break
            if deps.now() >= deadline:
                break
            deps.sleep(1.0)
        if owners is None:
            results.append(GuardResult("stop_port_free", False, f"could not enumerate :{MEAS_PORT} listeners"))
        else:
            results.append(GuardResult(
                "stop_port_free", not owners,
                (f"port {MEAS_PORT} still has listener(s) owned by pid(s) {sorted({o for _a, _p, o in owners})}; "
                 "nothing is ever stopped by port: check by hand") if owners else f"nothing listens on {MEAS_PORT}"))
        results.append(GuardResult("stop_pids_gone", not alive,
                                   f"pid(s) {alive} still exist" if alive else f"pid(s) {pids} gone"))
        self.guards("stop", results)
        self.stamp_now("stopped_utc")
        failed = [r for r in results if not r.ok]
        if failed:
            msg = "stop verification failed: " + "; ".join(f"{r.rule} ({r.detail})" for r in failed)
            self.say("WARNING: " + msg)
            self.failures.append(msg)

    def start_measure_stop(self) -> None:
        deps = self.deps
        self.record_python()
        (self.jobs / "logs").mkdir(parents=True, exist_ok=True)
        argv = [str(self.python), "-m", "uvicorn", "app.main:app", "--ws", "websockets-sansio",
                "--host", MEAS_HOST, "--port", str(MEAS_PORT)]
        self.say(f"starting the frozen backend on {MEAS_HOST}:{MEAS_PORT}")
        self.launched = deps.launch(argv, cwd=self.meas / "backend", env=self.child_env(),
                                    log_path=self.backend_log)
        self.rec["meas_backend"] = {"launched_pid": self.launched, "health_pid": None}
        self.stamp_now("launched_utc")
        try:
            self.health_pid = self.wait_health()
            self.rec["meas_backend"]["health_pid"] = self.health_pid
            self.stamp_now("backend_healthy_utc")
            self.say(f"frozen backend healthy, health pid {self.health_pid} (launched {self.launched})")
            enforce_guard("G3 before the first scan", self.g3("g3_start"))
            self.wait_until_run_time()
            self.run_runner()
            g3_end = self.g3("g3_end")
            failed = [r for r in g3_end if not r.ok]
            if failed:
                self.failures.append("G3 at the end failed: " + "; ".join(f"{r.rule} ({r.detail})" for r in failed))
        finally:
            self.stop()

    # step 8
    def _not_this_run(self, src: Path) -> str | None:
        """Why the meas day folder is not this run's evidence, or None if it is: it must
        not have existed before the tag runner started, must exist now, and its
        manifest.json ``started_at.utc`` must be at or after the runner start."""
        day = f"scans/{self.et_date}"
        if self.day_preexisted is not False or self.runner_start_at is None:
            return (f"the day folder {day} in the meas checkout predates this run (it existed before the "
                    "tag runner started); not copied")
        if not src.is_dir():
            return f"the runner wrote no day folder {day} in the meas checkout"
        try:
            manifest = json.loads((src / "manifest.json").read_text(encoding="utf-8"))
            started = dt.datetime.fromisoformat(manifest["started_at"]["utc"])
            if started.tzinfo is None:
                raise ValueError("naive timestamp")
        except Exception as exc:
            return (f"the manifest start in {day}/manifest.json is unreadable ({type(exc).__name__}); "
                    "not copied")
        if started < self.runner_start_at:
            return (f"the manifest start {_iso(started)} in {day}/manifest.json is before the runner start "
                    f"{_iso(self.runner_start_at)}; not copied")
        return None

    def copy_day(self) -> None:
        src = self.meas / SCANS_REL / str(self.et_date)
        reason = self._not_this_run(src)
        if reason is not None:
            self.failures.append(reason)
            self.say("WARNING: " + reason)
            return
        self.evidence_dir = copy_evidence(src, self.repo / SCANS_REL, str(self.et_date), self.stamp, log=self.say)
        self.rec["paths"]["evidence_dir"] = _rel(self.evidence_dir, self.repo)
        self.say(f"evidence copied to {self.rec['paths']['evidence_dir']}")

    def execute(self) -> RunResult:
        try:
            self.step_weekday_and_docker()
            self.step_guards()
            self.step_checkout_files_and_copy()
            self.start_measure_stop()
            self.copy_day()
        except GuardRefusal as exc:
            self.refusal = str(exc)
        except Exception as exc:  # never a traceback (it could carry a secret); type + redacted text
            self.refusal = f"unexpected error: {type(exc).__name__}: {exc}"
            self.failures.append(self.refusal)
        return self.finish()

    def finish(self) -> RunResult:
        if self.refusal is not None:
            code = EXIT_FAILED if (self.runner_started or self.refusal in self.failures) else EXIT_REFUSED
            if self.refusal not in self.failures:
                self.failures.insert(0, self.refusal)
        else:
            code = EXIT_FAILED if self.failures else EXIT_OK
        self.rec["exit_code"] = code
        self.rec["failures"] = list(self.failures)
        self.stamp_now("end_utc")
        roots = [(self.meas, "<meas>"), (self.jobs, "<jobs>"), (self.repo, "<repo>"), (Path.home(), "~")]
        record = scrub_paths(redact(self.rec, self.secrets), roots)
        if self.evidence_dir is not None:
            try:
                text = json.dumps(record, indent=2, sort_keys=True) + "\n"
                assert_no_secret(text, self.secrets)
                assert_no_absolute_path(text, [r for r, _l in roots])
                with open(self.evidence_dir / "isolation.json", "x", encoding="utf-8", newline="\n") as f:
                    f.write(text)
            except (GuardRefusal, OSError) as exc:
                self.say(f"WARNING: isolation.json not written: {type(exc).__name__}: {exc}")
                code = EXIT_FAILED
        error = "; ".join(self.failures) if self.failures else None
        error = redact_text(error, self.secrets) if error else None
        verdict = {EXIT_OK: "OK", EXIT_FAILED: "FAILED", EXIT_REFUSED: "REFUSED"}[code]
        self.say(f"RESULT {verdict} (exit {code})" + (f": {error}" if error else ""))
        return RunResult(exit_code=code, error=error, isolation=record, evidence_dir=self.evidence_dir)


def run_isolated_day(*, repo_root: Path | str = REPO_ROOT, jobs_dir: Path | str = JOBS_DIR,
                     meas_checkout: Path | str | None = None, secret_file: Path | str | None = None,
                     deps: RunDeps | None = None) -> RunResult:
    """One isolated MEAS day (plan §2.6 steps 1-9). Refuses (exit 2, nothing
    started) on any guard before the start; after the start, every exit path
    stops the frozen backend by its launched PID (forced tree kill). The live
    backend, main checkout and live DB are never stopped, switched or written."""
    repo_root, jobs_dir = Path(repo_root), Path(jobs_dir)
    meas = Path(meas_checkout) if meas_checkout is not None else jobs_dir / TAG
    secret = Path(secret_file) if secret_file is not None else jobs_dir / "meas_db.secret"
    return _IsolatedRun(repo_root, jobs_dir, meas, secret, deps or RunDeps()).execute()


# ── check: every guard, nothing started, nothing written ─────────────────────

def check_isolated_day(*, repo_root: Path | str = REPO_ROOT, jobs_dir: Path | str = JOBS_DIR,
                       meas_checkout: Path | str | None = None, deps: RunDeps | None = None) -> int:
    deps = deps or RunDeps()
    repo_root, jobs_dir = Path(repo_root), Path(jobs_dir)
    meas = Path(meas_checkout) if meas_checkout is not None else jobs_dir / TAG
    secrets_ = _secret_values(repo_root)

    def say(line: str) -> None:
        deps.log(redact_text(line, secrets_))

    try:
        _docker_ready(deps, say, allow_start=False)
        live, password, _url, meas_db = _identity(repo_root, jobs_dir / "meas_db.secret")
        secrets_ += [password, live.password]
        results = (_g1(live, meas_db, meas, repo_root, deps)
                   + check_live_db_refused(live, password, pg=deps.pg) + [_port_free(deps)])
        for r in results:
            say(f"check: {'ok ' if r.ok else 'FAIL'} {r.rule}: {r.detail}")
        enforce_guard("check", results)
        live_pid = _health_pid(deps, LIVE_BASE)
        say(f"live backend on :{LIVE_PORT}: " + (f"health pid {live_pid}" if live_pid else "absent"))
        tag_commit = _tag_commit(repo_root, deps)
        if meas.exists():
            _verify_worktree(meas, tag_commit, deps)
            _verify_ignored(meas, deps)
            say(f"meas checkout clean at {TAG}; runtime files gitignored")
        else:
            say("meas checkout absent; `run` creates it")
    except GuardRefusal as exc:
        say(f"REFUSED: {exc}")
        return EXIT_REFUSED
    say("check OK: every guard passes (nothing was started or written)")
    return EXIT_OK


# ── cleanup: drop the copy, remove the runtime files ─────────────────────────

def cleanup_isolated_day(*, repo_root: Path | str = REPO_ROOT, jobs_dir: Path | str = JOBS_DIR,
                         meas_checkout: Path | str | None = None, reset_cache: bool = False,
                         deps: RunDeps | None = None) -> int:
    """Drop ``bamendjou_meas`` and remove the meas .env, sanitized settings.yaml and
    copied local_credentials.yaml. The confidence cache is kept unless
    ``reset_cache`` (logged). Refuses while anything listens on :8100."""
    deps = deps or RunDeps()
    repo_root, jobs_dir = Path(repo_root), Path(jobs_dir)
    meas = Path(meas_checkout) if meas_checkout is not None else jobs_dir / TAG
    log = deps.log
    try:
        if path_is_inside(meas, repo_root):
            raise GuardRefusal("the meas checkout is inside the repo root; refusing to delete anything")
        enforce_guard("cleanup", [_port_free(deps)])
        live = live_db_url(repo_root)
        _check_live_identity(live, deps.pg)
        deps.pg.superuser_sql(f"/* meas:drop */ DROP DATABASE IF EXISTS {quote_ident(MEAS_DBNAME)} WITH (FORCE);\n",
                              dbname=deps.pg.maintenance_db, read_only=False, what=f"drop {MEAS_DBNAME}",
                              secret_values=[live.password])
        log(f"dropped {MEAS_DBNAME}")
        for rel in (DOTENV_REL, SETTINGS_REL, LOCAL_CREDENTIALS_REL):
            target = meas / rel
            existed = target.exists()
            target.unlink(missing_ok=True)
            log(f"{'removed' if existed else 'absent'}: <meas>/{rel.as_posix()}")
        cache = meas / CONFIDENCE_CACHE_REL
        if reset_cache:
            for p in (cache, cache.with_name(cache.name + "-wal"), cache.with_name(cache.name + "-shm")):
                p.unlink(missing_ok=True)
            log(f"confidence cache RESET: removed <meas>/{CONFIDENCE_CACHE_REL.as_posix()} (--reset-cache)")
        else:
            log("confidence cache kept (only --reset-cache removes it)")
    except GuardRefusal as exc:
        log(f"REFUSED: {exc}")
        return EXIT_REFUSED
    return EXIT_OK


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None, *, deps: RunDeps | None = None) -> int:
    ap = argparse.ArgumentParser(prog="isolated_day.py",
                                 description="Isolated MEAS day orchestrator (plan 2026-10-13, #230).")
    sub = ap.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
        p.add_argument("--repo-root", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
        p.add_argument("--jobs-dir", type=Path, default=JOBS_DIR, help=argparse.SUPPRESS)
        return p

    p_setup = common(sub.add_parser("setup", help="one-time: meas role + DB + REVOKE on live (needs approval)"))
    p_setup.add_argument("--i-have-kenneths-approval", dest="approved", action="store_true",
                         help="confirm Kenneth explicitly approved changing live DB privileges")
    p_setup.add_argument("--rotate", action="store_true", help="generate a new meas password")
    common(sub.add_parser("check", help="run every guard; start nothing"))
    common(sub.add_parser("run", help="one isolated measurement day"))
    p_cleanup = common(sub.add_parser("cleanup", help="drop the copy DB, remove meas runtime files"))
    p_cleanup.add_argument("--reset-cache", action="store_true", help="also delete the meas confidence cache")
    args = ap.parse_args(argv)
    deps = deps or RunDeps()
    repo_root, jobs_dir = Path(args.repo_root), Path(args.jobs_dir)

    if args.command == "setup":
        deps.log(SETUP_WARNING)
        if not args.approved:
            deps.log("REFUSED: setup needs --i-have-kenneths-approval")
            return EXIT_REFUSED
        try:
            live = live_db_url(repo_root)
            result = setup(live, jobs_dir / "meas_db.secret", rotate=args.rotate, pg=deps.pg, log=deps.log)
        except GuardRefusal as exc:
            deps.log(f"REFUSED: {exc}")
            return EXIT_REFUSED
        deps.log(json.dumps(result, indent=2))
        return EXIT_OK
    if args.command == "check":
        return check_isolated_day(repo_root=repo_root, jobs_dir=jobs_dir, deps=deps)
    if args.command == "cleanup":
        return cleanup_isolated_day(repo_root=repo_root, jobs_dir=jobs_dir, reset_cache=args.reset_cache,
                                    deps=deps)
    return run_isolated_day(repo_root=repo_root, jobs_dir=jobs_dir, deps=deps).exit_code


if __name__ == "__main__":
    sys.exit(main())
