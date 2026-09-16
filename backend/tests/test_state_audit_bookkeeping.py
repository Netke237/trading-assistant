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
import json
import re
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


STATE_REL = "docs/superpowers/PROJECT_STATE.json"


class Repo:
    """A throwaway git repo with `main`, an `origin/main` ref, and a branch."""

    def __init__(self, path: Path):
        self.path = path
        self._writes = 0

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

    def write_state(self, state: dict, subject: str) -> None:
        """Commit a state file at its real repo-relative path, so the
        pointer-scoping walk has genuine history to read."""
        # A marker that changes every write. Without it, committing the same
        # pointer twice writes byte-identical JSON, git records no change to
        # THAT PATH, and `git log -- <path>` does not list the commit at all --
        # so a test meaning to build N state-file commits silently builds
        # fewer. That is how the scan-window test first passed against code
        # that had no scan-window handling.
        self._writes += 1
        f = self.path / STATE_REL
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(dict(state, _write=self._writes)), encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", subject)

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
    monkeypatch.setattr(_mod, "STATE", tmp_path / STATE_REL)
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

def test_base_ref_is_origin_main_when_both_are_level(repo):
    ref, _ = _mod._resolve_base_ref()
    assert ref == "origin/main"


def test_base_ref_falls_back_to_local_main(repo):
    repo.drop_origin_main()
    ref, _ = _mod._resolve_base_ref()
    assert ref == "main"


def test_base_ref_prefers_the_tighter_ref_not_the_remote_one(repo):
    """ROUND 1 FINDING 3. This project merges with a local --no-ff and pushes
    afterwards, and those pushes have 403'd. Between merge and push, local main
    carries the merged work and origin/main is the stale one -- so preferring
    origin/main by name kept a banner up that the merge was meant to clear."""
    repo.git("checkout", "-q", "main")
    repo.commit("round 2: fixes on the earlier piece")
    repo.commit("Merge the earlier piece")          # local merge, never pushed
    repo.git("checkout", "-q", "-b", "later-piece")
    repo.commit("build the later piece")

    ref, _ = _mod._resolve_base_ref()
    assert ref == "main", "stale origin/main was preferred over the merged local main"
    # and the earlier piece's round is therefore out of range entirely
    assert _mod.audit_bookkeeping_drift(_state(active=None)) is None


def test_no_base_ref_warns_rather_than_reporting_no_drift(repo):
    """ROUND 1 FINDING 1. A --single-branch or --depth 1 clone has neither ref.
    Returning None renders as "No drift" -- a clean bill for a check that never
    ran, which is the exact observable this whole change exists to remove."""
    repo.drop_origin_main()
    repo.git("branch", "-D", "main")
    repo.commit("round 4: fixes")

    ref, detail = _mod._resolve_base_ref()
    assert ref is None
    assert "single-branch" in detail

    severity, message = _mod.audit_bookkeeping_drift(_state())
    assert severity == "warn", "an unrunnable check must not exit non-zero"
    assert "COULD NOT RUN" in message
    assert "UNCHECKED bill, not a clean one" in message


def test_no_git_repository_at_all_warns_too(tmp_path, monkeypatch):
    """Deliberately does NOT use the `repo` fixture: a directory nested inside
    a git repo is still in one, since git walks upward to find .git."""
    monkeypatch.setattr(_mod, "ROOT", tmp_path)
    monkeypatch.setattr(_mod, "STATE", tmp_path / STATE_REL)
    ref, detail = _mod._resolve_base_ref()
    assert ref is None
    assert "no usable git repository" in detail
    assert _mod.audit_bookkeeping_drift(_state())[0] == "warn"


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


# --- finding 2: rounds are scoped to the pointer, not to the whole branch ---

def _piece_state(active, shipped) -> dict:
    return {"main": PROSE_MAIN, "active_phase": active,
            "phases": [], "already_shipped": shipped}


def test_an_earlier_pieces_rounds_are_not_the_current_targets(repo):
    """ROUND 1 FINDING 2, the sharpest one. One branch, two pieces, nothing
    merged, a state file that is completely honest -- and the probe reported
    drift, prescribing a remedy that could only be satisfied by writing a
    number known to be false into the record."""
    one = _piece_state("piece one",
                       [{"name": "piece one", "audit_rounds": 0, "audit_clean": False}])
    repo.write_state(one, "Build piece one")
    repo.commit("round 1: fixes on piece one")
    repo.commit("round 2: fixes on piece one")
    one["already_shipped"][0].update(audit_rounds=2, audit_clean=True)
    repo.write_state(one, "Record piece one: clean after 2 rounds")

    two = _piece_state("piece two", [
        {"name": "piece one", "audit_rounds": 2, "audit_clean": True},
        {"name": "piece two", "audit_rounds": 0, "audit_clean": False},
    ])
    repo.write_state(two, "Build piece two")
    repo.commit("round 1: fixes on piece two")
    two["already_shipped"][1]["audit_rounds"] = 1
    repo.write_state(two, "Record piece two: round 1 findings fixed")

    # Unscoped, the branch's highest round is piece ONE's 2 ...
    assert _mod._round_numbers_in_branch_subjects("origin/main")[0] == 2
    # ... and scoping to the pointer is the only thing standing between that
    # and a red banner on an honest file.
    assert _mod.audit_bookkeeping_drift(two) is None


def test_the_scoped_base_is_the_commit_that_set_the_pointer(repo):
    """Not the commit where the pointer last DIFFERED -- that is one commit too
    far back, and `git log sha..HEAD` excludes only `sha` itself."""
    one = _piece_state("piece one", [{"name": "piece one", "audit_rounds": 0}])
    repo.write_state(one, "Build piece one")
    repo.commit("round 1: fixes on piece one")

    two = _piece_state("piece two", [{"name": "piece two", "audit_rounds": 0}])
    repo.write_state(two, "Record piece one; open piece two")
    opened = repo.git("rev-parse", "HEAD")

    assert _mod._pointer_scoped_base("origin/main", two) == opened


def test_the_commit_that_moves_the_pointer_is_not_the_new_pieces_round(repo):
    """ROUND 2 FINDING 1. Recording the round that just finished and moving the
    pointer is ONE commit in this repo's actual style ("Record round 4: clean
    at the gate...", "Phase G is in: name the merge, clear the active phase").
    Leaving that commit inside the new pointer's range drew red drift on a
    piece that had had no rounds at all -- clearable only by merging, or by
    writing a count known to be false into the record."""
    one = _piece_state("piece one",
                       [{"name": "piece one", "audit_rounds": 0, "audit_clean": False}])
    repo.write_state(one, "Build piece one")
    repo.commit("round 1: fixes on piece one")
    repo.commit("round 2: fixes on piece one")

    two = _piece_state("piece two", [
        {"name": "piece one", "audit_rounds": 2, "audit_clean": True},
        {"name": "piece two", "audit_rounds": 0, "audit_clean": False},
    ])
    repo.write_state(two, "Record round 2 clean; open piece two")

    assert _mod.audit_bookkeeping_drift(two) is None, (
        "piece two has had no rounds of its own; the only ways to clear this "
        "banner would be merging or writing a false count"
    )


def test_a_pointer_moved_only_in_the_working_tree_claims_no_committed_rounds(repo):
    """No COMMITTED round can belong to a pointer that exists only on disk."""
    one = _piece_state("piece one", [{"name": "piece one", "audit_rounds": 0}])
    repo.write_state(one, "Build piece one")
    repo.commit("round 3: fixes on piece one")

    two = _piece_state("piece two", [{"name": "piece two", "audit_rounds": 0}])
    assert _mod._pointer_scoped_base("origin/main", two) == "HEAD"
    assert _mod.audit_bookkeeping_drift(two) is None


def test_exhausting_the_scan_window_does_not_widen_back_to_the_full_range(repo, monkeypatch):
    """Degrading past the cap must not land back on the pre-fix false positive."""
    monkeypatch.setattr(_mod, "_POINTER_SCAN_LIMIT", 2)
    one = _piece_state("piece one", [{"name": "piece one", "audit_rounds": 0}])
    repo.write_state(one, "Build piece one")
    repo.commit("round 4: fixes on piece one")

    two = _piece_state("piece two", [{"name": "piece two", "audit_rounds": 0}])
    repo.write_state(two, "Open piece two")
    repo.write_state(two, "Touch the state file again")
    repo.write_state(two, "And once more")

    # Four state-file commits, window of two: the boundary lies beyond it.
    in_range = _mod._git("log", "--format=%H", "origin/main..HEAD", "--", STATE_REL)
    assert len(in_range.split()) > _mod._POINTER_SCAN_LIMIT, "window was never exhausted"
    assert _mod._round_numbers_in_branch_subjects("origin/main")[0] == 4, (
        "the full range must still contain the earlier piece's round, or this "
        "test cannot tell a safe degradation from a lucky one"
    )

    assert _mod._pointer_scoped_base("origin/main", two) != "origin/main"
    assert _mod.audit_bookkeeping_drift(two) is None


def test_a_pointer_that_never_moved_still_answers_for_the_whole_branch(repo):
    """The narrowing must not blunt the original catch: a single-piece branch
    is exactly the Phase A case this probe was written for."""
    st = _piece_state("piece", [{"name": "piece", "audit_rounds": 0, "audit_clean": False}])
    repo.write_state(st, "Build the piece")
    repo.commit("round 1: fixes")
    repo.commit("round 2: fixes")
    severity, message = _mod.audit_bookkeeping_drift(st)
    assert severity == "drift"
    assert "reach round 2" in message and "declares 0" in message


def test_scoping_degrades_to_the_full_range_when_state_is_outside_root(repo, monkeypatch):
    monkeypatch.setattr(_mod, "STATE", Path("/nowhere/PROJECT_STATE.json"))
    repo.commit("round 3: fixes")
    assert _mod._pointer_scoped_base("origin/main", _state()) == "origin/main"


def test_scoping_survives_unparseable_state_history(repo):
    """A commit whose state file is not valid JSON is not a boundary anyone can
    trust; it must be skipped, not crash the SessionStart hook."""
    f = repo.path / STATE_REL
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("{ this is not json", encoding="utf-8")
    repo.git("add", "-A")
    repo.git("commit", "-q", "-m", "round 1: broken state file")
    severity, _ = _mod.audit_bookkeeping_drift(_state(active=None))
    assert severity == "warn"


# --- finding 4: the verify probe must pin the load-bearing half -------------

def test_the_shipped_entrys_verify_probe_tracks_the_base_ref_fix(repo):
    """ROUND 1 FINDING 4. The probe pinned UNPHASED_FAIL_ROUND -- a constant
    belonging to the SECOND dead end -- so the whole revival could be reverted
    while state.py still certified it shipped. Same modelling error
    STATE_TRACKING.md already names about v0_grid."""
    real_root = Path(__file__).parent.parent.parent
    state = json.loads(
        (real_root / STATE_REL).read_text(encoding="utf-8")
    )
    entry = next(i for i in state["already_shipped"]
                 if i["name"].startswith("STATE-PROBE-REVIVAL"))
    pattern = entry["verify"]["pattern"]
    src = (real_root / entry["verify"]["path"]).read_text(encoding="utf-8")

    assert re.search(pattern, src, re.M), "the entry's probe does not match the real file"
    gutted = src.replace("def _resolve_base_ref", "def _reverted")
    assert not re.search(pattern, gutted, re.M), (
        "the probe still certifies this shipped with the base-ref fix removed"
    )
