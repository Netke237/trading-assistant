#!/usr/bin/env python3
"""run_options_profiles_measurement.py — Headless measurement harness for the 18 Options Search Profiles.

Target: Issue #187 (SEARCH-PROFILES-RECAL-OPTIONS).
Enables running measurement scans across the 18 Options search profiles (Intraday, Swing,
SemiAnnual × Baseline, Restrictive, Loose × Bullish, Bearish) on the mini PC or developer
workstation with live or mock market data.

Usage:
  python backend/scripts/run_options_profiles_measurement.py --dry-run
  python backend/scripts/run_options_profiles_measurement.py --live --api-url http://localhost:8000
  python backend/scripts/run_options_profiles_measurement.py --profile-id mu2n6u2bxt11 --dry-run
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure stdout/stderr handle UTF-8 if supported, otherwise ASCII fallback
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
# Resolve repository root robustly relative to this script
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

DEFAULT_PROFILES_FILE = REPO_ROOT / "docs" / "search-profiles" / "search-profiles-export.json"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "docs" / "superpowers" / "measurements"


def horizon_preset_to_scoring_horizon(preset: str) -> str:
    """Map holding horizonPreset to scoring horizon ('Intraday', 'Swing', 'Position')."""
    normalized = preset.strip().lower()
    if normalized == "intraday":
        return "Intraday"
    if normalized == "swing":
        return "Swing"
    if normalized in ("semiannual", "semi-annual", "position", "positionplus", "quarterly", "annual"):
        return "Position"
    return "Swing"


def horizon_preset_to_atr_key(preset: str) -> str:
    """Map horizonPreset to atrMult key ('intraday', 'swing', 'position')."""
    sh = horizon_preset_to_scoring_horizon(preset)
    return sh.lower()


def validate_profile_schema_v5(p: Dict[str, Any]) -> List[str]:
    """Validate that a profile matches Schema Version 5 requirements. Returns list of errors."""
    errors: List[str] = []
    if not isinstance(p, dict):
        return ["Profile must be an object"]

    # Basic identity
    for field in ("id", "name", "direction", "horizonPreset", "createdAt", "updatedAt"):
        val = p.get(field)
        if not isinstance(val, str) or not val.strip():
            errors.append(f"Missing or invalid string field: {field}")

    if p.get("mode") != "options":
        errors.append(f"Expected mode 'options', got {p.get('mode')!r}")

    if p.get("direction") not in ("Bullish", "Bearish"):
        errors.append(f"Invalid direction: {p.get('direction')!r}")

    # Hold bounds
    if not isinstance(p.get("holdMin"), (int, float)) or not isinstance(p.get("holdMax"), (int, float)):
        errors.append("holdMin and holdMax must be finite numbers")

    # Universe
    u = p.get("universe")
    if not isinstance(u, dict):
        errors.append("universe must be an object")
    else:
        if not isinstance(u.get("pick"), str) or not u.get("pick", "").strip():
            errors.append("universe.pick must be a non-empty string")
        if u.get("capUnit") not in ("M", "B"):
            errors.append(f"universe.capUnit must be 'M' or 'B', got {u.get('capUnit')!r}")
        for raw_field in ("minPriceRaw", "maxPriceRaw", "minCapRaw", "maxCapRaw", "customRaw"):
            if not isinstance(u.get(raw_field), str):
                errors.append(f"universe.{raw_field} must be a string primitive")

    # Overrides
    if not isinstance(p.get("scanOverrides"), dict):
        errors.append("scanOverrides must be an object")

    # Scan Settings
    ss = p.get("scanSettings")
    if not isinstance(ss, dict):
        errors.append("scanSettings must be an object")
    else:
        cg = ss.get("confidenceGate")
        if not isinstance(cg, dict):
            errors.append("scanSettings.confidenceGate must be an object")
        else:
            if not isinstance(cg.get("enabled"), bool):
                errors.append("confidenceGate.enabled must be boolean")
            if not isinstance(cg.get("cautionBelow"), (int, float)) or not isinstance(cg.get("rejectBelow"), (int, float)):
                errors.append("confidenceGate cautionBelow/rejectBelow must be numbers")
            atr = cg.get("atrMult")
            if not isinstance(atr, dict):
                errors.append("confidenceGate.atrMult must be an object")
            else:
                for k in ("intraday", "swing", "position"):
                    pair = atr.get(k)
                    if not isinstance(pair, dict) or not isinstance(pair.get("target"), (int, float)) or not isinstance(pair.get("stop"), (int, float)):
                        errors.append(f"confidenceGate.atrMult.{k} must contain numeric target and stop")

        fg = ss.get("fundamentalsGate")
        if not isinstance(fg, dict):
            errors.append("scanSettings.fundamentalsGate must be an object")
        else:
            if not isinstance(fg.get("enabled"), bool):
                errors.append("fundamentalsGate.enabled must be boolean")
            if not isinstance(fg.get("deReject"), (int, float)):
                errors.append("fundamentalsGate.deReject must be numeric")

        if not isinstance(ss.get("shortlistMaxCandidates"), int):
            errors.append("scanSettings.shortlistMaxCandidates must be an integer")

        spreads = ss.get("spreads")
        if not isinstance(spreads, dict):
            errors.append("scanSettings.spreads must be an object")

    # Options mode must omit strategy fields
    if "strategy" in p or "strategyParams" in p:
        errors.append("Options mode profiles must not define stocks strategy fields")

    return errors


def profile_to_scan_request_payload(profile: Dict[str, Any], symbols_override: Optional[List[str]] = None) -> Dict[str, Any]:
    """Convert a Schema Version 5 SearchProfile dictionary into a backend ScanRequest JSON payload."""
    universe_pick = profile["universe"]["pick"]
    if symbols_override:
        universe = symbols_override
    elif universe_pick == "Custom":
        custom_raw = profile["universe"].get("customRaw", "")
        import re
        tokens = re.split(r"[\s,;\n]+", custom_raw.strip())
        universe = [t.upper() for t in tokens if t]
    else:
        universe = [universe_pick]

    direction = profile["direction"]
    horizon_preset = profile["horizonPreset"]
    scoring_horizon = horizon_preset_to_scoring_horizon(horizon_preset)
    atr_key = horizon_preset_to_atr_key(horizon_preset)

    hold_min = int(profile.get("holdMin", 0))
    hold_max = int(profile.get("holdMax", 2))

    ss = profile.get("scanSettings", {})
    cg = ss.get("confidenceGate", {})
    atr = cg.get("atrMult", {}).get(atr_key, {})
    fg = ss.get("fundamentalsGate", {})
    spreads = ss.get("spreads", {})

    overrides = dict(profile.get("scanOverrides", {}))
    shortlist_max = ss.get("shortlistMaxCandidates", 10)
    overrides["shortlist_max_candidates"] = shortlist_max

    payload: Dict[str, Any] = {
        "universe": universe,
        "direction": direction,
        "horizon": scoring_horizon,
        "horizon_preset": horizon_preset,
        "hold_min_days": hold_min,
        "hold_max_days": hold_max,
        "overrides": overrides,
        "confidence_caution_below": cg.get("cautionBelow", 50) if cg.get("enabled", True) else 0,
        "confidence_reject_below": cg.get("rejectBelow", 35) if cg.get("enabled", True) else 0,
        "confidence_atr_mult_target": float(atr.get("target", 2.0)),
        "confidence_atr_mult_stop": float(atr.get("stop", 1.5)),
        "fundamentals_enabled": bool(fg.get("enabled", True)),
        "fundamentals_caution_below": float(fg.get("cautionBelow", 45)),
        "fundamentals_reject_below": float(fg.get("rejectBelow", 30)),
        "fundamentals_de_reject": float(fg.get("deReject", 3.0)),
        "spread_width": float(spreads.get("widthPoints", 5)),
        "short_leg_delta": float(spreads.get("shortLegDelta", 0.3)),
        "iv_rank_threshold": float(spreads.get("ivRankThreshold", 50)),
        "iv_abs_threshold": float(spreads.get("ivAbsThreshold", 50)),
        "min_credit": float(spreads.get("minCredit", 0.5)),
        "max_debit_pct": float(spreads.get("maxDebitPctOfWidth", 40)),
    }

    # Universe price / market-cap filters
    u = profile.get("universe", {})
    min_price_raw = u.get("minPriceRaw", "")
    max_price_raw = u.get("maxPriceRaw", "")
    min_cap_raw = u.get("minCapRaw", "")
    max_cap_raw = u.get("maxCapRaw", "")
    cap_unit = u.get("capUnit", "B")
    multiplier = 1e9 if cap_unit == "B" else 1e6

    try:
        if min_price_raw and min_price_raw.strip():
            payload["min_price"] = float(min_price_raw)
    except ValueError:
        pass
    try:
        if max_price_raw and max_price_raw.strip():
            payload["max_price"] = float(max_price_raw)
    except ValueError:
        pass
    try:
        if min_cap_raw and min_cap_raw.strip():
            payload["min_cap_usd"] = float(min_cap_raw) * multiplier
    except ValueError:
        pass
    try:
        if max_cap_raw and max_cap_raw.strip():
            payload["max_cap_usd"] = float(max_cap_raw) * multiplier
    except ValueError:
        pass

    return payload


def execute_live_scan(api_url: str, payload: Dict[str, Any], timeout_sec: int = 120) -> Dict[str, Any]:
    """Execute a scan request against a running FastAPI backend via HTTP."""
    endpoint = f"{api_url.rstrip('/')}/api/scan"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            status_code = resp.getcode()
            body = resp.read().decode("utf-8")
            if status_code != 200:
                raise RuntimeError(f"Scan endpoint returned HTTP {status_code}: {body}")
            return json.loads(body)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTPError {e.code} on POST {endpoint}: {err_body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Failed to reach scan endpoint {endpoint}: {e.reason}") from e


def run_measurement(
    profiles_path: Path,
    output_path: Optional[Path] = None,
    markdown_path: Optional[Path] = None,
    api_url: Optional[str] = None,
    live: bool = False,
    dry_run: bool = False,
    profile_id_filter: Optional[str] = None,
    symbols_override: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Orchestrate profile loading, validation, execution, and reporting."""
    if not profiles_path.exists():
        raise FileNotFoundError(f"Search profiles file not found: {profiles_path}")

    with open(profiles_path, "r", encoding="utf-8") as f:
        export_data = json.load(f)

    profiles: List[Dict[str, Any]] = export_data.get("state", {}).get("profiles", [])
    if not profiles:
        raise ValueError(f"No profiles found in {profiles_path}")

    if profile_id_filter:
        profiles = [p for p in profiles if p.get("id") == profile_id_filter]
        if not profiles:
            raise ValueError(f"Profile id {profile_id_filter!r} not found in {profiles_path}")

    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
    results: List[Dict[str, Any]] = []
    validation_failures: Dict[str, List[str]] = {}

    print(f"[MEAS] Loaded {len(profiles)} profile(s) from {profiles_path}")
    print(f"[MEAS] Mode: {'LIVE execution against ' + str(api_url) if live else 'DRY-RUN schema validation & payload plan'}")

    for idx, p in enumerate(profiles, start=1):
        pid = p.get("id", f"unknown-{idx}")
        name = p.get("name", f"unnamed-{idx}")
        errs = validate_profile_schema_v5(p)
        if errs:
            validation_failures[pid] = errs
            print(f"  [FAIL] [{idx}/{len(profiles)}] {name} ({pid}): Schema v5 errors: {errs}")
            continue

        payload = profile_to_scan_request_payload(p, symbols_override=symbols_override)

        # Check payload against Pydantic ScanRequest schema if app is importable
        pydantic_ok = True
        try:
            from app.schemas import ScanRequest
            # Pydantic v2 model_validate
            ScanRequest.model_validate(payload)
        except ImportError:
            pass  # Standalone environment without app package
        except Exception as ex:
            pydantic_ok = False
            validation_failures[pid] = [f"ScanRequest validation error: {ex}"]
            print(f"  [FAIL] [{idx}/{len(profiles)}] {name} ({pid}): Pydantic validation failed: {ex}")
            continue

        profile_summary: Dict[str, Any] = {
            "index": idx,
            "id": pid,
            "name": name,
            "mode": p.get("mode"),
            "direction": p.get("direction"),
            "horizon_preset": p.get("horizonPreset"),
            "scoring_horizon": payload["horizon"],
            "scan_overrides": payload.get("overrides", {}),
            "payload": payload,
            "validation_status": "PASS",
        }

        if live:
            if not api_url:
                raise ValueError("Must specify --api-url when running with --live")
            print(f"  [RUN] [{idx}/{len(profiles)}] Executing scan: {name} ({pid}) ...")
            start_t = dt.datetime.now()
            scan_out = execute_live_scan(api_url, payload)
            elapsed = (dt.datetime.now() - start_t).total_seconds()

            candidates = scan_out.get("candidates", [])
            rejected = scan_out.get("rejected", [])
            scan_id = scan_out.get("scan_id", "")

            # Rejection reason tally
            rejection_tally: Dict[str, int] = {}
            for r in rejected:
                reason = r.get("reason", "unknown")
                rejection_tally[reason] = rejection_tally.get(reason, 0) + 1

            top_candidates = []
            for c in candidates[:3]:
                top_candidates.append({
                    "symbol": c.get("symbol"),
                    "score": c.get("score"),
                    "contract": {
                        "strike": c.get("contract", {}).get("strike"),
                        "right": c.get("contract", {}).get("right"),
                        "expiration": c.get("contract", {}).get("expiration"),
                        "delta": c.get("contract", {}).get("delta"),
                        "spread": c.get("contract", {}).get("spread"),
                        "iv_rank": c.get("contract", {}).get("iv_rank"),
                    }
                })

            profile_summary["live_scan"] = {
                "scan_id": scan_id,
                "elapsed_seconds": elapsed,
                "candidates_count": len(candidates),
                "rejected_count": len(rejected),
                "rejection_tally": rejection_tally,
                "top_candidates": top_candidates,
            }
            print(f"     -> Passed: {len(candidates)}, Rejected: {len(rejected)} in {elapsed:.1f}s")
        else:
            print(f"  [OK] [{idx}/{len(profiles)}] Validated v5: {name} ({pid}) [Horizon: {payload['horizon']}, Direction: {payload['direction']}]")

        results.append(profile_summary)

    report: Dict[str, Any] = {
        "timestamp": now_iso,
        "profiles_file": str(profiles_path),
        "total_profiles": len(profiles),
        "valid_count": len(results),
        "failure_count": len(validation_failures),
        "failures": validation_failures,
        "results": results,
    }

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"[MEAS] Wrote JSON report to: {output_path}")

    if markdown_path:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        md_text = generate_markdown_summary(report, live=live)
        with open(markdown_path, "w", encoding="utf-8") as f:
            f.write(md_text)
        print(f"[MEAS] Wrote Markdown summary to: {markdown_path}")

    return report


def generate_markdown_summary(report: Dict[str, Any], live: bool = False) -> str:
    """Generate a clean Markdown summary table from measurement report."""
    lines: List[str] = [
        f"# Options Search Profiles Measurement Report",
        f"",
        f"- **Timestamp:** {report.get('timestamp')}",
        f"- **Profiles Evaluated:** {report.get('valid_count')} / {report.get('total_profiles')}",
        f"- **Mode:** {'Live Market Scan' if live else 'Schema v5 Dry Run'}",
        f"",
    ]

    if not live:
        lines.extend([
            f"| Profile ID | Profile Name | Direction | Horizon | Overrides | Status |",
            f"|---|---|---|---|---|---|",
        ])
        for r in report.get("results", []):
            ov_str = ", ".join(f"{k}={v}" for k, v in r.get("scan_overrides", {}).items() if k != "shortlist_max_candidates")
            lines.append(f"| `{r['id']}` | `{r['name']}` | {r['direction']} | {r['horizon_preset']} ({r['scoring_horizon']}) | {ov_str or 'default'} | ✅ PASS |")
    else:
        lines.extend([
            f"| Profile ID | Profile Name | Candidates | Rejected | Top Reject Reasons | Top Pick (Score) |",
            f"|---|---|---|---|---|---|",
        ])
        for r in report.get("results", []):
            ls = r.get("live_scan", {})
            c_cnt = ls.get("candidates_count", 0)
            r_cnt = ls.get("rejected_count", 0)
            tally = ls.get("rejection_tally", {})
            top_rej = ", ".join(f"{k}:{v}" for k, v in sorted(tally.items(), key=lambda x: -x[1])[:2])
            top_c = ls.get("top_candidates", [])
            top_pick = f"{top_c[0]['symbol']} ({top_c[0]['score']})" if top_c else "—"
            lines.append(f"| `{r['id']}` | `{r['name']}` | {c_cnt} | {r_cnt} | {top_rej or 'none'} | {top_pick} |")

    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Options Search Profiles Measurement Runner")
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES_FILE, help="Path to search profiles JSON export")
    parser.add_argument("--output", type=Path, default=None, help="Path to write JSON output report")
    parser.add_argument("--markdown", type=Path, default=None, help="Path to write Markdown summary table")
    parser.add_argument("--api-url", type=str, default="http://localhost:8000", help="FastAPI backend URL (for --live)")
    parser.add_argument("--live", action="store_true", help="Execute scans against live API")
    parser.add_argument("--dry-run", action="store_true", help="Validate schema and generate payload plan only")
    parser.add_argument("--profile-id", type=str, default=None, help="Filter to single profile by ID")
    parser.add_argument("--symbols", type=str, default=None, help="Comma-separated symbols override (e.g. AAPL,MSFT,NVDA)")

    args = parser.parse_args()

    # Default output path if not specified
    date_str = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = args.output
    if output_path is None and not args.dry_run:
        output_path = DEFAULT_OUTPUT_DIR / f"options_profiles_measurement_{date_str}.json"

    symbols_list = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] if args.symbols else None

    # Default to dry-run if --live is not specified
    is_live = args.live
    is_dry = args.dry_run or not is_live

    try:
        report = run_measurement(
            profiles_path=args.profiles,
            output_path=output_path,
            markdown_path=args.markdown,
            api_url=args.api_url,
            live=is_live,
            dry_run=is_dry,
            profile_id_filter=args.profile_id,
            symbols_override=symbols_list,
        )
        if report.get("failure_count", 0) > 0:
            print(f"[MEAS] Failed with {report['failure_count']} schema error(s).", file=sys.stderr)
            return 1
        print("[MEAS] Execution finished successfully.")
        return 0
    except Exception as e:
        print(f"[MEAS] Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
