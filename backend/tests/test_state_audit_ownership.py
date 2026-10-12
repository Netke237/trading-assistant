"""Real-git regressions for explicit audit-record phase ownership."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from tests.test_state_audit_bookkeeping import Repo, repo as git_repo, STATE_REL

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "state.py"
_spec = importlib.util.spec_from_file_location("state_ownership_script", _SCRIPT_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

P0A = "STOCKS-HORIZON-P0A"
P0B = "STOCKS-HORIZON-P0B"
PREREQUISITE = "STATE-AUDIT-MULTI-PHASE"


def _state(active=P0B, *, clean=True, rounds=2):
    return {
        "active_phase": active,
        "phases": [
            {"id": phase, "name": phase, "audit_rounds": rounds if phase == P0B else 0,
             "audit_clean": clean if phase == P0B else False}
            for phase in (P0A, P0B, P0B + "-EXTRA", PREREQUISITE)
        ],
        "already_shipped": [],
    }


@pytest.fixture()
def repo(git_repo: Repo, monkeypatch):
    git_repo.write_state(_state(), "Introduce phases together")
    monkeypatch.setattr(_mod, "ROOT", git_repo.path)
    monkeypatch.setattr(_mod, "STATE", git_repo.path / STATE_REL)
    return git_repo


@pytest.mark.parametrize("stage", ["", "plan ", "code "])
@pytest.mark.parametrize("clean", [True, False])
def test_explicit_other_phase_rounds_do_not_count_against_p0b(repo, stage, clean):
    repo.commit(f"docs(state): {P0B} round 2 plan clean")
    repo.commit(f"docs(state): {P0A} {stage}round 3 (code round 2) clean")
    repo.commit(f"docs(state): {PREREQUISITE} round 1 plan clean")
    assert _mod.audit_bookkeeping_drift(_state(clean=clean)) is None


def test_active_phases_own_round_still_reports_undercount(repo):
    repo.commit(f"docs(state): {P0A} round 9 clean")
    repo.commit(f"docs(state): {P0B} round 3 (code round 1)")
    severity, message = _mod.audit_bookkeeping_drift(_state())
    assert severity == "drift"
    assert "reach round 3" in message
    assert "declares 2" in message


@pytest.mark.parametrize("subject", [
    "round 3 unowned evidence",
    f"docs(state): UNKNOWN-PHASE round 3 references {P0A}",
    "docs(state): P0A round 3 shorthand",
    f"fix(state): {P0A} round 3 other prefix",
    f"Docs(state): {P0A} round 3 other case",
    f"docs(state): {P0A.lower()} round 3 mismatched owner case",
    f"docs(state): {P0A} r3 shorthand round",
    f"docs(state): {P0A} round 3 interacts with {P0B}",
    f"docs(state): {P0A} round 3 interacts with ({P0B})",
    f"docs(state): {P0A} round 3 interacts with {P0B} / {PREREQUISITE}",
    f"docs(state): {P0A} and {P0B} round 3 ambiguous ownership",
    f"docs(state): {P0B}-UNKNOWN round 3 prefix is not an owner",
    f"docs(state): {P0B} round 3 own evidence",
])
def test_unknown_ambiguous_and_active_evidence_still_reports_undercount(repo, subject):
    repo.commit(subject)
    severity, message = _mod.audit_bookkeeping_drift(_state())
    assert severity == "drift"
    assert "reach round 3" in message
    assert "declares 2" in message


@pytest.mark.parametrize("subject", [
    f"docs(state): {P0B}-EXTRA round 3 clean",
    f"docs(state): {P0A} round 3 interacts with {P0B}-EXTRA",
    f"docs(state): {P0A} round 3 refers to x{P0B}",
    f"docs(state): {P0A} round 3 refers to {P0B}_EXTRA",
])
def test_active_id_must_match_a_whole_token(repo, subject):
    repo.commit(subject)
    assert _mod.audit_bookkeeping_drift(_state()) is None


@pytest.mark.parametrize("active", [None, "UNKNOWN-PHASE"])
@pytest.mark.parametrize("round_number, expected", [(2, "warn"), (3, "drift")])
def test_missing_or_unresolved_pointer_retains_all_evidence(repo, active, round_number, expected):
    repo.commit(f"docs(state): {P0A} round {round_number} clean")
    state = _state(active=active)
    if active is None:
        state.pop("active_phase")
    severity, message = _mod.audit_bookkeeping_drift(state)
    assert severity == expected
    assert f"reach round {round_number}" in message
    assert "nothing in PROJECT_STATE.json is counting them" in message


def test_already_shipped_pointer_does_not_enable_phase_filtering(repo):
    repo.commit(f"docs(state): {P0A} round 3 clean")
    state = _state(active="legacy piece")
    state["already_shipped"] = [{"name": "legacy piece", "audit_rounds": 2, "audit_clean": True}]
    severity, message = _mod.audit_bookkeeping_drift(state)
    assert severity == "drift"
    assert "reach round 3" in message


def test_default_helper_callers_keep_all_rounds(repo):
    subject = f"docs(state): {P0A} round 3 clean"
    repo.commit(subject)
    assert _mod._round_numbers_in_branch_subjects("origin/main") == (3, [subject])


def test_active_phase_cap_and_strict_clean_check_still_apply(repo):
    repo.commit(f"docs(state): {P0B} round 3 still open")
    severity, message = _mod.audit_bookkeeping_drift(_state(rounds=3, clean="false"))
    assert severity == "drift"
    assert "HARD CAP" in message
    assert "NONE of them clean" in message


def test_commit_body_does_not_make_other_owned_round_active(repo):
    repo.commit(f"docs(state): {P0A} round 3 clean", body=f"Interacts with {P0B} round 4")
    assert _mod.audit_bookkeeping_drift(_state()) is None


def test_merged_history_remains_excluded_with_phase_ownership(repo):
    repo.git("checkout", "-q", "main")
    repo.commit(f"docs(state): {P0B} round 9 merged elsewhere")
    repo.set_origin_main()
    repo.git("checkout", "-q", "feature")
    repo.git("merge", "-q", "--no-ff", "main", "-m", "Bring merged history current")
    repo.commit(f"docs(state): {P0A} round 3 clean")
    repo.commit(f"docs(state): {P0B} round 2 plan clean")
    assert _mod.audit_bookkeeping_drift(_state()) is None


HISTORICAL_MIXED_SUBJECT = (
    "docs(state): P0A plan round 1 clean; P0B plan round 1, 3 findings fixed in the plan"
)


@pytest.mark.parametrize("subject, expected_round", [
    (HISTORICAL_MIXED_SUBJECT, 1),
    ("round 1, 3 findings fixed", 1),
    ("ROUND 1, 3 FINDINGS fixed", 1),
    ("round 1, 3 finding fixed", 1),
    ("round 1, 2, 3 findings fixed", 3),
    ("round 1, 2 and 3 findings fixed", 3),
    ("round 1, round 2, 3 findings fixed", 2),
    ("round 1, 3 findings fixed; round 2 clean", 2),
    ("round 3 findings fixed", 3),
    ("round 1, round 3 findings fixed", 3),
    ("round 1, r3 findings fixed", 3),
    ("r1, 3 findings fixed", 3),
    ("rounds 1, 3 findings fixed", 3),
    ("ROUNDS 1, 3 FINDINGS fixed", 3),
    ("round 1, 3 unknown counts", 3),
    ("round 1, 3 finding_count fixed", 3),
    ("round 1, 3 findings fixed; r4 clean", 4),
    ("round 1, 3 findings fixed; rounds 2, 4 clean", 4),
    ("clean after 3 rounds, 1 finding", 3),
])
def test_finding_counts_are_not_implicit_singular_rounds(repo, subject, expected_round):
    repo.commit(subject)
    # Parsing is corrected even for callers that do not opt into ownership.
    assert _mod._round_numbers_in_branch_subjects("origin/main") == (
        expected_round, [subject]
    )


@pytest.mark.parametrize("subject", [
    HISTORICAL_MIXED_SUBJECT,
    f"docs(state): {P0A} round 1, 3 findings fixed with {P0B}",
    f"docs(state): UNKNOWN-PHASE round 1, 3 findings fixed with {P0B}",
])
def test_mixed_or_unowned_finding_subject_retains_primary_round(repo, subject):
    repo.commit(subject)
    assert _mod._round_numbers_in_branch_subjects(
        "origin/main", active_phase=P0B, known_phase_ids={P0A, P0B}
    ) == (1, [subject])
    repo.commit(f"docs(state): {P0B} round 2 plan clean")
    assert _mod.audit_bookkeeping_drift(_state()) is None


@pytest.mark.parametrize("subject", [
    f"docs(state): {P0A} round 1, round 3 findings fixed with {P0B}",
    f"docs(state): UNKNOWN-PHASE round 1, r3 findings fixed with {P0B}",
    f"docs(state): P0A rounds 1, 3 findings fixed with {P0B}",
])
def test_explicit_or_plural_mixed_finding_subject_still_reports_undercount(repo, subject):
    repo.commit(subject)
    severity, message = _mod.audit_bookkeeping_drift(_state())
    assert severity == "drift"
    assert "reach round 3" in message
    assert "declares 2" in message


@pytest.mark.parametrize("continuation", ["-", "..", "+", "/", "&", " and ", " to "])
def test_noncomma_finding_continuation_delimiters_remain_round_evidence(repo, continuation):
    subject = f"round 1{continuation}3 findings fixed"
    repo.commit(subject)
    assert _mod._round_numbers_in_branch_subjects("origin/main") == (3, [subject])
