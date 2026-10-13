"""Isolated MEAS day orchestrator: config layer and the G1 config guard.

Plan: docs/superpowers/plans/2026-10-13-meas-live-db-isolation-plan.md (#230).
This module is ticket T1 (#281): §2.2 fixed names, §2.3 G1, §2.4 the files the
orchestrator writes into the meas checkout, the child environment, the secret
file and the confidence-cache seed/carry-over (§2.4 [v3 R2-1], §2.7). Ticket T2
(#282) adds the DB layer at the end of the file: one-time ``setup`` (§2.3 G2),
the per-run copy and its verification (§2.5), the G2 probe and the G3 DB probe.
The run sequence (run / check / cleanup, T3) is added on top of it.

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

import copy
import getpass
import hashlib
import json
import os
import re
import secrets
import shlex
import socket
import sqlite3
import subprocess
import sys
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
