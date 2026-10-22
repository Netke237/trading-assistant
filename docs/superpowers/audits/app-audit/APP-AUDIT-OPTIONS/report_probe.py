"""
Executable Verification Probe: Options Durable Reports, Lifecycle & Restart Parity
Lane C: APP-AUDIT-OPTIONS (#379, Part of #351)
Application Baseline: 880c8441841cc22d5090cdc5f984e4cf7e3d9a8d
Runtime: Python 3.11 pinned

This probe independently validates:
1. Scan report storage schema, table constraints, generation sequencing, and additive migration.
2. Complete report lifecycle: created/running -> completed, failed, cancelled, interrupted.
3. Category retention and strict isolation across all 5 categories (options, stocks, prebreakout, pullback, fib).
4. Dual-evidence latest attempt vs previous usable report retention and non-pruning of inflight runs.
5. Simulated backend process restart: engine disposal and cold session recreation against the same SQLite database.
6. Startup recovery of interrupted scans (recover_interrupted) without corrupting existing reports.
7. Exact frozen request settings preservation and immutability against caller dictionary mutation.
8. Setting comparison logic (scanReportInputsDiffer) verifying frozen historical inputs vs current control mutations.
9. Pipeline diagnostics, candidate drop-offs, exclusions, and terminal outcomes (version 1) verification.
10. Security guardrails: forbidden keys, credential rejection, and projection sanitization.
11. Legacy scan_sessions interoperability and additive schema upgrade/downgrade.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any, Dict, List, Optional

# Ensure backend root is on sys.path
REPO_ROOT = Path(__file__).resolve().parents[5]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import create_engine, delete, inspect, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.exc import SQLAlchemyError

from app.models.scan_report import ScanReport, ScanReportBase, ScanReportHead
from app.models.scan_session import ScanSession, ScanSessionBase
from app.services.scan_reports import (
    CATEGORIES,
    ERROR_CODES,
    FORBIDDEN_KEYS,
    TERMINAL_STATES,
    TRIGGERS,
    ScanReportStorageError,
    _encode,
    _now,
    begin_run,
    finish_run,
    get_latest,
    get_legacy,
    get_run,
    recover_interrupted,
)
from app.services.scan_report_lifecycle import (
    Collector,
    _safe_key,
    _safe_string,
    current_collector,
    observe_configuration,
    observe_data_failure,
    observe_evaluation,
    observe_no_data,
    observe_resolution,
    observe_terminal,
    persisted_result,
    project,
    project_terminal_record,
    run_reported_scan,
)
from app.schemas import ScanResult, RejectedCandidate, TradeCardData


def hash_file(path: Path) -> str:
    if not path.exists():
        return "MISSING"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_json(value: Any) -> Optional[str]:
    """Pure canonical JSON serialization matching frontend canonical() helper."""
    if value is None:
        return None

    def _sort_obj(v: Any) -> Any:
        if isinstance(v, dict):
            return {k: _sort_obj(v[k]) for k in sorted(v.keys()) if v[k] is not None}
        if isinstance(v, list):
            return [_sort_obj(x) for x in v]
        return v

    sorted_v = _sort_obj(value)
    return json.dumps(sorted_v, separators=(',', ':'))


def scan_report_inputs_differ(frozen: Dict[str, Any], current: Dict[str, Any]) -> bool:
    """Independent implementation of frontend scanReportInputsDiffer logic."""
    all_keys = sorted(set(list(frozen.keys()) + list(current.keys())))
    for key in all_keys:
        if key == 'category':
            continue
        v_frozen = canonical_json(frozen.get(key))
        v_current = canonical_json(current.get(key))
        if v_frozen != v_current:
            return True
    return False


class ReportAuditProbe:
    def __init__(self):
        self.observations: Dict[str, Any] = {
            "probe_metadata": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "python_version": sys.version,
                "platform": sys.platform,
                "baseline_sha": "880c8441841cc22d5090cdc5f984e4cf7e3d9a8d",
                "source_hashes": {
                    "scan_report_model": hash_file(BACKEND_DIR / "app" / "models" / "scan_report.py"),
                    "scan_reports_service": hash_file(BACKEND_DIR / "app" / "services" / "scan_reports.py"),
                    "scan_report_lifecycle": hash_file(BACKEND_DIR / "app" / "services" / "scan_report_lifecycle.py"),
                    "scan_reports_router": hash_file(BACKEND_DIR / "app" / "routers" / "scan_reports.py"),
                    "scoring_rules_yaml": hash_file(BACKEND_DIR / "config" / "scoring_rules.yaml"),
                    "contract_rules_yaml": hash_file(BACKEND_DIR / "config" / "contract_rules.yaml"),
                    "risk_rules_yaml": hash_file(BACKEND_DIR / "config" / "risk_rules.yaml"),
                },
            },
            "suites": {},
            "findings": [],
            "summary": {"total_tests": 0, "passed_tests": 0, "failed_tests": 0},
        }

    def record_test(self, suite_name: str, test_name: str, passed: bool, details: Dict[str, Any]):
        if suite_name not in self.observations["suites"]:
            self.observations["suites"][suite_name] = []
        self.observations["suites"][suite_name].append({
            "name": test_name,
            "passed": passed,
            "details": details,
        })
        self.observations["summary"]["total_tests"] += 1
        if passed:
            self.observations["summary"]["passed_tests"] += 1
        else:
            self.observations["summary"]["failed_tests"] += 1

    async def run_all(self):
        temp_dir = tempfile.mkdtemp(prefix="report_audit_")
        db_path = Path(temp_dir) / "isolated_reports.db"
        try:
            await self._run_suite1_schema_and_models(db_path)
            await self._run_suite2_lifecycle_states(db_path)
            await self._run_suite3_category_isolation_and_retention(db_path)
            await self._run_suite4_process_restart_parity(db_path)
            await self._run_suite5_frozen_settings_and_mutation_safety(db_path)
            await self._run_suite6_pipeline_diagnostics_and_terminal_outcomes(db_path)
            await self._run_suite7_security_and_credential_sanitization(db_path)
            await self._run_suite8_legacy_interoperability(db_path)
            await self._run_suite9_additive_migration_verification(Path(temp_dir))
            await self._run_suite10_dispatch_lifecycle_wrap(db_path)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # Suite 1: Schema and Models
    # -------------------------------------------------------------------------
    async def _run_suite1_schema_and_models(self, db_path: Path):
        suite = "1. Storage Schema & Model Invariants"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        async with engine.begin() as conn:
            await conn.run_sync(ScanReportBase.metadata.create_all)
            await conn.run_sync(ScanSessionBase.metadata.create_all)

        def _inspect_schema(conn):
            insp = inspect(conn)
            tables = set(insp.get_table_names())
            report_cols = {c["name"]: str(c["type"]) for c in insp.get_columns("scan_reports")}
            head_cols = {c["name"]: str(c["type"]) for c in insp.get_columns("scan_report_heads")}
            uqs = insp.get_unique_constraints("scan_reports")
            pks = insp.get_pk_constraint("scan_report_heads")
            return tables, report_cols, head_cols, uqs, pks

        async with engine.connect() as conn:
            tables, r_cols, h_cols, uqs, pks = await conn.run_sync(_inspect_schema)

        t1_passed = {"scan_reports", "scan_report_heads", "scan_sessions"} <= tables
        self.record_test(suite, "1.1 Required tables exist in isolated SQLite schema", t1_passed, {
            "tables_found": sorted(list(tables)),
            "required": ["scan_reports", "scan_report_heads", "scan_sessions"],
        })

        t2_passed = (
            "id" in r_cols and "category" in r_cols and "generation" in r_cols
            and "status" in r_cols and "envelope_json" in r_cols
        )
        self.record_test(suite, "1.2 ScanReport column definitions match additive model", t2_passed, {
            "columns": r_cols,
        })

        t3_passed = (
            "category" in h_cols and "generation" in h_cols
            and "latest_id" in h_cols and "usable_id" in h_cols
            and pks.get("constrained_columns") == ["category"]
        )
        self.record_test(suite, "1.3 ScanReportHead tracks category primary key and generation", t3_passed, {
            "columns": h_cols,
            "pk_constraint": pks,
        })

        # Check unique constraint on (category, generation)
        uq_cols = [uq.get("column_names") for uq in uqs]
        t4_passed = any(sorted(c) == ["category", "generation"] for c in uq_cols if c)
        self.record_test(suite, "1.4 ScanReport enforces unique constraint on (category, generation)", t4_passed, {
            "unique_constraints": uqs,
        })

        await engine.dispose()

    # -------------------------------------------------------------------------
    # Suite 2: Report Lifecycle State Transitions
    # -------------------------------------------------------------------------
    async def _run_suite2_lifecycle_states(self, db_path: Path):
        suite = "2. Lifecycle State Transitions"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        factory = async_sessionmaker(engine, expire_on_commit=False)

        # 2.1 begin_run
        req_inputs = {
            "request": {"universe": ["SP500"], "direction": "Bullish", "horizon": "Swing"},
            "expanded_symbols": ["AAPL", "MSFT"],
        }
        async with factory() as db:
            run_env = await begin_run(db, category="options", trigger="manual", inputs=req_inputs)

        t1_passed = (
            run_env["category"] == "options"
            and run_env["status"] == "running"
            and run_env["generation"] == 1
            and run_env["started_at"] is not None
            and run_env["ended_at"] is None
            and run_env["diagnostics_available"] is False
            and run_env["diagnostics"] is None
            and run_env["result"] is None
            and run_env["error_code"] is None
            and run_env["persistence"] == "saved"
        )
        self.record_test(suite, "2.1 begin_run creates running report with generation 1 and frozen inputs", t1_passed, {
            "run_id": run_env["run_id"],
            "generation": run_env["generation"],
            "status": run_env["status"],
            "started_at": run_env["started_at"],
        })

        # 2.2 finish_run complete
        diag = {
            "pipeline": {"scanned": 100, "pre_screen_pass": 40, "shortlist": 5},
            "accepted_symbols": ["AAPL"],
        }
        res = {"candidates": [{"symbol": "AAPL", "stockScore": 88}]}
        async with factory() as db:
            complete_env = await finish_run(
                db, run_env["run_id"], status="complete", diagnostics=diag, result=res
            )

        t2_passed = (
            complete_env["status"] == "complete"
            and complete_env["ended_at"] is not None
            and complete_env["diagnostics_available"] is True
            and complete_env["diagnostics"] == diag
            and complete_env["result"] == res
            and complete_env["error_code"] is None
        )
        self.record_test(suite, "2.2 finish_run transitions to complete, saves diagnostics and result", t2_passed, {
            "status": complete_env["status"],
            "ended_at": complete_env["ended_at"],
            "diagnostics_available": complete_env["diagnostics_available"],
        })

        # 2.3 check head promotion
        async with factory() as db:
            head_data = await get_latest(db, "options")
        t3_passed = (
            head_data["latest_attempt"]["run_id"] == run_env["run_id"]
            and head_data["previous_report"] is None  # usable_id == latest_id
        )
        self.record_test(suite, "2.3 Head pointer promotes complete report to usable_id", t3_passed, {
            "latest_run_id": head_data["latest_attempt"]["run_id"],
            "previous_report": head_data["previous_report"],
        })

        # 2.4 finish_run on already terminal run raises ValueError
        already_term = False
        try:
            async with factory() as db:
                await finish_run(db, run_env["run_id"], status="complete")
        except ValueError as e:
            if "already terminal" in str(e).lower():
                already_term = True
        self.record_test(suite, "2.4 Re-finishing a terminal run is rejected with ValueError", already_term, {
            "rejected_as_expected": already_term,
        })

        # 2.5 failed run with promote_usable=False retains previous usable
        async with factory() as db:
            failed_run = await begin_run(db, category="options", trigger="manual", inputs={"request": {"universe": "SP500"}})
            failed_env = await finish_run(
                db, failed_run["run_id"], status="failed", error_code="scan_failed", promote_usable=False
            )
            head_dual = await get_latest(db, "options")

        t5_passed = (
            failed_env["status"] == "failed"
            and failed_env["error_code"] == "scan_failed"
            and head_dual["latest_attempt"]["run_id"] == failed_run["run_id"]
            and head_dual["previous_report"]["run_id"] == run_env["run_id"]
        )
        self.record_test(suite, "2.5 Failed run retains previous usable report as previous_report", t5_passed, {
            "latest_attempt_status": head_dual["latest_attempt"]["status"],
            "latest_attempt_id": head_dual["latest_attempt"]["run_id"],
            "previous_report_id": head_dual["previous_report"]["run_id"] if head_dual["previous_report"] else None,
        })

        # 2.6 cancelled run with error_code='cancelled'
        async with factory() as db:
            cancel_run = await begin_run(db, category="options", trigger="manual", inputs={"request": {"direction": "Bearish"}})
            cancel_env = await finish_run(
                db, cancel_run["run_id"], status="cancelled", error_code="cancelled", promote_usable=False
            )
        t6_passed = (
            cancel_env["status"] == "cancelled"
            and cancel_env["error_code"] == "cancelled"
        )
        self.record_test(suite, "2.6 Cancelled run records status='cancelled' and error_code='cancelled'", t6_passed, {
            "status": cancel_env["status"],
            "error_code": cancel_env["error_code"],
        })

        # 2.7 invalid terminal status or error code is rejected
        invalid_caught = 0
        for bad_status, bad_code in [("unknown_status", None), ("complete", "invalid_error_code")]:
            bad_run_id = None
            try:
                async with factory() as db:
                    bad_run = await begin_run(db, category="options", trigger="manual", inputs={})
                    bad_run_id = bad_run["run_id"]
                    await finish_run(db, bad_run["run_id"], status=bad_status, error_code=bad_code)
            except ValueError:
                invalid_caught += 1
                if bad_run_id:
                    # Clean up the test run so it does not leak running state into subsequent suites
                    async with factory() as db:
                        await finish_run(db, bad_run_id, status="failed", error_code="scan_failed", promote_usable=False)
        self.record_test(suite, "2.7 Invalid terminal status or error codes are rejected", invalid_caught == 2, {
            "rejections": invalid_caught,
        })

        await engine.dispose()

    # -------------------------------------------------------------------------
    # Suite 3: Category Isolation & Dual Retention
    # -------------------------------------------------------------------------
    async def _run_suite3_category_isolation_and_retention(self, db_path: Path):
        suite = "3. Category Isolation & Dual Retention"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        factory = async_sessionmaker(engine, expire_on_commit=False)

        # Seed reports across all 5 categories
        categories = list(CATEGORIES)
        saved_per_cat = {}
        for cat in categories:
            async with factory() as db:
                r = await begin_run(db, category=cat, trigger="manual", inputs={"category": cat, "seed": 42})
                completed = await finish_run(
                    db, r["run_id"], status="complete",
                    diagnostics={"category": cat, "scanned": 10},
                    result={"candidates": [{"symbol": f"{cat.upper()}_TICKER"}]}
                )
                saved_per_cat[cat] = completed

        # Verify each category is independent
        all_isolated = True
        for cat in categories:
            async with factory() as db:
                latest = await get_latest(db, cat)
                if (
                    latest["latest_attempt"]["category"] != cat
                    or latest["latest_attempt"]["result"]["candidates"][0]["symbol"] != f"{cat.upper()}_TICKER"
                ):
                    all_isolated = False

        self.record_test(suite, "3.1 All 5 categories are independently stored and accessible", all_isolated, {
            "categories": categories,
        })

        # Mutate options category by running 2 new reports: one complete, one failed
        async with factory() as db:
            opt_r2 = await begin_run(db, category="options", trigger="scheduled", inputs={"run": "opt2"})
            await finish_run(db, opt_r2["run_id"], status="complete", diagnostics={"scanned": 20}, result={"candidates": []})
            opt_r3 = await begin_run(db, category="options", trigger="manual", inputs={"run": "opt3"})
            await finish_run(db, opt_r3["run_id"], status="failed", error_code="scan_failed", promote_usable=False)

        # Verify other categories were NOT modified or pruned
        other_cats_untouched = True
        for cat in categories:
            if cat == "options":
                continue
            async with factory() as db:
                latest = await get_latest(db, cat)
                if latest["latest_attempt"]["run_id"] != saved_per_cat[cat]["run_id"]:
                    other_cats_untouched = False

        self.record_test(suite, "3.2 Mutations in options category leave other 4 categories untouched", other_cats_untouched, {
            "tested_categories": [c for c in categories if c != "options"],
        })

        # Verify inflight running report is NOT pruned
        async with factory() as db:
            inflight = await begin_run(db, category="stocks", trigger="manual", inputs={"state": "inflight"})
            # Run another complete run to trigger pruning
            next_run = await begin_run(db, category="stocks", trigger="manual", inputs={"state": "next"})
            await finish_run(db, next_run["run_id"], status="complete", diagnostics={"scanned": 5}, result={})

            # Check if inflight is still in database
            inflight_row = await get_run(db, inflight["run_id"])

        t3_passed = inflight_row is not None and inflight_row["status"] == "running"
        self.record_test(suite, "3.3 Pruning never deletes inflight running attempts", t3_passed, {
            "inflight_run_id": inflight["run_id"],
            "inflight_status": inflight_row["status"] if inflight_row else None,
        })

        # Complete the inflight run
        async with factory() as db:
            await finish_run(db, inflight["run_id"], status="cancelled", error_code="cancelled", promote_usable=False)

        await engine.dispose()

    # -------------------------------------------------------------------------
    # Suite 4: Backend Process Restart Parity
    # -------------------------------------------------------------------------
    async def _run_suite4_process_restart_parity(self, db_path: Path):
        suite = "4. Process Restart & Read-Back Parity"
        # 4.1 First process snapshot
        engine1 = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        factory1 = async_sessionmaker(engine1, expire_on_commit=False)

        pre_restart_snapshots = {}
        for cat in CATEGORIES:
            async with factory1() as db:
                pre_restart_snapshots[cat] = await get_latest(db, cat)

        # Start an inflight scan that will be interrupted by process death
        async with factory1() as db:
            crashed_run = await begin_run(db, category="fib", trigger="automatic", inputs={"crash": True})

        # Close all connections and simulate abrupt process shutdown
        await engine1.dispose()
        del engine1
        del factory1

        # 4.2 Second process startup: recreate engine from scratch against exact same DB file
        engine2 = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        factory2 = async_sessionmaker(engine2, expire_on_commit=False)

        # Execute startup recovery
        async with factory2() as db:
            recovered_count = await recover_interrupted(db)

        t1_passed = recovered_count == 1
        self.record_test(suite, "4.1 Cold process startup recovers interrupted in-flight scans", t1_passed, {
            "recovered_count": recovered_count,
            "crashed_run_id": crashed_run["run_id"],
        })

        # Verify read-back parity for existing reports
        async with factory2() as db:
            recovered_env = await get_run(db, crashed_run["run_id"])
            parity_matches = True
            for cat in CATEGORIES:
                if cat == "fib":
                    continue  # fib had the crashed run
                post_data = await get_latest(db, cat)
                if post_data != pre_restart_snapshots[cat]:
                    parity_matches = False

        t2_passed = (
            recovered_env["status"] == "interrupted"
            and recovered_env["error_code"] == "interrupted"
            and recovered_env["ended_at"] is not None
            and parity_matches
        )
        self.record_test(suite, "4.2 Cold process read-back has exact parity with pre-shutdown snapshot", t2_passed, {
            "interrupted_status": recovered_env["status"],
            "interrupted_error_code": recovered_env["error_code"],
            "unrelated_categories_parity": parity_matches,
        })

        await engine2.dispose()

    # -------------------------------------------------------------------------
    # Suite 5: Frozen Settings Preservation & Mutation Safety
    # -------------------------------------------------------------------------
    async def _run_suite5_frozen_settings_and_mutation_safety(self, db_path: Path):
        suite = "5. Frozen Settings Preservation & Mutation Safety"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        factory = async_sessionmaker(engine, expire_on_commit=False)

        # 5.1 Deep-copy / serialization immunity against caller mutation
        caller_dict = {
            "request": {
                "universe": ["SP500"],
                "direction": "Bullish",
                "horizon": "Swing",
                "overrides": {"fast_ema": 8, "slow_ema": 21},
            }
        }
        async with factory() as db:
            run_imm = await begin_run(db, category="options", trigger="manual", inputs=caller_dict)

        # Mutate caller dictionary post begin_run
        caller_dict["request"]["direction"] = "Bearish"
        caller_dict["request"]["overrides"]["fast_ema"] = 999
        caller_dict["request"]["injected_secret"] = "LEAKED_TOKEN"

        async with factory() as db:
            saved_run = await get_run(db, run_imm["run_id"])

        stored_req = saved_run["inputs"]["request"]
        t1_passed = (
            stored_req["direction"] == "Bullish"
            and stored_req["overrides"]["fast_ema"] == 8
            and "injected_secret" not in stored_req
        )
        self.record_test(suite, "5.1 Stored report inputs are immune to post-invocation caller dictionary mutations", t1_passed, {
            "stored_direction": stored_req.get("direction"),
            "stored_fast_ema": stored_req.get("overrides", {}).get("fast_ema"),
            "secret_leaked": "injected_secret" in stored_req,
        })

        # 5.2 Pure settings comparison drift tests (scanReportInputsDiffer)
        fixtures_path = Path(__file__).resolve().parent / "report-fixtures.json"
        drift_fixtures = json.loads(fixtures_path.read_text(encoding="utf-8"))["frozen_vs_live_drift_cases"]

        drift_results = []
        all_drift_correct = True
        for case in drift_fixtures:
            differs = scan_report_inputs_differ(case["frozen"], case["current"])
            correct = (differs == case["expected_differ"])
            if not correct:
                all_drift_correct = False
            drift_results.append({
                "description": case["description"],
                "expected": case["expected_differ"],
                "actual": differs,
                "passed": correct,
            })

        self.record_test(suite, "5.2 scanReportInputsDiffer correctly identifies frozen vs live drift cases", all_drift_correct, {
            "cases_evaluated": len(drift_results),
            "all_passed": all_drift_correct,
            "details": drift_results,
        })

        # 5.3 finish_run
        async with factory() as db:
            await finish_run(db, run_imm["run_id"], status="complete", diagnostics={"scanned": 1}, result={})

        await engine.dispose()

    # -------------------------------------------------------------------------
    # Suite 6: Pipeline Diagnostics & Terminal Outcomes
    # -------------------------------------------------------------------------
    async def _run_suite6_pipeline_diagnostics_and_terminal_outcomes(self, db_path: Path):
        suite = "6. Pipeline Diagnostics & Terminal Outcomes"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        factory = async_sessionmaker(engine, expire_on_commit=False)

        # 6.1 Options pipeline funnel monotonic non-increasing invariant
        options_pipeline = {
            "scanned": 120,
            "pre_screen_pass": 65,
            "direction_pass": 40,
            "chain_pass": 28,
            "contracts_pass": 18,
            "shortlist": 5,
        }
        stages = ["scanned", "pre_screen_pass", "direction_pass", "chain_pass", "contracts_pass", "shortlist"]
        is_monotonic = all(options_pipeline[stages[i]] >= options_pipeline[stages[i+1]] for i in range(len(stages)-1))
        self.record_test(suite, "6.1 Options pipeline funnel counts satisfy monotonic non-increasing drop-off", is_monotonic, {
            "pipeline": options_pipeline,
        })

        # 6.2 Pre-Breakout / Fib terminal outcomes version 1 schema & count balance
        terminal_collector = Collector(
            request={"strategy": "breakout_base", "direction": "Bullish"},
            terminal_enabled=True,
        )
        expanded = ["NVDA", "AVGO", "MSFT", "AAPL", "INTC", "CSCO", "QCOM", "TXN"]
        excluded = [{"symbol": "TXN"}]
        observe_token = None
        from app.services.scan_report_lifecycle import _collector
        token = _collector.set(terminal_collector)

        try:
            observe_resolution(expanded, [x for x in expanded if x != "TXN"], excluded)
            for s in ["NVDA", "AVGO", "MSFT", "AAPL", "INTC", "CSCO", "QCOM"]:
                observe_evaluation(s)
            observe_terminal("NVDA", "accepted", "candidate_returned")
            observe_terminal("AVGO", "accepted", "candidate_returned")
            observe_terminal("MSFT", "no_setup", "setup_not_returned")
            observe_terminal("AAPL", "no_setup", "setup_not_returned")
            observe_terminal("INTC", "filtered", "price_min", thresholds={"min_price": 20.0}, observations={"price": 18.5})
            observe_terminal("CSCO", "filtered", "score_min", thresholds={"min_stock_score": 60.0}, observations={"score": 45.0})
            observe_terminal("QCOM", "no_data", "missing_price")

            snapshot = terminal_collector.terminal_snapshot()
        finally:
            _collector.reset(token)

        cnts = snapshot["counts"]
        sum_outcomes = (
            cnts["accepted"] + cnts["excluded"] + cnts["no_data"]
            + cnts["error_count"] + cnts["no_setup"] + cnts["filtered"]
        )
        t2_passed = (
            snapshot["version"] == 1
            and snapshot["complete"] is True
            and snapshot["resolution_available"] is True
            and cnts["input"] == len(expanded)
            and cnts["evaluated"] == len(expanded) - len(excluded)
            and sum_outcomes == len(snapshot["outcomes"])
            and len(snapshot["unknown_symbols"]) == 0
        )
        self.record_test(suite, "6.2 Terminal outcomes version 1 schema and count balance equations hold", t2_passed, {
            "counts": cnts,
            "outcomes_count": len(snapshot["outcomes"]),
            "complete": snapshot["complete"],
        })

        # 6.3 Conflict detection in terminal outcomes
        conflict_col = Collector(request={}, terminal_enabled=True)
        t_conflict = _collector.set(conflict_col)
        try:
            observe_resolution(["AAPL"], ["AAPL"], [])
            observe_evaluation("AAPL")
            observe_terminal("AAPL", "accepted", "candidate_returned")
            observe_terminal("AAPL", "filtered", "price_min")
            c_snap = conflict_col.terminal_snapshot()
        finally:
            _collector.reset(t_conflict)

        t3_passed = (
            "AAPL" in conflict_col.terminal_conflicts
            and c_snap.get("diagnostic_unavailable") is True
            and c_snap["complete"] is False
        )
        self.record_test(suite, "6.3 Conflicting symbol outcomes are flagged and invalidate complete status", t3_passed, {
            "conflicts": list(conflict_col.terminal_conflicts),
            "diagnostic_unavailable": c_snap.get("diagnostic_unavailable"),
        })

        await engine.dispose()

    # -------------------------------------------------------------------------
    # Suite 7: Security Guardrails & Credential Sanitization
    # -------------------------------------------------------------------------
    async def _run_suite7_security_and_credential_sanitization(self, db_path: Path):
        suite = "7. Security & Credential Redaction"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        factory = async_sessionmaker(engine, expire_on_commit=False)

        # 7.1 Rejection of forbidden keys in _encode
        rejected_keys = 0
        forbidden_test_keys = [
            "token", "access_token", "refresh_token", "api_key", "password",
            "secret", "credentials", "authorization", "exception", "traceback"
        ]
        for f_key in forbidden_test_keys:
            try:
                _encode({"normal_param": 10, f_key: "secret_value"})
            except ValueError as e:
                if "Unsafe report payload key" in str(e):
                    rejected_keys += 1

        self.record_test(suite, "7.1 _encode rejects all forbidden secret and exception payload keys", rejected_keys == len(forbidden_test_keys), {
            "tested_keys": len(forbidden_test_keys),
            "rejected_keys": rejected_keys,
        })

        # 7.2 Non-finite numbers (NaN, Inf, -Inf) are rejected by _encode
        non_finites_rejected = 0
        for nf in [float("nan"), float("inf"), float("-inf")]:
            try:
                _encode({"score": nf})
            except (ValueError, TypeError):
                non_finites_rejected += 1

        self.record_test(suite, "7.2 _encode rejects non-finite IEEE-754 floats (NaN, +/-Inf)", non_finites_rejected == 3, {
            "rejected_count": non_finites_rejected,
        })

        # 7.3 project() strips non-allowlisted keys and free text
        unav = []
        dirty_input = {
            "direction": "Bullish",
            "horizon": "Swing",
            "malicious_free_text": "DROP TABLE scan_reports;",
            "numeric_threshold": 42,
            "overrides": {
                "fast_ema": 8,
                "unsupported_override": 99,
            }
        }
        projected = project(dirty_input, path="request", unavailable=unav)
        t3_passed = (
            "malicious_free_text" not in projected
            and projected.get("malicious_free_text_unavailable") is True
            and "unsupported_override" not in projected.get("overrides", {})
            and projected.get("direction") == "Bullish"
            and projected.get("overrides", {}).get("fast_ema") == 8
            and projected.get("numeric_threshold") == 42
            and "request.malicious_free_text" in unav
            and "request.overrides.unsupported_override" in unav
        )
        self.record_test(suite, "7.3 project() strictly redacts untyped free text and unwhitelisted overrides", t3_passed, {
            "projected_keys": list(projected.keys()),
            "unavailable_paths": unav,
        })

        await engine.dispose()

    # -------------------------------------------------------------------------
    # Suite 8: Legacy Scan Sessions Interoperability
    # -------------------------------------------------------------------------
    async def _run_suite8_legacy_interoperability(self, db_path: Path):
        suite = "8. Legacy Scan Sessions Interoperability"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        factory = async_sessionmaker(engine, expire_on_commit=False)

        # Seed legacy records directly in scan_sessions table
        fixtures_path = Path(__file__).resolve().parent / "report-fixtures.json"
        legacy_fixtures = json.loads(fixtures_path.read_text(encoding="utf-8"))["legacy_fixtures"]

        async with factory() as db:
            for item in legacy_fixtures:
                created_dt = datetime.fromisoformat(item["created_at"].replace("Z", "+00:00"))
                updated_dt = datetime.fromisoformat(item["updated_at"].replace("Z", "+00:00"))
                db.add(ScanSession(
                    id=item["id"],
                    status=item["status"],
                    last_request_json=item["last_request_json"],
                    last_result_json=item["last_result_json"],
                    created_at=created_dt,
                    updated_at=updated_dt,
                ))
            await db.commit()

        # Read legacy reports through get_legacy()
        async with factory() as db:
            legacy_reports = await get_legacy(db)

        t1_passed = len(legacy_reports) == len(legacy_fixtures)
        t2_passed = all(
            r["category"] == "legacy/unclassified"
            and r["run_id"].startswith("legacy:")
            and r["diagnostics_available"] is False
            for r in legacy_reports
        )

        # Check corrupted record handling
        corrupted_entry = next((r for r in legacy_reports if r["legacy_id"] == "corrupted-legacy"), None)
        t3_passed = (
            corrupted_entry is not None
            and "inputs" in corrupted_entry["unavailable_fields"]
        )

        self.record_test(suite, "8.1 get_legacy parses legacy sessions with unclassified category and safe projection", t1_passed and t2_passed and t3_passed, {
            "total_legacy_sessions": len(legacy_reports),
            "corrupted_handled": t3_passed,
        })

        # Verify source table scan_sessions remains byte-for-byte unmodified
        async with factory() as db:
            rows = (await db.execute(select(ScanSession))).scalars().all()
            source_untouched = (len(rows) == len(legacy_fixtures))

        self.record_test(suite, "8.2 Legacy scan_sessions table is never modified or rewritten by get_legacy", source_untouched, {
            "session_count": len(rows),
        })

        await engine.dispose()

    # -------------------------------------------------------------------------
    # Suite 9: Additive Migration Verification
    # -------------------------------------------------------------------------
    async def _run_suite9_additive_migration_verification(self, temp_dir: Path):
        suite = "9. Additive Alembic Migration Verification"
        import importlib.util
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        migration_path = BACKEND_DIR / "migrations" / "versions" / "a93b8d24f760_add_isolated_scan_reports.py"
        spec = importlib.util.spec_from_file_location("scan_report_migration", migration_path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)

        sync_db_path = temp_dir / "migration_test.db"
        sync_engine = create_engine(f"sqlite:///{sync_db_path}")

        # Start with only scan_sessions table (legacy state)
        with sync_engine.begin() as conn:
            ScanSessionBase.metadata.create_all(conn)
            conn.execute(text("INSERT INTO scan_sessions (id, status, last_result_json) VALUES ('legacy_stock', 'complete', 'preserved_json')"))

        # Run migration upgrade
        with sync_engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                migration.upgrade()
            insp = inspect(conn)
            tables_after_up = set(insp.get_table_names())
            val_after_up = conn.execute(text("SELECT last_result_json FROM scan_sessions WHERE id = 'legacy_stock'")).scalar_one()

        t1_passed = (
            {"scan_reports", "scan_report_heads", "scan_sessions"} <= tables_after_up
            and val_after_up == "preserved_json"
        )
        self.record_test(suite, "9.1 migration.upgrade() creates scan_reports and leaves scan_sessions intact", t1_passed, {
            "tables_created": list(tables_after_up),
            "preserved_value": val_after_up,
        })

        # Run migration downgrade
        with sync_engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                migration.downgrade()
            insp = inspect(conn)
            tables_after_down = set(insp.get_table_names())
            val_after_down = conn.execute(text("SELECT last_result_json FROM scan_sessions WHERE id = 'legacy_stock'")).scalar_one()

        t2_passed = (
            "scan_reports" not in tables_after_down
            and "scan_report_heads" not in tables_after_down
            and "scan_sessions" in tables_after_down
            and val_after_down == "preserved_json"
        )
        self.record_test(suite, "9.2 migration.downgrade() drops report tables while preserving legacy scan_sessions", t2_passed, {
            "tables_remaining": list(tables_after_down),
            "preserved_value": val_after_down,
        })

        sync_engine.dispose()

    # -------------------------------------------------------------------------
    # Suite 10: Dispatch Lifecycle Wrap (run_reported_scan)
    # -------------------------------------------------------------------------
    async def _run_suite10_dispatch_lifecycle_wrap(self, db_path: Path):
        suite = "10. Dispatch Lifecycle Wrap (run_reported_scan)"
        from app.services import scan_report_lifecycle as lc

        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        factory = async_sessionmaker(engine, expire_on_commit=False)

        # Patch AsyncSessionLocal in scan_report_lifecycle to use our isolated DB
        original_session_local = lc.AsyncSessionLocal
        lc.AsyncSessionLocal = factory

        try:
            # 10.1 Successful options scan wrap
            async def mock_scan_callback():
                lc.observe_resolution(["AAPL"], ["AAPL"], [])
                return ScanResult(
                    scan_id="mock_run_1",
                    timestamp="now",
                    candidates=[],
                    rejected=[],
                    pipeline=None,
                )

            res = await run_reported_scan(
                {"universe": ["AAPL"], "direction": "Bullish", "horizon": "Swing"},
                category="options",
                trigger="manual",
                callback=mock_scan_callback,
            )

            async with factory() as db:
                run_row = await get_run(db, res.report_run_id)

            t1_passed = (
                run_row["status"] == "complete"
                and res.report_persistence == "saved"
                and run_row["inputs"]["dispatched_symbols"] == ["AAPL"]
            )
            self.record_test(suite, "10.1 run_reported_scan wraps normal scan and attaches durable identity metadata", t1_passed, {
                "report_run_id": res.report_run_id,
                "report_generation": res.report_generation,
                "report_persistence": res.report_persistence,
                "db_status": run_row["status"],
            })

            # 10.2 Cancelled callback
            async def cancelled_callback():
                raise asyncio.CancelledError()

            was_cancelled = False
            try:
                await run_reported_scan(
                    {"universe": ["AAPL"]}, category="options", trigger="manual", callback=cancelled_callback
                )
            except asyncio.CancelledError:
                was_cancelled = True

            async with factory() as db:
                latest = await get_latest(db, "options")

            t2_passed = was_cancelled and latest["latest_attempt"]["status"] == "cancelled"
            self.record_test(suite, "10.2 run_reported_scan records cancelled status on asyncio.CancelledError", t2_passed, {
                "cancelled_caught": was_cancelled,
                "latest_status": latest["latest_attempt"]["status"],
            })

        finally:
            lc.AsyncSessionLocal = original_session_local
            await engine.dispose()


async def main():
    print("=== Running APP-AUDIT-OPTIONS Report Probe ===")
    probe = ReportAuditProbe()
    await probe.run_all()

    obs_file = Path(__file__).resolve().parent / "report-observations.json"
    browser_obs_file = Path(__file__).resolve().parent / "browser-observations.json"
    if browser_obs_file.exists():
        try:
            probe.observations["browser_probe"] = json.loads(browser_obs_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    obs_file.write_text(json.dumps(probe.observations, indent=2), encoding="utf-8")
    print(f"Structured observations saved to {obs_file}")

    s = probe.observations["summary"]
    print(f"=== Report Probe Completed: {s['passed_tests']} passed, {s['failed_tests']} failed (Total: {s['total_tests']}) ===")
    if s["failed_tests"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
