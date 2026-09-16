# backend/tests/test_state_audit_bookkeeping.py
"""Tests for scripts/state.py's audit-bookkeeping probe -- the one check in
that script that reads git history instead of a code symbol.

Two defects are pinned here, both of which made the probe return None on every
single run rather than fail loudly:

  1. It took its base ref from `state["main"]`, a field that stopped being a
     sha and became a narrative paragraph at 2242f36 (2026-09-09). The ref
     guard then rejected it, silently, for a week.
  2. It resolved `active_phase` against `phases` only and returned None when
     that came up empty -- throwing away the git evidence it had just
     computed. Work that is not a phase (a scoped piece) had nowhere to point,
     so four adversarial rounds ran under a rendered "No drift".

The tests drive a REAL temporary git repo rather than mocking subprocess,
because both defects were about which value reached git, not about what git
said back. scripts/ is not a package, so the module is loaded via importlib,
matching test_update_sp500_liquidity_script.py.
"""
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).parent.parent.parent / "scripts" / "state.py"
_spec = importlib.util.spec_from_file_location("state_script", _SCRIPT_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]


# The shape `state["main"]` has actually had since 2242f36. Every test passes
# this, so any future version that reads a ref out of it fails here.
PROSE_MAIN = (
    "BEARISH DIRECTION-CONVICTION GATE FIX MERGED at 49ffa53 (2026-09-16, "
    "--no-ff). || PREVIOUSLY: PHASE G MERGED at 45ccb2d2."
)


class Repo:
    """A throwaway git repo with `main`, an `origin/main` ref, and a branch."""

    def __init__(self, path: Path):
        self.path = path

    def git(self, *args: str) -> str:
        proc = subprocess.run(
            ["git", *args], cwd=self.path, capture_output=True, text=True, check=True,
        )
        return proc.stdout.strip()

    def commit(self, subject: str, body: str = "") -> None:
        (self.path / "f.txt").write_text(subject + body, encoding="utf-8")
        self.git("add", "-A")
        message = subject if not body else f"{subject}\n\n{body}"
        self.git("commit", "-q", "-m", message)

    def set_origin_main(self, ref: str = "HEAD") -> None:
        self.git("update-ref", "refs/remotes/origin/main", self.git("rev-parse", ref))

    def drop_origin_main(self) -> None:
        self.git("update-ref", "-d", "refs/remotes/origin/main")


@pytest.fixture()
def repo(tmp_path, monkeypatch) -> Repo:
    r = Repo(tmp_path)
    r.git("init", "-q", "-b", "main")
    r.git("config", "user.email", "t@example.com")
    r.git("config", "user.name", "t")
    r.commit("base commit")
    r.set_origin_main()
    r.git("checkout", "-q", "-b", "feature")
    monkeypatch.setattr(_mod, "ROOT", tmp_path)
    return r


def _state(active=None, phases=None, shipped=None) -> dict:
    return {
        "main": PROSE_MAIN,
        "active_phase": active,
        "phases": phases if phases is not None else [
            {"id": "A", "name": "Phase A", "audit_rounds": 7, "audit_clean": True},
        ],
        "already_shipped": shipped if shipped is not None else [],
    }


# --- base ref resolution ---------------------------------------------------

def test_base_ref_prefers_origin_main(repo):
    assert _mod._resolve_base_ref() == "origin/main"


def test_base_ref_falls_back_to_local_main(repo):
    repo.drop_origin_main()
    assert _mod._resolve_base_ref() == "main"


def test_base_ref_is_none_when_no_base_exists(repo):
    repo.drop_origin_main()
    repo.git("branch", "-D", "main")
    assert _mod._resolve_base_ref() is None


def test_base_ref_is_not_read_from_the_state_file(repo):
    """THE REGRESSION. A prose `main` field must not silence the probe."""
    repo.commit("round 4: fix the gate")
    result = _mod.audit_bookkeeping_drift(_state())
    assert result is not None, "prose in state['main'] silenced the probe again"
    assert "round 4" in result[1]


# --- no evidence to read ---------------------------------------------------

def test_silent_when_branch_has_no_commits_beyond_base(repo):
    assert _mod.audit_bookkeeping_drift(_state()) is None


def test_silent_when_no_commit_subject_names_a_round(repo):
    repo.commit("tidy up the resolver")
    assert _mod.audit_bookkeeping_drift(_state()) is None


def test_round_in_body_is_ignored(repo):
    """Bodies are full of backward references; only subjects count."""
    repo.commit("tidy up the resolver", body="follows round 12's findings")
    assert _mod.audit_bookkeeping_drift(_state()) is None


def test_merged_work_goes_quiet(repo):
    """The escape hatch: once origin/main carries the rounds, the range is
    empty and the banner clears itself."""
    repo.commit("round 3: third pass")
    assert _mod.audit_bookkeeping_drift(_state()) is not None
    repo.set_origin_main("feature")
    assert _mod.audit_bookkeeping_drift(_state()) is None


# --- unphased rounds: warn below the cap, drift at it ----------------------

@pytest.mark.parametrize("n", [1, 2])
def test_unphased_rounds_below_the_cap_warn(repo, n):
    repo.commit(f"round {n}: a pass over the piece")
    severity, message = _mod.audit_bookkeeping_drift(_state(active=None))
    assert severity == "warn"
    assert f"round {n}" in message
    assert "active_phase is null" in message
    assert str(_mod.UNPHASED_FAIL_ROUND) in message


@pytest.mark.parametrize("n", [3, 4, 9])
def test_unphased_rounds_at_or_above_the_cap_are_drift(repo, n):
    repo.commit(f"round {n}: another pass")
    severity, message = _mod.audit_bookkeeping_drift(_state(active=None))
    assert severity == "drift"
    assert "HARD CAP" in message


def test_the_cap_is_audit_rules_three(repo):
    assert _mod.UNPHASED_FAIL_ROUND == 3


def test_highest_round_wins_across_commits(repo):
    repo.commit("round 1: first pass")
    repo.commit("round 4: fourth pass")
    repo.commit("round 2: second pass")
    severity, message = _mod.audit_bookkeeping_drift(_state(active=None))
    assert severity == "drift"
    assert "reach round 4" in message


def test_dangling_pointer_is_treated_as_unphased(repo):
    repo.commit("round 1: first pass")
    severity, message = _mod.audit_bookkeeping_drift(_state(active="Z"))
    assert severity == "warn"
    assert "neither phases nor already_shipped" in message


# --- a pointer that resolves ----------------------------------------------

def test_phase_declaring_enough_rounds_is_silent(repo):
    repo.commit("round 2: second pass")
    phases = [{"id": "H", "name": "Phase H", "audit_rounds": 2, "audit_clean": False}]
    assert _mod.audit_bookkeeping_drift(_state(active="H", phases=phases)) is None


def test_phase_declaring_too_few_rounds_is_drift(repo):
    repo.commit("round 5: fifth pass")
    phases = [{"id": "H", "name": "Phase H", "audit_rounds": 2, "audit_clean": False}]
    severity, message = _mod.audit_bookkeeping_drift(_state(active="H", phases=phases))
    assert severity == "drift"
    assert "Phase H" in message and "declares 2" in message


def test_pointer_resolves_against_already_shipped_by_name(repo):
    """Scoped pieces are not phases; an already_shipped entry is a valid
    target, and the audit_rule says the count means the same thing there."""
    repo.commit("round 2: second pass")
    shipped = [{"name": "O4 -- the piece", "audit_rounds": 2, "audit_clean": False}]
    assert _mod.audit_bookkeeping_drift(_state(active="O4 -- the piece", shipped=shipped)) is None


def test_already_shipped_target_declaring_too_few_is_drift(repo):
    repo.commit("round 2: second pass")
    shipped = [{"name": "O4 -- the piece", "audit_rounds": 1, "audit_clean": False}]
    severity, message = _mod.audit_bookkeeping_drift(
        _state(active="O4 -- the piece", shipped=shipped)
    )
    assert severity == "drift"
    assert "shipped item 'O4 -- the piece'" in message


def test_already_shipped_target_without_a_count_is_drift(repo):
    """`audit_rounds` is optional on those entries; missing means zero, not
    'unknown, stay quiet'."""
    repo.commit("round 1: first pass")
    shipped = [{"name": "piece", "audit_clean": True}]
    severity, _ = _mod.audit_bookkeeping_drift(_state(active="piece", shipped=shipped))
    assert severity == "drift"


def test_one_directional_file_ahead_of_git_is_not_drift(repo):
    """Rounds legitimately run without producing a commit."""
    repo.commit("round 1: first pass")
    phases = [{"id": "H", "name": "Phase H", "audit_rounds": 6, "audit_clean": False}]
    assert _mod.audit_bookkeeping_drift(_state(active="H", phases=phases)) is None


# --- main()'s routing: warn is yellow and exit 0, drift is red and exit 1 ---

def _run_main(repo, monkeypatch, capsys, state: dict) -> tuple[int, str]:
    import json
    import sys

    (repo.path / "marker.txt").write_text("SENTINEL", encoding="utf-8")
    state_file = repo.path / "state.json"
    state_file.write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(_mod, "STATE", state_file)
    monkeypatch.setattr(sys, "argv", ["state.py", "--quiet"])
    code = _mod.main()
    return code, capsys.readouterr().out


def _renderable(active=None) -> dict:
    """The smallest state --quiet will walk: one phase whose probe passes."""
    return {
        "main": PROSE_MAIN,
        "active_phase": active,
        "phases": [{
            "id": "A", "name": "Phase A", "status": "shipped",
            "audit_rounds": 7, "audit_clean": True,
            "verify": {"path": "marker.txt", "pattern": "SENTINEL", "kind": "present"},
        }],
        "already_shipped": [],
    }


def test_main_routes_a_warn_to_exit_zero(repo, monkeypatch, capsys):
    repo.commit("round 1: first pass")
    code, out = _run_main(repo, monkeypatch, capsys, _renderable())
    assert code == 0
    assert "UNAUDITED WORK" in out
    assert "nothing in PROJECT_STATE.json is counting them" in out
    assert "STATE DRIFT" not in out


def test_main_routes_a_drift_to_exit_one(repo, monkeypatch, capsys):
    repo.commit("round 3: third pass")
    code, out = _run_main(repo, monkeypatch, capsys, _renderable())
    assert code == 1
    assert "STATE DRIFT" in out
    assert "HARD CAP" in out


def test_main_prints_the_message_not_the_tuple(repo, monkeypatch, capsys):
    repo.commit("round 1: first pass")
    _, out = _run_main(repo, monkeypatch, capsys, _renderable())
    assert "('warn'" not in out and '("warn"' not in out
