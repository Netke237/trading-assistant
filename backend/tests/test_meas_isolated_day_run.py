"""Tests for scripts/meas/isolated_day.py: the run sequence (#283, plan
docs/superpowers/plans/2026-10-13-meas-live-db-isolation-plan.md §2.3 G3 process
identity, §2.4, §2.6, §2.7, T3).

Nothing real is started, stopped or connected: every side effect goes through
the ``RunDeps`` seams, faked here by one in-memory ``World`` (clock, docker /
Postgres answers keyed on the T2 SQL tags, processes with parent PIDs, TCP
listeners with owner PIDs, health endpoints, git, the tag runner). The
assertions pin the plan's order of operations, every refusal, the forced
tree-kill of the *launched* PID (never by port) on every post-start refusal,
the evidence copy that never overwrites, and an ``isolation.json`` without
secrets or absolute user paths.

All credentials are synthetic. scripts/ is not a package, so the module is
loaded by path, matching the T1/T2 test files.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import pytest

_SCRIPT_PATH = Path(__file__).parent.parent.parent / "scripts" / "meas" / "isolated_day.py"
_PS1_PATH = _SCRIPT_PATH.with_name("run_isolated_day.ps1")
if "meas_isolated_day" in sys.modules:
    iso = sys.modules["meas_isolated_day"]
else:
    _spec = importlib.util.spec_from_file_location("meas_isolated_day", _SCRIPT_PATH)
    iso = importlib.util.module_from_spec(_spec)
    sys.modules["meas_isolated_day"] = iso  # dataclasses resolve their module by name
    _spec.loader.exec_module(iso)  # type: ignore[union-attr]


LIVE_PW = "LivePw-Synthetic-123"
MEAS_PW = "MeasPw_synthetic_TOKEN_abcdef0123456789"
TRADIER_TOKEN = "tradier-synthetic-token-777"
TIINGO_TOKEN = "tiingo-synthetic-token-888"
TELEGRAM_TOKEN = "telegram-synthetic-token-999"
CRED_SECRET = "credfile-synthetic-secret-555"
SMTP_SECRET = "smtp-synthetic-secret-444"
LIVE_DB = "TradingAssistantDB"
LIVE_URL = f"postgresql+asyncpg://bamendjou:{LIVE_PW}@localhost:5433/{LIVE_DB}"
ALL_SECRETS = [LIVE_PW, MEAS_PW, TRADIER_TOKEN, TIINGO_TOKEN, TELEGRAM_TOKEN, CRED_SECRET, SMTP_SECRET]

TAG_SHA = "61a03e49975a9384f72597a9148848d979769548"
LAUNCHED = 7100
CHILD = 7101       # the real interpreter under the venv launcher
LIVE_PID = 4242
# Wednesday 2026-10-14 12:00 EDT
START = dt.datetime(2026, 10, 14, 16, 0, 0, tzinfo=dt.timezone.utc)
ET_DATE = "2026-10-14"

PERMISSION_DENIED = (
    'psql: error: connection to server at "127.0.0.1", port 5432 failed: '
    f'FATAL:  permission denied for database "{LIVE_DB}"\n'
)


def _ok(stdout: str = "") -> Any:
    return iso.CmdResult(0, stdout, "")


# ── the fake world ───────────────────────────────────────────────────────────

@dataclass
class World:
    tmp: Path
    now: dt.datetime = START
    events: list[str] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    procs: dict[int, int] = field(default_factory=lambda: {LIVE_PID: 1, 1: 0})
    listeners: list[tuple[str, int, int]] = field(default_factory=lambda: [
        ("0.0.0.0", 135, 900), ("127.0.0.1", 8000, LIVE_PID)])
    connectable: set[tuple[str, int]] = field(default_factory=set)
    live_pid: int | None = LIVE_PID
    # meas backend behaviour
    health_after_polls: int = 2
    health_polls: int = 0
    meas_health_pid: int = CHILD
    listener_owner: int | None = None     # None: the child owns 127.0.0.1:8100
    launched: bool = False
    # docker / postgres
    docker_up: bool = True
    container_state: str = "running healthy"
    g2_connect: Any = None
    activity: dict[str, int] = field(default_factory=lambda: {"bamendjou_meas": 3})
    # git
    worktree_exists: bool = False
    status_out: str = ""
    head_sha: str = TAG_SHA
    not_ignored: set[str] = field(default_factory=set)
    git_calls: list[list[str]] = field(default_factory=list)
    # runner
    runner_exit: int = 0
    runner_writes_day: bool = True
    # what the fake runner stamps as manifest.json "started_at.utc" (None: the clock at its start);
    # "absent" writes a manifest without started_at
    manifest_started_at: Any = None
    hooks: dict[str, Callable[["World"], None]] = field(default_factory=dict)
    # recorded calls
    launch_calls: list[dict] = field(default_factory=list)
    runner_calls: list[dict] = field(default_factory=list)
    kill_calls: list[int] = field(default_factory=list)
    docker_calls: list[list[str]] = field(default_factory=list)

    @property
    def repo(self) -> Path:
        return self.tmp / "repo"

    @property
    def jobs(self) -> Path:
        return self.tmp / "jobs"

    @property
    def meas(self) -> Path:
        return self.jobs / iso.TAG

    def _hook(self, name: str) -> None:
        fn = self.hooks.get(name)
        if fn:
            fn(self)

    # clock
    def clock(self) -> dt.datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.events.append("sleep")
        self.now += dt.timedelta(seconds=seconds)

    # docker / postgres (T2 PgDocker runner)
    def docker(self, argv, *, input=None, env=None, timeout=None):
        argv = list(argv)
        self.docker_calls.append(argv)
        if argv[1:2] == ["info"]:
            self.events.append("docker:info")
            return _ok("ok") if self.docker_up else iso.CmdResult(1, "", "no engine")
        if argv[1:2] == ["inspect"]:
            self.events.append("docker:inspect")
            return _ok(self.container_state + "\n")
        if argv[-1].startswith("st=$(mktemp)"):
            self.events.append("db:dump-restore")
            return _ok()
        if "meas_runner" in argv and "-U" in argv:
            self.events.append("g2:connect")
            return self.g2_connect or iso.CmdResult(2, "", PERMISSION_DENIED)
        m = re.search(r"/\* (meas:[a-z0-9-]+) \*/", input or "")
        tag = m.group(1) if m else None
        self.events.append(f"sql:{tag}")
        if tag == "meas:g2-role":
            return _ok(json.dumps({"exists": True, "rolsuper": False}))
        if tag == "meas:g3-activity":
            return _ok(json.dumps(self.activity))
        if tag == "meas:drop-create":
            return _ok()
        if tag == "meas:drop":
            return _ok()
        if tag == "meas:tables":
            return _ok(json.dumps(["alembic_version", "ohlcv_daily"]))
        if tag == "meas:counts":
            return _ok(json.dumps({"alembic_version": 1, "ohlcv_daily": 1000}))
        if tag == "meas:ohlcv":
            return _ok(json.dumps({"count": 1000, "min": "2009-01-02", "max": "2026-10-13"}))
        if tag == "meas:alembic":
            return _ok(json.dumps(["8ee11537abcd"]))
        raise AssertionError(f"unexpected docker call {argv} tag={tag}")

    def start_docker_desktop(self) -> None:
        self.events.append("docker:start-desktop")
        self.docker_up = True

    # processes
    def launch(self, argv, *, cwd, env, log_path):
        self.events.append("launch")
        self.launch_calls.append({"argv": list(argv), "cwd": Path(cwd), "env": dict(env),
                                  "log_path": Path(log_path)})
        self.launched = True
        self.procs[LAUNCHED] = 1
        self.procs[CHILD] = LAUNCHED
        owner = self.listener_owner if self.listener_owner is not None else CHILD
        if owner not in self.procs:
            self.procs[owner] = 1
        self.listeners.append(("127.0.0.1", 8100, owner))
        if self.meas_health_pid not in self.procs:
            self.procs[self.meas_health_pid] = 1
        return LAUNCHED

    def parent_pid(self, pid: int):
        return self.procs.get(pid)

    def pid_exists(self, pid: int) -> bool:
        return pid in self.procs

    def kill_tree(self, pid: int):
        self.events.append("kill")
        self.kill_calls.append(pid)
        doomed = {pid}
        changed = True
        while changed:
            changed = False
            for p, parent in list(self.procs.items()):
                if parent in doomed and p not in doomed:
                    doomed.add(p)
                    changed = True
        for p in doomed:
            self.procs.pop(p, None)
        self.listeners = [entry for entry in self.listeners if entry[2] not in doomed]
        return _ok("SUCCESS")

    def list_listener_owners(self):
        self.events.append("listeners")
        return list(self.listeners)

    def tcp_connect(self, host, port, timeout=1.0):
        return (host, port) in self.connectable

    # http
    def http_get_json(self, url: str, timeout: float = 5.0):
        if ":8000/" in url:
            self.events.append("health:8000")
            if self.live_pid is None:
                raise OSError("connection refused")
            return {"ok": True, "pid": self.live_pid}
        if ":8100/" in url:
            self.events.append("health:8100")
            if not self.launched:
                raise OSError("connection refused")
            self.health_polls += 1
            if self.health_polls < self.health_after_polls:
                raise OSError("connection refused")
            if self.meas_health_pid not in self.procs:
                raise OSError("connection refused")
            return {"ok": True, "pid": self.meas_health_pid}
        raise AssertionError(url)

    # git
    def git(self, args):
        args = list(args)
        self.git_calls.append(args)
        if "worktree" in args and "add" in args:
            self.events.append("git:worktree-add")
            self.worktree_exists = True
            _make_meas_tree(self.meas)
            return _ok()
        if "status" in args:
            self.events.append("git:status")
            return _ok(self.status_out)
        if "rev-parse" in args:
            self.events.append("git:rev-parse")
            if any(a.startswith(iso.TAG) for a in args):
                return _ok(TAG_SHA + "\n")
            return _ok(self.head_sha + "\n")
        if "check-ignore" in args:
            self.events.append("git:check-ignore")
            rel = args[-1]
            return iso.CmdResult(1, "", "") if rel in self.not_ignored else _ok(rel + "\n")
        raise AssertionError(f"unexpected git {args}")

    # the tag runner
    def run_runner(self, argv, *, cwd, env, log_path):
        self.events.append("runner")
        self.runner_calls.append({"argv": list(argv), "cwd": Path(cwd), "env": dict(env),
                                  "log_path": Path(log_path), "now": self.now})
        day = self.meas / "docs" / "superpowers" / "measurements" / "scans" / ET_DATE
        if day.exists():
            # the tag runner's cmd_core: "<folder> already exists -- never overwritten", exit 2
            self._hook("runner")
            return 2
        if self.runner_writes_day:
            day.mkdir(parents=True)
            manifest: dict[str, Any] = {"status": "done"}
            if self.manifest_started_at != "absent":
                started = self.manifest_started_at or self.now
                manifest["started_at"] = {"utc": started.isoformat(), "et": "unused"}
            (day / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        self._hook("runner")
        return self.runner_exit

    # python version / pip freeze
    def cmd(self, argv, **_kw):
        argv = list(argv)
        if argv[1:3] == ["-m", "pip"]:
            self.events.append("pip-freeze")
            return _ok("fastapi==0.110.0\nuvicorn==0.29.0\n")
        if argv[1:2] == ["-c"]:
            self.events.append("python-version")
            return _ok("3.11.9 (tags/v3.11.9, Apr  2 2024) [MSC v.1938 64 bit (AMD64)]\n")
        raise AssertionError(f"unexpected cmd {argv}")

    def deps(self, **overrides):
        kw = dict(
            now=self.clock, sleep=self.sleep, pg=iso.PgDocker(runner=self.docker),
            launch=self.launch, http_get_json=self.http_get_json,
            list_listener_owners=self.list_listener_owners, parent_pid=self.parent_pid,
            pid_exists=self.pid_exists, kill_tree=self.kill_tree, git=self.git,
            run_runner=self.run_runner, cmd=self.cmd, start_docker_desktop=self.start_docker_desktop,
            tcp_connect=self.tcp_connect, log=self.logs.append,
            environ={"PATH": "/usr/bin", "DATABASE_URL": LIVE_URL, "PGPASSWORD": LIVE_PW,
                     "BAMENDJOU_TELEGRAM_BOT_TOKEN": TELEGRAM_TOKEN, "SystemRoot": "C:\\Windows"},
        )
        kw.update(overrides)
        return iso.RunDeps(**kw)


def _make_meas_tree(meas: Path) -> None:
    (meas / "docs" / "superpowers" / "measurements").mkdir(parents=True, exist_ok=True)
    (meas / "docs" / "superpowers" / "measurements" / "run_measurement_day.py").write_text("# tag runner\n")
    (meas / "backend" / "config").mkdir(parents=True, exist_ok=True)
    (meas / "backend" / "data").mkdir(parents=True, exist_ok=True)


def _make_repo(repo: Path) -> None:
    (repo / "backend" / "config").mkdir(parents=True)
    (repo / "backend" / "data").mkdir(parents=True)
    venv = iso.venv_python(repo)
    venv.parent.mkdir(parents=True, exist_ok=True)
    venv.write_text("")
    (repo / ".env").write_text(
        f"DATABASE_URL={LIVE_URL}\nTRADIER_API_TOKEN={TRADIER_TOKEN}\n"
        f"TRADIER_BASE_URL=https://api.tradier.com\nTIINGO_API_TOKEN={TIINGO_TOKEN}\n"
        f"BAMENDJOU_TELEGRAM_BOT_TOKEN={TELEGRAM_TOKEN}\n", encoding="utf-8")
    (repo / "backend" / "config" / "settings.yaml").write_text(
        "alert_delivery:\n  masterEnabled: true\n"
        "notifications:\n  gmail:\n    enabled: true\n"
        f"    smtp_password: {SMTP_SECRET}\n  telegram:\n    enabled: true\n"
        f"    bot_token: {TELEGRAM_TOKEN}\n"
        "scan:\n  schedule:\n    enabled: true\ntheme: dark\n", encoding="utf-8")
    (repo / "backend" / "config" / "local_credentials.yaml").write_text(
        f"tastytrade:\n  password: {CRED_SECRET}\n", encoding="utf-8")
    (repo / "backend" / "config" / "scan_schedule.yaml").write_text("entries: []\n", encoding="utf-8")
    conn = sqlite3.connect(repo / "backend" / "data" / "confidence_cache.db")
    conn.execute("CREATE TABLE confidence_cache (cache_key TEXT PRIMARY KEY, expires_at REAL, payload TEXT)")
    conn.execute("INSERT INTO confidence_cache VALUES ('A|b|c|d|e', ?, '{}')", (START.timestamp() + 86400,))
    conn.execute("INSERT INTO confidence_cache VALUES ('A|b|c|d|e|b3', ?, '{}')", (START.timestamp() + 86400,))
    conn.commit()
    conn.close()


@pytest.fixture
def world(tmp_path):
    w = World(tmp=tmp_path)
    _make_repo(w.repo)
    w.jobs.mkdir()
    (w.jobs / "meas_db.secret").write_text(MEAS_PW + "\n", encoding="utf-8")
    return w


def _run(world: World, **deps_overrides):
    return iso.run_isolated_day(repo_root=world.repo, jobs_dir=world.jobs,
                                deps=world.deps(**deps_overrides))


def _first(events: list[str], name: str) -> int:
    assert name in events, f"{name} not in {events}"
    return events.index(name)


def _isolation(res) -> dict:
    assert res.evidence_dir is not None
    return json.loads((res.evidence_dir / "isolation.json").read_text(encoding="utf-8"))


# ── module hygiene ───────────────────────────────────────────────────────────

def test_module_still_never_imports_app():
    src = _SCRIPT_PATH.read_text(encoding="utf-8")
    assert "import app" not in src and "from app" not in src


def test_run_entry_point_name_is_pinned():
    assert re.search(r"^def run_isolated_day\(", _SCRIPT_PATH.read_text(encoding="utf-8"), re.M)


def test_nothing_is_ever_stopped_by_port_or_name():
    src = _SCRIPT_PATH.read_text(encoding="utf-8")
    assert "Stop-Process" not in src
    assert "/IM" not in src
    assert src.count('"taskkill"') == 1   # only taskkill_argv builds the command


def test_taskkill_argv_is_forced_tree_kill_by_pid():
    assert iso.taskkill_argv(1234) == ["taskkill", "/F", "/T", "/PID", "1234"]
    with pytest.raises(iso.GuardRefusal):
        iso.taskkill_argv(0)


def test_default_kill_tree_uses_taskkill_on_windows(monkeypatch):
    seen = []
    monkeypatch.setattr(iso.sys, "platform", "win32")
    res = iso.kill_process_tree(555, runner=lambda argv, **kw: seen.append(argv) or _ok())
    assert seen == [["taskkill", "/F", "/T", "/PID", "555"]] and res.returncode == 0


def test_to_et_matches_us_dst_rules():
    assert iso.to_et(START) == dt.datetime(2026, 10, 14, 12, 0, 0)
    winter = dt.datetime(2026, 12, 1, 18, 0, tzinfo=dt.timezone.utc)
    assert iso.to_et(winter) == dt.datetime(2026, 12, 1, 13, 0, 0)


# ── Windows parsers (PowerShell JSON) ────────────────────────────────────────

def test_parse_listener_owners_json():
    text = json.dumps([{"LocalAddress": "127.0.0.1", "LocalPort": 8100, "OwningProcess": 7101},
                       {"LocalAddress": "::", "LocalPort": 135, "OwningProcess": 900}])
    assert iso.parse_listener_owners_json(text) == [("127.0.0.1", 8100, 7101), ("::", 135, 900)]
    one = json.dumps({"LocalAddress": "0.0.0.0", "LocalPort": 5000, "OwningProcess": 3})
    assert iso.parse_listener_owners_json(one) == [("0.0.0.0", 5000, 3)]
    for bad in ("", "nope", json.dumps([{"LocalPort": 1}])):
        with pytest.raises(ValueError):
            iso.parse_listener_owners_json(bad)


def test_parse_process_json():
    assert iso.parse_process_json(json.dumps({"ProcessId": 7101, "ParentProcessId": 7100})) == 7100
    assert iso.parse_process_json("") is None
    assert iso.parse_process_json("   \n") is None
    with pytest.raises(ValueError):
        iso.parse_process_json("[1, 2]")


def test_parent_pid_windows_uses_cim_ppid_query():
    seen = []

    def runner(argv, **kw):
        seen.append(argv)
        return _ok(json.dumps({"ProcessId": 42, "ParentProcessId": 41}))

    assert iso.parent_pid_windows(42, runner=runner) == 41
    script = seen[0][-1]
    assert "Get-CimInstance" in script and "Win32_Process" in script and "ProcessId=42" in script
    assert "ParentProcessId" in script and "ConvertTo-Json" in script


def test_descendant_walk():
    procs = {7101: 7100, 7100: 1, 9999: 1, 1: 0}
    assert iso.is_descendant_or_self(7100, 7100, procs.get)
    assert iso.is_descendant_or_self(7101, 7100, procs.get)
    assert not iso.is_descendant_or_self(9999, 7100, procs.get)
    assert not iso.is_descendant_or_self(123456, 7100, procs.get)
    loop = {1: 2, 2: 1}
    assert not iso.is_descendant_or_self(1, 7100, loop.get)
    chain = {i: i - 1 for i in range(1, 100)}
    assert not iso.is_descendant_or_self(99, 0, chain.get, max_depth=8)


# ── happy path ───────────────────────────────────────────────────────────────

def test_happy_path_order_of_operations(world):
    res = _run(world)
    assert res.exit_code == iso.EXIT_OK, (res.error, world.logs)
    ev = world.events
    order = ["docker:info", "docker:inspect", "sql:meas:g2-role", "g2:connect", "health:8000",
             "git:worktree-add", "git:status", "git:check-ignore", "sql:meas:drop-create",
             "db:dump-restore", "sql:meas:tables", "pip-freeze", "launch", "health:8100",
             "sql:meas:g3-activity", "runner", "kill"]
    idx = [_first(ev, name) for name in order]
    assert idx == sorted(idx), list(zip(order, idx))
    # G3 runs before the runner and again after it, and the kill comes after both
    g3 = [i for i, e in enumerate(ev) if e == "sql:meas:g3-activity"]
    runner_i = ev.index("runner")
    assert len(g3) == 2 and g3[0] < runner_i < g3[1] < ev.index("kill")
    # G1's listener enumeration ran before anything was written or launched
    assert ev.index("listeners") < ev.index("git:worktree-add")
    assert world.kill_calls == [LAUNCHED]


def test_happy_path_worktree_add_command(world):
    _run(world)
    add = next(c for c in world.git_calls if "worktree" in c)
    assert add == ["-C", str(world.repo), "worktree", "add", "--detach", str(world.meas), iso.TAG]
    status = next(c for c in world.git_calls if "status" in c)
    assert status == ["-C", str(world.meas), "status", "--porcelain", "--untracked-files=no"]


def test_happy_path_existing_worktree_is_not_re_added(world):
    _make_meas_tree(world.meas)
    world.worktree_exists = True
    res = _run(world)
    assert res.exit_code == iso.EXIT_OK
    assert not any("worktree" in c for c in world.git_calls)


def test_happy_path_launch_command_cwd_env_and_log(world):
    _run(world)
    (call,) = world.launch_calls
    py = str(iso.venv_python(world.repo))
    assert call["argv"] == [py, "-m", "uvicorn", "app.main:app", "--ws", "websockets-sansio",
                            "--host", "127.0.0.1", "--port", "8100"]
    assert call["cwd"] == world.meas / "backend"
    env = call["env"]
    assert env["PYTHONUTF8"] == "1"
    assert env["DATABASE_URL"].startswith("postgresql+asyncpg://meas_runner:")
    assert "/bamendjou_meas" in env["DATABASE_URL"]
    assert "PGPASSWORD" not in env and "BAMENDJOU_TELEGRAM_BOT_TOKEN" not in env
    assert env[iso.MEAS_MARKER_KEY] == "1"
    assert env["TRADIER_API_TOKEN"] == TRADIER_TOKEN
    assert call["log_path"].parent == world.jobs / "logs"
    assert call["log_path"].name.endswith("-backend.log")


def test_happy_path_runner_command_and_timing(world):
    _run(world)
    (call,) = world.runner_calls
    py = str(iso.venv_python(world.repo))
    runner = world.meas / "docs" / "superpowers" / "measurements" / "run_measurement_day.py"
    assert call["argv"] == [py, str(runner), "core", "--base", "http://127.0.0.1:8100",
                            "--repo", str(world.meas)]
    assert call["cwd"] == world.meas
    assert call["env"]["PYTHONUTF8"] == "1"
    assert "PGPASSWORD" not in call["env"]
    assert iso.to_et(call["now"]) >= dt.datetime(2026, 10, 14, 13, 0, 30)


def test_runner_starts_immediately_when_past_1300_et(world):
    world.now = dt.datetime(2026, 10, 14, 17, 30, tzinfo=dt.timezone.utc)  # 13:30 ET
    res = _run(world)
    assert res.exit_code == iso.EXIT_OK
    assert any("13:00:30" in line and "skip" in line.lower() for line in world.logs)


def test_happy_path_meas_files(world):
    _run(world)
    meas_env = iso.read_env_file(world.meas / ".env")
    assert set(meas_env) == {"DATABASE_URL", "TRADIER_API_TOKEN", "TRADIER_BASE_URL", "TIINGO_API_TOKEN",
                             iso.MEAS_MARKER_KEY}
    settings = (world.meas / "backend" / "config" / "settings.yaml").read_text(encoding="utf-8")
    assert SMTP_SECRET not in settings and TELEGRAM_TOKEN not in settings
    creds = world.meas / "backend" / "config" / "local_credentials.yaml"
    assert creds.read_bytes() == (world.repo / "backend" / "config" / "local_credentials.yaml").read_bytes()
    assert not (world.meas / "backend" / "config" / "scan_schedule.yaml").exists()
    assert (world.meas / "backend" / "data" / "confidence_cache.db").is_file()
    # every runtime file was checked with git check-ignore in the meas checkout
    checked = {c[-1] for c in world.git_calls if "check-ignore" in c}
    assert checked == {".env", "backend/config/settings.yaml", "backend/config/local_credentials.yaml",
                       "backend/data/confidence_cache.db"}
    assert all(c[:2] == ["-C", str(world.meas)] for c in world.git_calls if "check-ignore" in c)
    # credentials content never logged
    assert not any(CRED_SECRET in line for line in world.logs)


def test_happy_path_evidence_and_isolation_json(world):
    res = _run(world)
    dest = world.repo / "docs" / "superpowers" / "measurements" / "scans" / ET_DATE
    assert res.evidence_dir == dest
    assert json.loads((dest / "manifest.json").read_text())["status"] == "done"
    data = _isolation(res)
    assert data["meas_db"] == "bamendjou_meas"
    assert data["tag_commit"] == TAG_SHA
    assert data["ports"]["meas"] == 8100 and data["ports"]["live"] == 8000
    assert data["live_backend_pid"] == {"before": LIVE_PID, "after": LIVE_PID}
    assert data["runner"]["exit_code"] == 0
    assert data["copy"]["row_counts"]["ohlcv_daily"] == {"copy": 1000, "live": 1000}
    assert data["confidence_cache"]["origin"] == "seeded-from-live"
    assert data["confidence_cache"]["tag_hittable_rows"] == 1
    assert data["settings_sha256"]["live"] and data["settings_sha256"]["sanitized"]
    assert data["settings_sha256"]["live"] != data["settings_sha256"]["sanitized"]
    assert data["python"]["version"].startswith("3.11.9")
    assert re.fullmatch(r"[0-9a-f]{64}", data["python"]["pip_freeze_sha256"])
    for key in ("g1", "g2", "g3_start", "g3_end", "stop"):
        assert data["guards"][key] and all(r["ok"] for r in data["guards"][key]), key
    assert data["exit_code"] == 0 and data["failures"] == []
    for key in ("start_utc", "backend_healthy_utc", "runner_start_utc", "runner_end_utc", "stopped_utc"):
        assert data["timestamps"][key]


def test_isolation_json_has_no_secret_and_no_absolute_user_path(world):
    res = _run(world)
    text = (res.evidence_dir / "isolation.json").read_text(encoding="utf-8")
    for secret in ALL_SECRETS:
        assert secret not in text
    for root in (world.tmp, world.repo, world.jobs, world.meas, Path.home()):
        for form in (str(root), root.as_posix(), json.dumps(str(root))[1:-1]):
            assert form.lower() not in text.lower()
    assert not re.search(r"(?<![A-Za-z])[A-Za-z]:[\\/]", text)
    assert "/home/" not in text and "/Users/" not in text


def test_isolation_paths_are_relative(world):
    data = _isolation(_run(world))
    paths = data["paths"]
    assert paths["meas_checkout"] == iso.TAG
    assert paths["backend_log"].startswith("logs/") and paths["runner_log"].startswith("logs/")
    assert paths["evidence_dir"] == f"docs/superpowers/measurements/scans/{ET_DATE}"


def test_bamendjou_meas_is_left_in_place(world):
    _run(world)
    assert "sql:meas:drop" not in world.events


def test_live_backend_absent_is_allowed_and_logged(world):
    world.live_pid = None
    res = _run(world)
    assert res.exit_code == iso.EXIT_OK
    assert any("8000" in line and "absent" in line for line in world.logs)
    assert _isolation(res)["live_backend_pid"] == {"before": None, "after": None}


def test_docker_desktop_started_when_engine_down(world):
    world.docker_up = False
    res = _run(world)
    assert res.exit_code == iso.EXIT_OK
    assert "docker:start-desktop" in world.events


def test_unhealthy_container_refuses_before_anything(world):
    world.container_state = "running unhealthy"
    res = _run(world, docker_wait_seconds=30)
    assert res.exit_code == iso.EXIT_REFUSED
    assert "launch" not in world.events and "git:worktree-add" not in world.events


def test_weekend_refuses(world):
    world.now = dt.datetime(2026, 10, 17, 16, 0, tzinfo=dt.timezone.utc)  # Saturday
    res = _run(world)
    assert res.exit_code == iso.EXIT_REFUSED
    assert "weekend" in res.error.lower()
    assert world.docker_calls == [] and "launch" not in world.events


# ── refusals before the start never launch ──────────────────────────────────

def _assert_not_started(world: World, res) -> None:
    assert res.exit_code == iso.EXIT_REFUSED
    assert "launch" not in world.events
    assert world.kill_calls == []
    assert "runner" not in world.events


def test_g2_failure_refuses_before_launch(world):
    world.g2_connect = _ok("1")   # meas_runner CONNECTED to live
    res = _run(world)
    _assert_not_started(world, res)
    assert "G2" in res.error
    assert "sql:meas:drop-create" not in world.events


def test_g1_failure_refuses_before_launch(world):
    world.listeners.append(("0.0.0.0", 5000, 321))   # IBKR gateway listening
    res = _run(world)
    _assert_not_started(world, res)
    assert "G1" in res.error and "git:worktree-add" not in world.events


def test_port_8100_busy_refuses_before_launch(world):
    world.listeners.append(("127.0.0.1", 8100, 5555))
    res = _run(world)
    _assert_not_started(world, res)
    assert "8100" in res.error


def test_meas_checkout_inside_repo_refuses(world):
    deps = world.deps()
    res = iso.run_isolated_day(repo_root=world.repo, jobs_dir=world.jobs,
                               meas_checkout=world.repo / "nested" / iso.TAG, deps=deps)
    _assert_not_started(world, res)
    assert "checkout_outside_repo" in res.error


def test_dirty_worktree_refuses(world):
    world.status_out = " M backend/app/main.py\n"
    res = _run(world)
    _assert_not_started(world, res)
    assert not (world.meas / ".env").exists()


def test_head_not_tag_refuses(world):
    world.head_sha = "0" * 40
    res = _run(world)
    _assert_not_started(world, res)
    assert not (world.meas / ".env").exists()


@pytest.mark.parametrize("rel", [".env", "backend/config/settings.yaml",
                                 "backend/config/local_credentials.yaml", "backend/data/confidence_cache.db"])
def test_runtime_file_not_gitignored_refuses(world, rel):
    world.not_ignored.add(rel)
    res = _run(world)
    _assert_not_started(world, res)
    assert rel in res.error
    assert not (world.meas / "backend" / "config" / "local_credentials.yaml").exists()


def test_missing_secret_file_refuses(world):
    (world.jobs / "meas_db.secret").unlink()
    res = _run(world)
    _assert_not_started(world, res)


# ── post-start refusals: forced tree-kill of the launched PID, never by port ─

def _assert_refused_after_start(world: World, res) -> None:
    assert res.exit_code == iso.EXIT_REFUSED, (res.error, world.logs)
    assert "launch" in world.events
    assert world.kill_calls == [LAUNCHED]
    assert "runner" not in world.events


def test_health_timeout_stops_and_refuses(world):
    world.health_after_polls = 10 ** 9
    res = _run(world)
    _assert_refused_after_start(world, res)
    assert "health" in res.error.lower()
    elapsed = (world.now - START).total_seconds()
    assert 180 <= elapsed < 400


def test_health_pid_not_descendant_stops_and_refuses(world):
    world.meas_health_pid = 9999          # some other process answers on 8100
    res = _run(world)
    _assert_refused_after_start(world, res)
    assert "g3_health_pid_descendant" in res.error


def test_8100_owned_by_another_pid_stops_and_refuses(world):
    world.listener_owner = 8888
    res = _run(world)
    _assert_refused_after_start(world, res)
    assert "g3_listener_owner" in res.error
    # the foreign listener is reported, never killed by port
    assert any("8100" in line and "still" in line for line in world.logs)
    assert ("127.0.0.1", 8100, 8888) in world.listeners


def test_live_pid_changed_at_start_stops_and_refuses(world):
    orig = world.launch

    def launch(*a, **kw):
        pid = orig(*a, **kw)
        world.live_pid = 4343
        return pid

    res = _run(world, launch=launch)
    _assert_refused_after_start(world, res)
    assert "g3_live_backend_pid_unchanged" in res.error


def test_meas_not_using_copy_stops_and_refuses(world):
    world.activity = {"bamendjou_meas": 2, LIVE_DB: 1}
    res = _run(world)
    _assert_refused_after_start(world, res)
    assert "g3_meas_connections_on_copy" in res.error


def test_ibkr_port_open_at_g3_start_stops_and_refuses(world):
    orig = world.launch

    def launch(*a, **kw):
        pid = orig(*a, **kw)
        world.listeners.append(("::1", 7499, 333))
        return pid

    res = _run(world, launch=launch)
    _assert_refused_after_start(world, res)
    assert "ibkr_ports_not_listening" in res.error


def test_unexpected_exception_after_start_still_kills_launched_pid(world):
    def boom(*_a, **_kw):
        raise RuntimeError("runner crashed")
    res = _run(world, run_runner=boom)
    assert res.exit_code != iso.EXIT_OK
    assert world.kill_calls == [LAUNCHED]


def test_stop_verification_failure_is_reported(world):
    def kill_noop(pid):
        world.kill_calls.append(pid)
        world.events.append("kill")
        return iso.CmdResult(1, "", "ERROR: not found")
    res = _run(world, kill_tree=kill_noop)
    assert res.exit_code != iso.EXIT_OK
    assert world.kill_calls == [LAUNCHED]
    assert any(not r["ok"] for r in res.isolation["guards"]["stop"])


# ── failures after the runner: recorded, non-zero exit, still stopped ───────

def test_ibkr_port_opens_mid_run(world):
    world.hooks["runner"] = lambda w: w.listeners.append(("0.0.0.0", 5000, 444))
    res = _run(world)
    assert res.exit_code == iso.EXIT_FAILED
    assert world.kill_calls == [LAUNCHED]
    data = _isolation(res)
    failed = [r["rule"] for r in data["guards"]["g3_end"] if not r["ok"]]
    assert "ibkr_ports_not_listening" in failed
    assert data["exit_code"] == iso.EXIT_FAILED and data["failures"]
    assert world.events.index("kill") > world.events.index("runner")


def test_live_pid_changed_at_end(world):
    def change(w):
        w.live_pid = 5151
    world.hooks["runner"] = change
    res = _run(world)
    assert res.exit_code == iso.EXIT_FAILED
    assert world.kill_calls == [LAUNCHED]
    data = _isolation(res)
    assert data["live_backend_pid"] == {"before": LIVE_PID, "after": 5151}
    assert "g3_live_backend_pid_unchanged" in [r["rule"] for r in data["guards"]["g3_end"] if not r["ok"]]


def test_runner_nonzero_exit(world):
    world.runner_exit = 3
    res = _run(world)
    assert res.exit_code == iso.EXIT_FAILED
    assert world.kill_calls == [LAUNCHED]
    data = _isolation(res)
    assert data["runner"]["exit_code"] == 3
    assert any("runner" in f for f in data["failures"])


def test_runner_wrote_no_day_folder_fails(world):
    world.runner_writes_day = False
    res = _run(world)
    assert res.exit_code == iso.EXIT_FAILED
    assert res.evidence_dir is None
    assert world.kill_calls == [LAUNCHED]


# ── only a day folder this run's runner created is copied ───────────────────

def _repo_scans(world: World) -> Path:
    return world.repo / "docs" / "superpowers" / "measurements" / "scans"


def _meas_day(world: World) -> Path:
    return world.meas / "docs" / "superpowers" / "measurements" / "scans" / ET_DATE


def test_second_run_same_et_date_copies_nothing(world):
    first = _run(world)
    assert first.exit_code == iso.EXIT_OK, (first.error, world.logs)
    first_iso = (first.evidence_dir / "isolation.json").read_text(encoding="utf-8")
    world.kill_calls.clear()
    second = _run(world)
    assert second.exit_code == iso.EXIT_FAILED
    assert second.evidence_dir is None
    assert sorted(p.name for p in _repo_scans(world).iterdir()) == [ET_DATE]
    assert (first.evidence_dir / "isolation.json").read_text(encoding="utf-8") == first_iso
    assert len(list(_repo_scans(world).rglob("isolation.json"))) == 1
    assert "predates this run" in second.error
    assert "predates this run" in " ".join(second.isolation["failures"])
    assert any("predates this run" in line for line in world.logs)
    assert world.kill_calls == [LAUNCHED]


def test_interrupted_first_run_folder_is_not_copied_to_primary_date(world):
    # run 1 was interrupted after its runner wrote the meas day folder, before the copy
    _make_meas_tree(world.meas)
    world.worktree_exists = True
    _meas_day(world).mkdir(parents=True)
    (_meas_day(world) / "manifest.json").write_text(
        json.dumps({"status": "running", "started_at": {"utc": START.isoformat()}}), encoding="utf-8")
    res = _run(world)
    assert res.exit_code == iso.EXIT_FAILED
    assert res.evidence_dir is None
    assert not (_repo_scans(world) / ET_DATE).exists()
    assert not _repo_scans(world).exists() or not any(_repo_scans(world).iterdir())
    assert not (_meas_day(world) / "isolation.json").exists()
    assert "predates this run" in res.error
    assert world.kill_calls == [LAUNCHED]


@pytest.mark.parametrize("started", [START, "absent"])
def test_day_folder_whose_manifest_starts_before_runner_start_is_refused(world, started):
    world.manifest_started_at = started
    res = _run(world)
    assert res.exit_code == iso.EXIT_FAILED
    assert res.evidence_dir is None
    assert not _repo_scans(world).exists() or not any(_repo_scans(world).iterdir())
    assert "manifest start" in res.error
    assert world.kill_calls == [LAUNCHED]


def test_runner_wrote_no_day_folder_reason_is_recorded(world):
    world.runner_writes_day = False
    res = _run(world)
    assert res.exit_code == iso.EXIT_FAILED and res.evidence_dir is None
    assert "wrote no day folder" in res.error


# ── evidence copy never overwrites ───────────────────────────────────────────

def test_copy_evidence_to_empty_or_missing_destination(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "manifest.json").write_text("{}")
    root = tmp_path / "scans"
    logs: list[str] = []
    dest = iso.copy_evidence(src, root, ET_DATE, "20261014T190000Z", log=logs.append)
    assert dest == root / ET_DATE and (dest / "manifest.json").read_text() == "{}"
    empty_root = tmp_path / "scans2"
    (empty_root / ET_DATE).mkdir(parents=True)
    dest2 = iso.copy_evidence(src, empty_root, ET_DATE, "s", log=logs.append)
    assert dest2 == empty_root / ET_DATE


def test_copy_evidence_falls_back_when_destination_not_empty(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "manifest.json").write_text("new")
    root = tmp_path / "scans"
    (root / ET_DATE).mkdir(parents=True)
    (root / ET_DATE / "manifest.json").write_text("old")
    logs: list[str] = []
    dest = iso.copy_evidence(src, root, ET_DATE, "20261014T190000Z", log=logs.append)
    assert dest == root / f"{ET_DATE}-isolated-20261014T190000Z"
    assert (root / ET_DATE / "manifest.json").read_text() == "old"
    assert (dest / "manifest.json").read_text() == "new"
    assert any("isolated" in line for line in logs)
    # the fallback folder itself is never overwritten either
    with pytest.raises(iso.GuardRefusal):
        iso.copy_evidence(src, root, ET_DATE, "20261014T190000Z", log=logs.append)
    assert (dest / "manifest.json").read_text() == "new"


def test_run_evidence_falls_back_when_day_folder_exists(world):
    existing = world.repo / "docs" / "superpowers" / "measurements" / "scans" / ET_DATE
    existing.mkdir(parents=True)
    (existing / "manifest.json").write_text("day3-original")
    res = _run(world)
    assert res.exit_code == iso.EXIT_OK
    assert res.evidence_dir.name.startswith(f"{ET_DATE}-isolated-")
    assert (existing / "manifest.json").read_text() == "day3-original"
    assert not (existing / "isolation.json").exists()
    assert (res.evidence_dir / "isolation.json").is_file()


# ── check ────────────────────────────────────────────────────────────────────

def test_check_runs_guards_and_never_starts_or_writes(world):
    _make_meas_tree(world.meas)
    world.worktree_exists = True
    code = iso.check_isolated_day(repo_root=world.repo, jobs_dir=world.jobs, deps=world.deps())
    assert code == iso.EXIT_OK, world.logs
    assert "launch" not in world.events and "runner" not in world.events
    assert "sql:meas:drop-create" not in world.events and "git:worktree-add" not in world.events
    assert "g2:connect" in world.events and "listeners" in world.events
    assert not (world.meas / ".env").exists()


def test_check_refuses_on_guard_failure(world):
    world.g2_connect = _ok("1")
    code = iso.check_isolated_day(repo_root=world.repo, jobs_dir=world.jobs, deps=world.deps())
    assert code == iso.EXIT_REFUSED
    assert "launch" not in world.events


# ── cleanup ──────────────────────────────────────────────────────────────────

def _seed_meas_runtime(world: World) -> None:
    _make_meas_tree(world.meas)
    (world.meas / ".env").write_text("DATABASE_URL=x\n")
    (world.meas / "backend" / "config" / "settings.yaml").write_text("a: 1\n")
    (world.meas / "backend" / "config" / "local_credentials.yaml").write_text("b: 2\n")
    (world.meas / "backend" / "config" / "strategy_params.yaml").write_text("tracked: 1\n")
    (world.meas / "backend" / "data" / "confidence_cache.db").write_bytes(b"cache")


def test_cleanup_drops_db_and_removes_runtime_files_but_keeps_cache(world):
    _seed_meas_runtime(world)
    code = iso.cleanup_isolated_day(repo_root=world.repo, jobs_dir=world.jobs, reset_cache=False,
                                    deps=world.deps())
    assert code == iso.EXIT_OK
    assert "sql:meas:drop" in world.events
    drop = next(c for c in world.docker_calls if c[1:2] == ["exec"])
    assert LIVE_DB not in " ".join(drop)
    assert not (world.meas / ".env").exists()
    assert not (world.meas / "backend" / "config" / "settings.yaml").exists()
    assert not (world.meas / "backend" / "config" / "local_credentials.yaml").exists()
    assert (world.meas / "backend" / "config" / "strategy_params.yaml").exists()
    assert (world.meas / "backend" / "data" / "confidence_cache.db").exists()
    assert (world.repo / "backend" / "config" / "settings.yaml").exists()


def test_cleanup_reset_cache_removes_cache_and_logs_it(world):
    _seed_meas_runtime(world)
    code = iso.cleanup_isolated_day(repo_root=world.repo, jobs_dir=world.jobs, reset_cache=True,
                                    deps=world.deps())
    assert code == iso.EXIT_OK
    assert not (world.meas / "backend" / "data" / "confidence_cache.db").exists()
    assert any("confidence" in line and "reset" in line.lower() for line in world.logs)
    assert (world.repo / "backend" / "data" / "confidence_cache.db").exists()


def test_cleanup_refuses_while_8100_is_in_use(world):
    _seed_meas_runtime(world)
    world.listeners.append(("127.0.0.1", 8100, 7777))
    code = iso.cleanup_isolated_day(repo_root=world.repo, jobs_dir=world.jobs, reset_cache=False,
                                    deps=world.deps())
    assert code == iso.EXIT_REFUSED
    assert "sql:meas:drop" not in world.events
    assert (world.meas / ".env").exists()


# ── CLI ──────────────────────────────────────────────────────────────────────

def test_setup_without_approval_flag_refuses(world, capsys):
    code = iso.main(["setup", "--repo-root", str(world.repo), "--jobs-dir", str(world.jobs)],
                    deps=world.deps())
    assert code == iso.EXIT_REFUSED
    out = capsys.readouterr()
    text = out.out + out.err + "\n".join(world.logs)
    assert "--i-have-kenneths-approval" in text
    assert "privileges" in text.lower() and "live" in text.lower()
    assert world.docker_calls == []


def test_setup_with_approval_flag_calls_setup(world, monkeypatch):
    seen = {}

    def fake_setup(live, secret_file, *, rotate=False, pg=None, log=print, **kw):
        seen.update(dbname=live.dbname, secret_file=Path(secret_file), rotate=rotate, pg=pg)
        return {"reverse_command": "GRANT CONNECT ..."}

    monkeypatch.setattr(iso, "setup", fake_setup)
    deps = world.deps()
    code = iso.main(["setup", "--i-have-kenneths-approval", "--repo-root", str(world.repo),
                     "--jobs-dir", str(world.jobs)], deps=deps)
    assert code == iso.EXIT_OK
    assert seen["dbname"] == LIVE_DB and seen["secret_file"] == world.jobs / "meas_db.secret"
    assert seen["rotate"] is False and seen["pg"] is deps.pg


def test_main_dispatches_run_check_cleanup(world, monkeypatch):
    calls = []
    monkeypatch.setattr(iso, "run_isolated_day",
                        lambda **kw: calls.append(("run", kw)) or iso.RunResult(exit_code=0))
    monkeypatch.setattr(iso, "check_isolated_day", lambda **kw: calls.append(("check", kw)) or 0)
    monkeypatch.setattr(iso, "cleanup_isolated_day", lambda **kw: calls.append(("cleanup", kw)) or 0)
    common = ["--repo-root", str(world.repo), "--jobs-dir", str(world.jobs)]
    assert iso.main(["run", *common], deps=world.deps()) == 0
    assert iso.main(["check", *common], deps=world.deps()) == 0
    assert iso.main(["cleanup", "--reset-cache", *common], deps=world.deps()) == 0
    assert [c[0] for c in calls] == ["run", "check", "cleanup"]
    assert calls[2][1]["reset_cache"] is True
    assert calls[0][1]["repo_root"] == world.repo and calls[0][1]["jobs_dir"] == world.jobs


def test_main_run_returns_nonzero_exit_code(world, monkeypatch):
    monkeypatch.setattr(iso, "run_isolated_day", lambda **kw: iso.RunResult(exit_code=iso.EXIT_FAILED))
    assert iso.main(["run", "--repo-root", str(world.repo), "--jobs-dir", str(world.jobs)],
                    deps=world.deps()) == iso.EXIT_FAILED


def test_script_has_main_guard():
    src = _SCRIPT_PATH.read_text(encoding="utf-8")
    assert 'if __name__ == "__main__":\n    sys.exit(main())' in src


# ── PowerShell launcher ──────────────────────────────────────────────────────

def test_ps1_launcher_is_thin():
    text = _PS1_PATH.read_text(encoding="utf-8")
    assert "isolated_day.py" in text and re.search(r"\brun\b", text)
    assert "$env:USERPROFILE" in text and "bamendjou-jobs" in text and "logs" in text
    assert "meas-isolated-" in text
    assert r"backend\.venv\Scripts\python.exe" in text
    assert "$PSScriptRoot" in text
    assert re.search(r"exit\s+\$", text)
    lowered = text.lower()
    for forbidden in ("git switch", "git checkout", "stop-process", "taskkill", "start-backend", ":8000",
                      "uvicorn"):
        assert forbidden not in lowered, forbidden
