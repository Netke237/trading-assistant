#!/usr/bin/env python3
"""MEAS measurement-day runner. Read PROTOCOL.md (same folder) first.

Sends the exact request bodies in protocol-requests/ to a RUNNING backend,
in a fixed order, and saves every request and raw result under
docs/superpowers/measurements/scans/<date>[-<tag>]/. It changes nothing in the
app: it issues GETs and scan POSTs only, never writes under backend/, and never
calls /settings/credentials.

Standard library only, except `strip-creds`, which needs PyYAML -- run the whole
thing with the backend's interpreter (Windows: backend\\.venv\\Scripts\\python.exe).

    python run_measurement_day.py core                  # O1-O4, S1-S4, C1-C6
    python run_measurement_day.py strip-creds --out C:\\Users\\me\\meas-creds.yaml
    (restart the backend with BAMENDJOU_CREDS_PATH set -- PROTOCOL.md step 4)
    python run_measurement_day.py ivabs                 # A1, A2 (percentile source OFF)
    (restart the backend normally -- PROTOCOL.md step 6)
    python run_measurement_day.py restore-check

Every safety or validity breach STOPS the run with a message and records it in
manifest.json. Nothing here decides a threshold: see RESULTS-SHEET.md.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REQ_DIR = HERE / "protocol-requests"
DEFAULT_REPO = HERE.parents[2]          # docs/superpowers/measurements -> repo root
DEFAULT_BASE = "http://127.0.0.1:8000"

SCAN_TIMEOUT_S = 1800
GET_TIMEOUT_S = 90

# ── The scan set (plan §3). Order is part of the protocol. ────────────────────
# (id, endpoint, base body file, change applied to a deep copy of the base body)
OPT = "/api/scan"
STK = "/api/stock-scan"
CORE_SCANS = [
    ("O1", OPT, "options-position-bearish", None),
    ("O2", OPT, "options-position-bullish", None),
    ("O3", OPT, "options-swing-bearish", None),
    ("O4", OPT, "options-swing-bullish", None),
    ("S1", STK, "stocks-swing-bearish", None),
    ("S2", STK, "stocks-swing-bullish", None),
    ("S3", STK, "stocks-position-bearish", None),
    ("S4", STK, "stocks-position-bullish", None),
]
COUNTERFACTUAL_SCANS = [
    ("C1", OPT, "options-position-bearish", {"confidence_reject_below": 30}),
    ("C2", OPT, "options-position-bearish", {"confidence_reject_below": 25}),
    ("C3", STK, "stocks-position-bearish", {"confidence_reject_below": 30}),
    ("C4", STK, "stocks-position-bearish", {"confidence_reject_below": 25}),
    ("C5", OPT, "options-position-bearish", {"overrides": {"min_stock_score": 35}}),
    ("C6", OPT, "options-position-bearish", {"overrides": {"min_volume": 0, "min_open_interest": 0}}),
]
IVABS_SCANS = [
    ("A1", OPT, "options-position-bearish", None),
    ("A2", OPT, "options-swing-bearish", None),
]
CORE_IDS = {s[0] for s in CORE_SCANS}

REGIME_URLS = {
    "position": "/api/regime?horizon=position&lookback=20&threshold=0.02&smoothing=0",
    "swing": "/api/regime?horizon=swing&lookback=20&threshold=0.02&smoothing=0",
}

# ── Time windows (plan §4.6). ET is authoritative. ────────────────────────────
CORE_START_EARLIEST = (13, 0)
CORE_START_LATEST = (13, 45)
CORE_DONE_BY = (15, 0)
LAST_SCAN_START_BY = (15, 40)   # a scan takes ~5 min; nothing may start later
ALL_DONE_BY = (15, 55)


class Stop(Exception):
    """A safety or validity breach: the run stops here."""


# ── US Eastern time without tzdata (Windows Python often has no IANA db) ─────
def _nth_sunday(year: int, month: int, n: int) -> dt.date:
    d = dt.date(year, month, 1)
    d += dt.timedelta(days=(6 - d.weekday()) % 7)
    return d + dt.timedelta(weeks=n - 1)


def to_et(t_utc: dt.datetime) -> dt.datetime:
    """UTC-aware datetime -> naive US Eastern wall time (EDT/EST rules since 2007)."""
    y = t_utc.year
    dst_start = dt.datetime.combine(_nth_sunday(y, 3, 2), dt.time(7, 0))   # 02:00 EST = 07:00 UTC
    dst_end = dt.datetime.combine(_nth_sunday(y, 11, 1), dt.time(6, 0))    # 02:00 EDT = 06:00 UTC
    naive = t_utc.astimezone(dt.timezone.utc).replace(tzinfo=None)
    offset = -4 if dst_start <= naive < dst_end else -5
    return naive + dt.timedelta(hours=offset)


class Clock:
    def __init__(self, fixed: str | None):
        self._fixed = dt.datetime.fromisoformat(fixed).astimezone(dt.timezone.utc) if fixed else None

    def utc(self) -> dt.datetime:
        return self._fixed or dt.datetime.now(dt.timezone.utc)

    def et(self) -> dt.datetime:
        return to_et(self.utc())


def _hm(t: dt.datetime) -> tuple[int, int]:
    return (t.hour, t.minute)


# ── HTTP ──────────────────────────────────────────────────────────────────────
def http(base: str, method: str, path: str, body: bytes | None = None, timeout: float = GET_TIMEOUT_S) -> bytes:
    req = urllib.request.Request(base.rstrip("/") + path, data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read()[:500].decode("utf-8", "replace")
        raise Stop(f"{method} {path} -> HTTP {e.code}: {detail}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise Stop(f"{method} {path} failed: {e} -- is the backend running at {base}?") from None


def get_json(base: str, path: str):
    return json.loads(http(base, "GET", path).decode("utf-8"))


# ── Files ─────────────────────────────────────────────────────────────────────
def write_bytes(path: Path, data: bytes) -> None:
    """Exact bytes as received -- no re-encoding (the 09-18 mojibake)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def write_json(path: Path, obj) -> None:
    write_bytes(path, (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def build_body(base_file: str, change: dict | None) -> dict:
    body = json.loads((REQ_DIR / f"{base_file}.request.json").read_text(encoding="utf-8"))
    body = copy.deepcopy(body)
    for k, v in (change or {}).items():
        if k == "overrides":
            body.setdefault("overrides", {}).update(v)
        else:
            body[k] = v
    return body


# ── Checks (each one is a plan §4 rule) ───────────────────────────────────────
def check_auto_trade_disarmed(ctx) -> None:
    """§4.1: POST /api/scan fires an ARMED auto-trade on a PASS candidate."""
    status = get_json(ctx.base, "/auto-trade/status")
    if status.get("armed") is not False:
        raise Stop(f"auto-trader is not disarmed (armed={status.get('armed')!r}). "
                   "Disarm it in the app, then re-run with a new --run-tag.")


def check_no_enabled_schedules(ctx) -> None:
    """§4.2: a scheduled scan inside the window competes for the same data sources."""
    entries = get_json(ctx.base, "/api/scan-schedule")
    enabled = [e.get("id") or e.get("name") for e in entries if e.get("enabled")]
    if enabled:
        raise Stop(f"scan schedule entries are enabled: {enabled}. Disable them for the run.")


def config_state(repo: Path) -> dict:
    cfg = repo / "backend" / "config"
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(cfg.glob("*.yaml"))
              if p.name != "local_credentials.yaml"}
    return {"sha256": hashes}


def git(repo: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as e:
        raise Stop(f"git {' '.join(args)} failed: {e}") from None


def check_config_clean(ctx) -> None:
    """§4.3: tracked YAML must equal HEAD."""
    dirty = git(ctx.repo, "status", "--porcelain", "--", "backend/config")
    if dirty:
        raise Stop(f"backend/config differs from HEAD:\n{dirty}\nRestore it (or commit it on main) first.")


def source_status(ctx, source_id: str) -> str | None:
    for s in get_json(ctx.base, "/api/data-sources"):
        if s.get("id") == source_id:
            return s.get("status")
    return None


def iv_bases(result: dict) -> list[str | None]:
    out = []
    for c in result.get("candidates") or []:
        vd = ((c.get("stockBreakdown") or {}).get("volDetail") or {})
        out.append(vd.get("iv_basis"))
    return out


def check_window_before_scan(ctx, scan_id: str) -> None:
    now = _hm(ctx.clock.et())
    if now > LAST_SCAN_START_BY:
        raise Stop(f"{scan_id}: it is {now[0]:02d}:{now[1]:02d} ET, past the last start time "
                   f"{LAST_SCAN_START_BY[0]:02d}:{LAST_SCAN_START_BY[1]:02d} ET -- the scan could not finish "
                   "before the close.")


# ── Manifest ──────────────────────────────────────────────────────────────────
class Ctx:
    def __init__(self, args):
        self.base = args.base
        self.repo = Path(args.repo).resolve()
        self.clock = Clock(args.now)
        self.out_root = Path(args.out_root).resolve() if args.out_root else HERE / "scans"
        self.tag = args.run_tag

    def day_dir(self) -> Path:
        name = self.clock.et().date().isoformat() + (f"-{self.tag}" if self.tag else "")
        return self.out_root / name

    def load_manifest(self) -> dict:
        return json.loads((self.day_dir() / "manifest.json").read_text(encoding="utf-8"))

    def save_manifest(self, m: dict) -> None:
        write_json(self.day_dir() / "manifest.json", m)


def stamp(ctx) -> dict:
    return {"utc": ctx.clock.utc().isoformat(), "et": ctx.clock.et().strftime("%Y-%m-%d %H:%M:%S ET")}


def snapshot(ctx, folder: Path, label: str) -> None:
    write_bytes(folder / f"data-sources.{label}.json", http(ctx.base, "GET", "/api/data-sources"))
    for h, url in REGIME_URLS.items():
        write_bytes(folder / f"regime-{h}.{label}.json", http(ctx.base, "GET", url))


def run_scan(ctx, m: dict, folder: Path, scan) -> None:
    scan_id, endpoint, base_file, change = scan
    check_window_before_scan(ctx, scan_id)
    if endpoint == OPT:
        check_auto_trade_disarmed(ctx)
    body = build_body(base_file, change)
    raw_body = json.dumps(body, ensure_ascii=False).encode("utf-8")
    name = f"{scan_id}-{base_file}"
    write_bytes(folder / f"{name}.request.json", raw_body)
    rec = {"id": scan_id, "endpoint": endpoint, "base": base_file, "change": change,
           "request_file": f"{name}.request.json", "start": stamp(ctx), "flags": []}
    m["scans"].append(rec)
    ctx.save_manifest(m)
    print(f"[{rec['start']['et']}] {scan_id} {endpoint} {base_file} {change or ''} ...", flush=True)

    raw = http(ctx.base, "POST", endpoint, raw_body, timeout=SCAN_TIMEOUT_S)
    write_bytes(folder / f"{name}.result.json", raw)
    rec["result_file"] = f"{name}.result.json"
    rec["end"] = stamp(ctx)
    result = json.loads(raw.decode("utf-8"))
    rec["scan_id"] = result.get("scan_id")
    rec["candidates"] = len(result.get("candidates") or [])

    if endpoint == OPT:
        write_json(folder / f"{name}.envelope.json", {"request": body, "result": result})
        rec["envelope_file"] = f"{name}.envelope.json"
        bases = iv_bases(result)
        rec["iv_bases"] = bases
        if scan_id.startswith("A"):
            iv_ranks = [((c.get("contractDetails") or {}).get("ivRank")) for c in result.get("candidates") or []]
            if any(b == "rank" for b in bases) or any(r is not None for r in iv_ranks):
                rec["flags"].append("INVALID:percentile_source_still_on")
        elif any(b != "rank" for b in bases):
            rec["flags"].append("iv_source_mismatch")
    if scan_id == "C6":
        reasons = json.dumps(result.get("rejected") or [])
        if "volume_too_low" in reasons or "open_interest_too_low" in reasons:
            rec["flags"].append("override_not_applied:min_volume_or_oi")

    if scan_id in CORE_IDS and _hm(ctx.clock.et()) > CORE_DONE_BY:
        rec["flags"].append("late_for_comparison")
    if _hm(ctx.clock.et()) > ALL_DONE_BY:
        rec["flags"].append("finished_after_1555_ET")
    ctx.save_manifest(m)
    print(f"    -> {rec['candidates']} candidates, scan_id {rec['scan_id']}, flags {rec['flags'] or '-'}",
          flush=True)


def _finish(ctx, m: dict, folder: Path, label: str) -> None:
    snapshot(ctx, folder, label)
    m[f"config_{label}"] = config_state(ctx.repo)
    if m[f"config_{label}"] != m["config_start"]:
        m["flags"].append(f"INVALID:config_changed_during_run({label})")
    m[f"{label}_at"] = stamp(ctx)


# ── Commands ──────────────────────────────────────────────────────────────────
def cmd_core(ctx) -> None:
    et = ctx.clock.et()
    if et.weekday() >= 5:
        raise Stop(f"{et.date()} is a weekend in New York -- no session.")
    if not (CORE_START_EARLIEST <= _hm(et) <= CORE_START_LATEST):
        raise Stop(f"it is {et:%H:%M} ET; the core block must START between 13:00 and 13:45 ET "
                   "(comparability with 2026-09-18, which started 13:20 ET).")
    folder = ctx.day_dir()
    if folder.exists():
        raise Stop(f"{folder} already exists -- never overwritten. Use --run-tag <new tag> for a rerun.")

    check_config_clean(ctx)
    check_no_enabled_schedules(ctx)
    check_auto_trade_disarmed(ctx)
    tasty = source_status(ctx, "tastytrade")
    if tasty != "connected":
        raise Stop(f"tastytrade (IV rank source) is {tasty!r}, not 'connected' -- the rank "
                   "measurement would be wasted. Fix the connection first.")

    folder.mkdir(parents=True)
    m = {"protocol": "docs/superpowers/measurements/PROTOCOL.md", "base_url": ctx.base,
         "git_head": git(ctx.repo, "rev-parse", "HEAD"), "started_at": stamp(ctx),
         "config_start": config_state(ctx.repo), "regime_urls": REGIME_URLS,
         "scans": [], "flags": [], "status": "running"}
    ctx.save_manifest(m)
    snapshot(ctx, folder, "start")
    print("NOTE: every POST /api/scan replaces the app's 'last scan' and its rank deltas.", flush=True)
    try:
        for scan in CORE_SCANS + COUNTERFACTUAL_SCANS:
            run_scan(ctx, m, folder, scan)
        _finish(ctx, m, folder, "core_end")
        m["status"] = "core_complete"
    except Stop as e:
        m["status"] = f"stopped: {e}"
        raise
    finally:
        ctx.save_manifest(m)
    print(f"core block done -> {folder}\nNext: PROTOCOL.md step 3 (strip-creds) and step 4 (restart).")


def cmd_ivabs(ctx) -> None:
    folder = ctx.day_dir()
    if not (folder / "manifest.json").exists():
        raise Stop(f"no core run found at {folder} -- run `core` first (same day, same --run-tag).")
    m = ctx.load_manifest()
    if m.get("status") != "core_complete":
        raise Stop(f"core run status is {m.get('status')!r}, not 'core_complete'.")
    if any(s["id"].startswith("A") for s in m["scans"]):
        raise Stop("A-scans already recorded for this run -- never overwritten. Use a new --run-tag.")
    tasty = source_status(ctx, "tastytrade")
    ibkr = source_status(ctx, "ibkr")
    if tasty != "unconfigured":
        raise Stop(f"tastytrade is {tasty!r}; it must be 'unconfigured' (backend started with "
                   "BAMENDJOU_CREDS_PATH pointing at the stripped copy -- PROTOCOL.md step 4).")
    if ibkr == "connected":
        raise Stop("IBKR gateway is connected -- stop it; it is an IV rank source too.")
    check_auto_trade_disarmed(ctx)
    m["ivabs_sources"] = {"tastytrade": tasty, "ibkr": ibkr}
    snapshot(ctx, folder, "ivabs_start")
    try:
        for scan in IVABS_SCANS:
            run_scan(ctx, m, folder, scan)
        _finish(ctx, m, folder, "ivabs_end")
        m["status"] = "ivabs_complete"
    except Stop as e:
        m["status"] = f"ivabs stopped: {e}"
        raise
    finally:
        ctx.save_manifest(m)
    print("A-scans done. Next: PROTOCOL.md step 6 (restart normally) and restore-check.")


def cmd_restore_check(ctx) -> None:
    folder = ctx.day_dir()
    tasty = source_status(ctx, "tastytrade")
    rec = {"tastytrade": tasty, "at": stamp(ctx)}
    if folder.exists() and (folder / "manifest.json").exists():
        m = ctx.load_manifest()
        m["restore_check"] = rec
        ctx.save_manifest(m)
    if tasty != "connected":
        raise Stop(f"tastytrade is {tasty!r} after the restart -- the backend is still running on the "
                   "stripped copy. Close that window, open a NEW cmd window and run start-backend.bat.")
    print("tastytrade connected again. Delete the stripped copy now (PROTOCOL.md step 7).")


def cmd_strip_creds(ctx, out: str) -> None:
    import yaml  # PyYAML ships with the backend venv

    src = ctx.repo / "backend" / "config" / "local_credentials.yaml"
    dst = Path(out).expanduser().resolve()
    try:
        dst.relative_to(ctx.repo)
        raise Stop(f"{dst} is inside the repository -- put the copy OUTSIDE it (it holds broker tokens).")
    except ValueError:
        pass
    if not src.exists():
        raise Stop(f"{src} not found -- nothing to copy.")
    data = yaml.safe_load(src.read_text(encoding="utf-8")) or {}
    stripped = {k: v for k, v in data.items() if k not in ("tastytrade_paper", "tastytrade_live")}
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(yaml.safe_dump(stripped, sort_keys=True), encoding="utf-8")
    try:
        os.chmod(dst, 0o600)
    except OSError:
        pass
    print(f"wrote {dst} with slots {sorted(stripped)} (tastytrade removed). The original is untouched.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["core", "ivabs", "restore-check", "strip-creds"])
    ap.add_argument("--base", default=DEFAULT_BASE, help="backend URL (default %(default)s)")
    ap.add_argument("--run-tag", default=None, help="sub-run name for a same-day rerun, e.g. run2")
    ap.add_argument("--out", help="strip-creds: output path OUTSIDE the repository")
    ap.add_argument("--repo", default=str(DEFAULT_REPO), help=argparse.SUPPRESS)
    ap.add_argument("--out-root", default=None, help=argparse.SUPPRESS)   # tests only
    ap.add_argument("--now", default=None, help=argparse.SUPPRESS)        # tests only
    args = ap.parse_args(argv)
    ctx = Ctx(args)
    try:
        if args.command == "core":
            cmd_core(ctx)
        elif args.command == "ivabs":
            cmd_ivabs(ctx)
        elif args.command == "restore-check":
            cmd_restore_check(ctx)
        else:
            if not args.out:
                raise Stop("strip-creds needs --out <path outside the repository>")
            cmd_strip_creds(ctx, args.out)
    except Stop as e:
        print(f"STOPPED: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
