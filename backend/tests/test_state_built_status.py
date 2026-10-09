"""Pin built/unmerged status without weakening presence or audit warnings."""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "state.py"
_spec = importlib.util.spec_from_file_location("state_built_script", _SCRIPT_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


@pytest.fixture()
def state_run(tmp_path, monkeypatch, capsys):
    marker = tmp_path / "feature.py"
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(_mod, "ROOT", tmp_path)
    monkeypatch.setattr(_mod, "STATE", state_file)
    monkeypatch.setattr(_mod, "audit_bookkeeping_drift", lambda state: None)

    def run(status, *, present=True, clean=True, rounds=1, quiet=True):
        marker.write_text("feature_ready = True\n" if present else "", encoding="utf-8")
        state_file.write_text(json.dumps({
            "updated": "2026-10-06",
            "main": "merged baseline",
            "working_branch": "feature",
            "phases": [{
                "id": "TARGET",
                "name": "Built feature",
                "status": status,
                "audit_rounds": rounds,
                "audit_clean": clean,
                "verify": {
                    "kind": "present", "path": "feature.py", "pattern": "feature_ready",
                },
            }],
            "authoritative_documents": [],
        }), encoding="utf-8")
        monkeypatch.setattr(_mod.sys, "argv", ["state.py", "--quiet"] if quiet else ["state.py"])
        exit_code = _mod.main()
        output = re.sub(r"\x1b\[[0-9;]*m", "", capsys.readouterr().out)
        return exit_code, output

    return run


def test_clean_built_code_is_accepted_before_merge(state_run):
    code, output = state_run("built")
    assert code == 0, output
    assert output == ""


@pytest.mark.parametrize("clean", [False, "false"])
@pytest.mark.parametrize("rounds", [0, 2])
def test_built_code_without_clean_audit_is_reported(state_run, clean, rounds):
    code, output = state_run("built", clean=clean, rounds=rounds)
    assert code == 0, output
    assert "STATE DRIFT" not in output
    assert "UNAUDITED WORK" in output
    assert f"Phase TARGET (Built feature) — {rounds} round(s) run, none clean" in output


def test_built_claim_with_missing_code_is_drift(state_run):
    code, output = state_run("built", present=False)
    assert code == 1, output
    assert "declared 'built' but the code says NOT BUILT" in output


def test_built_label_is_distinct_from_shipped(state_run):
    code, output = state_run("built", quiet=False)
    assert code == 0, output
    assert "BUILT" in output.split("Built feature", 1)[1].splitlines()[0]
    assert "clean after 1" in output


def test_unaudited_built_render_shows_never_audited(state_run):
    code, output = state_run("built", clean=False, rounds=0, quiet=False)
    assert code == 0, output
    assert "NEVER AUDITED" in output
    assert "UNAUDITED WORK" in output


@pytest.mark.parametrize("status", ["not_started", "in_progress"])
def test_unbuilt_status_with_built_code_remains_drift(state_run, status):
    code, output = state_run(status)
    assert code == 1, output
    assert f"declared '{status}' but the code says BUILT" in output


@pytest.mark.parametrize("status", ["shipped", "shipped_unaudited"])
def test_existing_built_statuses_still_match_present_code(state_run, status):
    code, output = state_run(status)
    assert code == 0, output


@pytest.mark.parametrize("status", ["shipped", "shipped_unaudited"])
def test_existing_built_statuses_still_detect_missing_code(state_run, status):
    code, output = state_run(status, present=False)
    assert code == 1, output
    assert "NOT BUILT" in output
