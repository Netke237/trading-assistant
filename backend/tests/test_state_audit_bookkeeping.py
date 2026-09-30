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
    """Rounds legitimately run without producing a commit.

    `audit_clean` is TRUE here on purpose. The property under test is that the
    UNDERCOUNT check is one-directional, and a piece at 6 rounds with none of
    them clean now trips the hard cap on its own -- a different complaint, on
    different evidence. The test below pins that one."""
    repo.commit("round 1: first pass")
    phases = [{"id": "H", "name": "Phase H", "audit_rounds": 6, "audit_clean": True}]
    assert _mod.audit_bookkeeping_drift(_state(active="H", phases=phases)) is None


def test_the_hard_cap_fires_on_the_resolved_path_too(repo):
    """THE CAP USED TO BE OPT-OUT, verified by reproduction before it was fixed:
    `UNPHASED_FAIL_ROUND` was read in exactly one place, inside the `target is
    None` branch, so once a pointer resolved and the declared count kept up with
    the git evidence this returned None at ANY round count. A piece could run 3,
    8 or 30 rounds without going clean under a rendered "No drift" -- and the
    unphased message's own printed remedy, point the pointer at the entry and
    record the count there, was precisely the move onto the branch that could
    not escalate. Following the instruction turned the check off."""
    repo.commit("round 4: the fourth unclean round")
    phases = [{"id": "H", "name": "Phase H", "audit_rounds": 4, "audit_clean": False}]
    severity, message = _mod.audit_bookkeeping_drift(_state(active="H", phases=phases))
    assert severity == "drift"
    assert "HARD CAP" in message


def test_the_hard_cap_counts_this_branch_not_the_self_report(repo):
    """IT GATED ON `audit_rounds` FIRST, AND THAT BANNER COULD NOT BE CLEARED.
    A piece past three unclean rounds whose work cannot yet merge had no truthful
    way back: going clean is only honest when it IS clean, lowering the count
    trips the undercount check, and re-pointing moves the complaint instead of
    answering it. It also re-fired forever on work whose cap had already been
    escalated and merged, and on a stale pointer left at a finished piece --
    round 4 finding 6's rule broken by the block that cites it.

    Counting what the branch still carries keeps the signal on the unfinished
    rounds. Here the six rounds are merged history and only round 1 is live."""
    repo.commit("round 1: first pass")
    phases = [{"id": "H", "name": "Phase H", "audit_rounds": 6, "audit_clean": False}]
    assert _mod.audit_bookkeeping_drift(_state(active="H", phases=phases)) is None


def test_the_hard_cap_holds_its_fire_below_the_threshold(repo):
    """Two rounds and no clean one is the commonest shape in this repo (C, E,
    F1 and F2 all went clean in exactly two). The cap is a stop signal, not a
    running commentary."""
    repo.commit("round 1: first pass")
    phases = [{"id": "H", "name": "Phase H", "audit_rounds": 2, "audit_clean": False}]
    assert _mod.audit_bookkeeping_drift(_state(active="H", phases=phases)) is None


def test_the_hard_cap_clears_by_merging(repo):
    """Round 4 finding 6's rule, applied to the new banner: a red banner nobody
    can clear is worse than no banner. This one clears by going clean (the test
    above) or by merging, after which the range is empty, there is no evidence
    to read, and the cap never runs."""
    repo.commit("round 6: the last unclean round")
    phases = [{"id": "H", "name": "Phase H", "audit_rounds": 6, "audit_clean": False}]
    # The rounds are live on the branch, so the cap is up ...
    assert _mod.audit_bookkeeping_drift(_state(active="H", phases=phases)) is not None
    repo.set_origin_main("feature")
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


def test_an_entry_older_than_the_branch_gets_no_narrowing(repo):
    """THE ACCEPTED COST OF THE INTRODUCING-COMMIT RULE, pinned so it is a
    decision rather than a surprise.

    THIS TEST USED TO SPECIFY A REGRESSION. It asserted `is None` here and
    required the boundary to be "the newest commit where this target's own count
    was LOWER than the value now declared" -- and that rule, shipped at d5fcbce,
    made every undercount above zero SILENT, because raising the declared count
    makes more historical commits qualify as lower and the newest qualifying one
    wins, so recording a number moved the boundary FORWARD. In this repo's style,
    where every branch commit touches the state file, the newest state-file
    commit almost always declares less than the live one. Five rounds run and a
    file declaring two rendered "No drift" at exit 0.

    So the count no longer supplies a boundary at all, and the price is here: an
    entry that predates the branch point is never ABSENT inside the range, gets
    no narrowing, and answers for the whole branch -- piece one's round 4
    included, on a file telling the truth. A false ALARM, visible, and it clears
    by merging or by recording the count. That is the deliberate trade against
    never going silent on an undercount."""
    both = _piece_state("piece two", [
        {"name": "piece one", "audit_rounds": 0},
        {"name": "piece two", "audit_rounds": 0},
    ])
    repo.write_state(both, "Open both pieces")
    repo.commit("round 4: fixes on piece one")
    repo.write_state(_piece_state("piece two", [
        {"name": "piece one", "audit_rounds": 4, "audit_clean": True},
        {"name": "piece two", "audit_rounds": 0},
    ]), "Record piece one at 4, clean")

    now = _piece_state("piece two", [
        {"name": "piece one", "audit_rounds": 4, "audit_clean": True},
        {"name": "piece two", "audit_rounds": 2, "audit_clean": True},
    ])
    repo.write_state(now, "Record piece two at 2, clean")

    assert _mod._target_scoped_base("origin/main", now) == "origin/main"
    severity, _ = _mod.audit_bookkeeping_drift(now)
    assert severity == "drift", "the accepted false alarm has quietly become silence"

    # And it clears the way the docstring says it does.
    repo.set_origin_main("feature")
    assert _mod.audit_bookkeeping_drift(now) is None


def test_recording_a_count_cannot_move_the_boundary(repo):
    """THE PROPERTY THE REGRESSION BROKE, pinned directly rather than implied.

    This repo's style is that every branch commit touches PROJECT_STATE.json, so
    the newest state-file commit is almost always one that trails the live count.
    Whatever the file claims, the span under judgement must not shrink."""
    piece = _piece_state("the piece", [{"name": "the piece", "audit_rounds": 0}])
    repo.write_state(piece, "Open the piece")
    for n in (1, 2, 3, 4, 5):
        repo.write_state(
            _piece_state("the piece", [{"name": "the piece", "audit_rounds": 0}]),
            f"Close round {n}'s findings",
        )
    # Nothing in range predates the entry, so there is no boundary to find and
    # the range stays whole -- which is the point: no count can shrink it.
    for declared in (0, 1, 2, 3, 4):
        state = _piece_state("the piece", [{"name": "the piece", "audit_rounds": declared,
                                            "audit_clean": True}])
        assert _mod._target_scoped_base("origin/main", state) == "origin/main", declared
        severity, message = _mod.audit_bookkeeping_drift(state)
        assert severity == "drift", f"declared {declared} went silent"
        assert "reach round 5" in message

    # Committing the undercount does not buy the silence either.
    lying = _piece_state("the piece", [{"name": "the piece", "audit_rounds": 2,
                                        "audit_clean": True}])
    repo.write_state(lying, "Record the rounds run so far")
    severity, _ = _mod.audit_bookkeeping_drift(lying)
    assert severity == "drift"


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


def test_the_scoped_base_is_the_commit_that_introduced_the_entry(repo):
    """Not the commit before it -- that is one commit too far back, and
    `git log sha..HEAD` excludes only `sha` itself. Opening a piece while
    recording the PREVIOUS piece's last round is one commit in this repo's
    style, so including the introducing commit would hand a brand-new piece the
    round number of the piece before it (round 2 finding 1, in the new key)."""
    one = _piece_state("piece one", [{"name": "piece one", "audit_rounds": 0}])
    repo.write_state(one, "Build piece one")
    repo.commit("round 1: fixes on piece one")

    two = _piece_state("piece two", [{"name": "piece two", "audit_rounds": 0}])
    repo.write_state(two, "Record piece one; open piece two")
    opened = repo.git("rev-parse", "HEAD")

    assert _mod._target_scoped_base("origin/main", two) == opened


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


def test_an_entry_that_exists_only_on_disk_does_not_narrow_anything(repo):
    """THE INVERSION OF A TEST THAT USED TO PIN AN ESCAPE HATCH. It asserted
    that a pointer moved only in the working tree scoped to `HEAD`, making
    `HEAD..HEAD` empty and the whole check silent -- and that was the mechanism
    behind the re-pointing escape: no commit was needed to switch the undercount
    check off, only an edit.

    Scoping now keys on the TARGET'S OWN history, and an entry the newest
    committed state file has never carried has no history to key on. So it
    refuses to narrow, and three rounds on the branch answer to a piece
    declaring none of them. Inventing an entry on disk, pointing at it and
    declaring 0 is not a way out."""
    one = _piece_state("piece one", [{"name": "piece one", "audit_rounds": 0}])
    repo.write_state(one, "Build piece one")
    repo.commit("round 3: fixes on piece one")

    two = _piece_state("piece two", [{"name": "piece two", "audit_rounds": 0}])
    assert _mod._target_scoped_base("origin/main", two) == "origin/main"
    severity, message = _mod.audit_bookkeeping_drift(two)
    assert severity == "drift"
    assert "reach round 3" in message


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

    assert _mod._target_scoped_base("origin/main", two) != "origin/main"
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
    """History that WOULD narrow, so the fallback is what is being measured.

    The first version of this asserted against a repo with no state-file
    history at all and a null pointer, which meant it passed whether the
    fallback was there or not -- twice over. The pointer is set, and the branch
    carries a real pointer move, so gutting the `except ValueError` branch
    fails here.
    """
    one = _piece_state("piece one", [{"name": "piece one", "audit_rounds": 0}])
    repo.write_state(one, "Open piece one")
    repo.commit("round 3: fixes on piece one")
    two = _piece_state("piece two", [{"name": "piece two", "audit_rounds": 0}])
    repo.write_state(two, "Record piece one; open piece two")

    assert _mod._target_scoped_base("origin/main", two) != "origin/main", (
        "this history must narrow while STATE is locatable, or the assertion "
        "below cannot tell the fallback from a no-op"
    )

    monkeypatch.setattr(_mod, "STATE", Path("/nowhere/PROJECT_STATE.json"))
    assert _mod._target_scoped_base("origin/main", two) == "origin/main"


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


# --- round 3: a cleared pointer is not a scope ------------------------------
#
# Kenneth's option (A), decision STATE-PROBE-NULL-POINTER-2026-09-16. Round 2's
# fix narrowed the range for every pointer value, `null` among them, so the
# commit that CLEARED the pointer became the excluded boundary and the window
# collapsed to empty. No test here exercised _target_scoped_base with a null
# pointer, which is exactly how that got through round 2.

def test_clearing_the_pointer_does_not_hide_an_undercount(repo):
    """THE REGRESSION, end to end. Four rounds run; one commit then records the
    piece UNDERCOUNTED and clears the pointer. Before the fix this rendered "No
    drift" at exit 0 -- clearing the pointer was an escape hatch from the one
    check that exists to catch an undercount."""
    piece = _piece_state("the piece",
                         [{"name": "the piece", "audit_rounds": 0, "audit_clean": False}])
    repo.write_state(piece, "Open the piece")
    for n in (1, 2, 3, 4):
        repo.commit(f"round {n}: fixes on the piece")

    cleared = _piece_state(None, [
        {"name": "the piece", "audit_rounds": 1, "audit_clean": True},
    ])
    repo.write_state(cleared, "Record the piece and clear the active phase")

    result = _mod.audit_bookkeeping_drift(cleared)
    assert result is not None, "the undercount went silent again"
    severity, message = result
    assert severity == "drift"
    assert "reach round 4" in message
    assert "HARD CAP" in message


def test_a_cleared_pointer_does_not_narrow_the_range_at_all(repo):
    """The mechanism, pinned directly: with no pointer there is no scope, so
    the base ref comes back untouched rather than as the clearing commit."""
    piece = _piece_state("the piece", [{"name": "the piece", "audit_rounds": 0}])
    repo.write_state(piece, "Open the piece")
    repo.commit("round 4: fixes on the piece")
    cleared = _piece_state(None, [{"name": "the piece", "audit_rounds": 4}])
    repo.write_state(cleared, "Record the piece; clear the active phase")

    assert _mod._target_scoped_base("origin/main", cleared) == "origin/main"


def test_an_honest_cleared_pointer_draws_the_banner_too(repo):
    """(A)'s ACCEPTED COST, pinned so a later round reads it as the decision it
    is rather than as a fresh bug. The unphased path cannot read
    `already_shipped` counts -- teaching it to was option C, rejected -- so a
    branch that clears the pointer before merging is banner-ed even when its
    count is perfectly honest."""
    piece = _piece_state("the piece",
                         [{"name": "the piece", "audit_rounds": 0, "audit_clean": False}])
    repo.write_state(piece, "Open the piece")
    for n in (1, 2, 3, 4):
        repo.commit(f"round {n}: fixes on the piece")

    honest = _piece_state(None, [
        {"name": "the piece", "audit_rounds": 4, "audit_clean": True},
    ])
    repo.write_state(honest, "Record the piece: 4 rounds, clean; clear the pointer")

    severity, message = _mod.audit_bookkeeping_drift(honest)
    assert severity == "drift"
    assert "active_phase is null" in message


def _four_rounds_then_a_cleared_pointer(repo, declared: int, clean: bool = True):
    """Rounds 1-4 really ran. The file records `declared` and clears the
    pointer. At declared=4 that is an honest record; at declared=1 it is the
    undercount the whole probe exists to catch."""
    piece = _piece_state("the piece",
                         [{"name": "the piece", "audit_rounds": 0, "audit_clean": False}])
    repo.write_state(piece, "Open the piece")
    for n in (1, 2, 3, 4):
        repo.commit(f"round {n}: fixes on the piece")
    repo.write_state(
        _piece_state(None, [{"name": "the piece", "audit_rounds": declared,
                             "audit_clean": clean}]),
        f"Record the piece at {declared}; clear the active phase",
    )


def test_the_cleared_pointers_banner_clears_by_re_pointing(repo):
    """The first of its two honest escapes, and the one that needs no push.

    ROUND 1 FINDING 7 rewrote this. It used to assert `is None` after
    re-pointing with an HONEST count and nothing else, which cannot tell "the
    count now covers the evidence" from "the range went empty because the
    pointer moved" -- it passed against a stubbed `_target_scoped_base`, and
    it passed with the declared count set to 1 instead of 4. It pinned nothing
    about honesty. The honest escape is now asserted against a control that
    makes the range demonstrably non-empty first."""
    _four_rounds_then_a_cleared_pointer(repo, declared=4)

    # Control: the cleared pointer DOES fire, so the `is None` below is the
    # re-pointing doing the work rather than an empty range.
    cleared = _piece_state(None, [{"name": "the piece", "audit_rounds": 4,
                                   "audit_clean": True}])
    assert _mod.audit_bookkeeping_drift(cleared) is not None

    re_pointed = _piece_state("the piece", [{"name": "the piece", "audit_rounds": 4,
                                             "audit_clean": True}])
    assert _mod.audit_bookkeeping_drift(re_pointed) is None


def test_re_pointing_does_not_silence_a_dishonest_count(repo):
    """THE INVERSION THIS TEST WAS WRITTEN TO RECEIVE. It shipped asserting
    `is None` -- the behaviour of the day -- under a docstring saying that was
    a GATE-LEVEL hole, not a passing behaviour, and that both assertions must
    flip when the escape closed. They have.

    FINDING 1 OF ROUND 1 ON OPTION (A): re-pointing at the piece with the false
    count left intact silenced the undercount exactly as clearing the pointer
    used to, and needed no commit at all -- a working-tree edit was enough,
    because the walk hit `was != active` on the newest committed state file and
    fell through to `HEAD`. Scoping keys on the target's own count history now,
    so the pointer's value cannot move the boundary: four rounds ran, the file
    says one, and it says so whichever way the pointer is pointing."""
    _four_rounds_then_a_cleared_pointer(repo, declared=1, clean=False)
    lying = _piece_state("the piece", [{"name": "the piece", "audit_rounds": 1}])

    # Working tree only -- zero commits carry this pointer.
    assert _mod._target_scoped_base("origin/main", lying) != "HEAD"
    severity, message = _mod.audit_bookkeeping_drift(lying)
    assert severity == "drift"
    assert "reach round 4" in message and "declares 1" in message

    # And committing the re-point does not buy the silence either.
    repo.write_state(lying, "Re-point at the piece, count still wrong")
    severity, message = _mod.audit_bookkeeping_drift(lying)
    assert severity == "drift"
    assert "reach round 4" in message


def test_the_cleared_pointers_banner_clears_by_merging(repo):
    """The second escape. `base_ref..HEAD` is empty once the work is merged, so
    the wider range this fix restores cannot hold up a banner nobody can clear
    -- the property `_round_numbers_in_branch_subjects` degrades to None for."""
    piece = _piece_state("the piece", [{"name": "the piece", "audit_rounds": 0}])
    repo.write_state(piece, "Open the piece")
    for n in (1, 2, 3, 4):
        repo.commit(f"round {n}: fixes on the piece")
    cleared = _piece_state(None, [{"name": "the piece", "audit_rounds": 1}])
    repo.write_state(cleared, "Record the piece; clear the active phase")

    assert _mod.audit_bookkeeping_drift(cleared) is not None
    repo.set_origin_main("feature")
    assert _mod.audit_bookkeeping_drift(cleared) is None


def test_a_dangling_pointer_does_not_narrow_at_all(repo):
    """THE OTHER INVERSION, and the same instruction honoured.

    FINDING 2 OF ROUND 1 ON OPTION (A): `not active` handled FALSY pointers and
    did nothing for one that was truthy and resolved to NOTHING. Such a value
    took the narrowing path AND the unphased path at once, so the escalation ran
    against a window the same nonsense value had just emptied -- the round-3
    defect, reached through a typo, and reachable without one: `already_shipped`
    is matched on `name`, those names are long prose strings, and renaming one
    while the pointer still holds the old string dangles it. So does opening a
    piece in one commit and adding its entry in the next.

    `_target_identity` now answers None for anything that resolves to nothing,
    null and typo alike, and nothing that resolves to nothing narrows."""
    one = _piece_state("piece one", [{"name": "piece one", "audit_rounds": 0}])
    repo.write_state(one, "Open piece one")
    repo.commit("round 4: fixes on piece one")

    typo = _piece_state("piece tow", [{"name": "piece two", "audit_rounds": 0}])
    repo.write_state(typo, "Record piece one; open piece two (misspelt pointer)")

    assert _mod._target_scoped_base("origin/main", typo) == "origin/main"
    severity, message = _mod.audit_bookkeeping_drift(typo)
    assert severity == "drift"
    assert "neither phases nor already_shipped" in message
    assert "reach round 4" in message


def test_a_non_string_pointer_is_treated_as_no_pointer(repo):
    """The same hole reached without a typo, and the same inversion.

    A state file is hand-edited, so a pointer that is a number, a bool, a list
    or an object is a plausible slip. Every one of them resolves to no target,
    so none of them narrows, and none of them crashes on the way."""
    one = _piece_state("piece one", [{"name": "piece one", "audit_rounds": 0}])
    repo.write_state(one, "Open piece one")
    repo.commit("round 4: fixes on piece one")
    repo.write_state(_piece_state("piece one", [{"name": "piece one", "audit_rounds": 0}]),
                     "Re-record piece one")

    for value in (123, True, ["piece one"], {"id": "piece one"}):
        state = _piece_state(value, [{"name": "piece one", "audit_rounds": 0}])
        assert _mod._target_scoped_base("origin/main", state) == "origin/main", repr(value)
        severity, _ = _mod.audit_bookkeeping_drift(state)
        assert severity == "drift", repr(value)


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


def test_the_target_scoping_entrys_probe_tracks_BOTH_halves(repo):
    """The structural change has two load-bearing halves -- the
    introducing-commit boundary and the hard cap on the resolved path -- and
    reverting either restores a false all-clear, so a probe pinning only one
    would certify the piece shipped with the other gone.

    THE FIRST VERSION OF THIS TEST WAS ROUND 1 FINDING 5, and the mistake is
    worth keeping written down because it is subtle: it anchored on
    `rounds = _declared_rounds_at(blob, identity)` and on the cap's CONDITION,
    then "proved" the probe tracked behaviour by mutating exactly those two
    strings. Every real behavioural revert left both anchors standing, so the
    probe certified the piece shipped with the behaviour gone -- round 1 finding
    4's modelling error, committed inside the test written to prevent it.

    A presence probe can only ever detect text that a revert REMOVES; that is
    limitation #1 in this script's own header, not something to design around.
    So the anchors are the two RETURNS -- the values the behaviour produces --
    and the mutations below are the reverts an actual reverter would write."""
    real_root = Path(__file__).parent.parent.parent
    state = json.loads((real_root / STATE_REL).read_text(encoding="utf-8"))
    entry = next(i for i in state["already_shipped"]
                 if i["name"].startswith("STATE-PROBE-TARGET-SCOPING"))
    pattern = entry["verify"]["pattern"]
    src = (real_root / entry["verify"]["path"]).read_text(encoding="utf-8")

    assert re.search(pattern, src, re.M), "the entry's probe does not match the real file"

    # Revert 1: the ABSENT branch stops backing up to the introducing commit.
    no_boundary = src.replace(
        "return boundary if boundary is not None else base_ref", "return sha"
    )
    assert no_boundary != src
    assert not re.search(pattern, no_boundary, re.M), (
        "the probe still certifies this shipped with the introducing-commit rule gone"
    )

    # Revert 2: the resolved-path cap stops firing.
    no_cap = src.replace(
        'if git_max >= UNPHASED_FAIL_ROUND and not target.get("audit_clean"):', "if False:"
    )
    assert no_cap != src
    assert not re.search(pattern, no_cap, re.M), (
        "the probe still certifies this shipped with the resolved-path cap gone"
    )

    # Revert 3: the condition is left standing and only the VERDICT changes.
    # This is the one a text probe is worst at, and it is included to show
    # exactly how far the anchor reaches: it catches this because the verdict
    # is what the pattern pins, and it would NOT catch a change that kept
    # `return "drift"` while altering the message or the threshold constant.
    downgraded = src.replace(
        '        return "drift", (\n            f"Audit bookkeeping: {label} -- the '
        'active target -- declares {declared} "',
        '        return "warn", (\n            f"Audit bookkeeping: {label} -- the '
        'active target -- declares {declared} "',
    )
    assert downgraded != src, "the revert-3 fixture no longer matches the source"
    assert not re.search(pattern, downgraded, re.M), (
        "the probe still certifies this shipped with the cap downgraded to a warning"
    )


def test_the_null_pointer_entrys_verify_probe_tracks_the_early_return(repo):
    """Same modelling error as ROUND 1 FINDING 4, refused up front for that
    entry: its probe must die when the one line of behaviour it certifies is
    reverted, not merely when some neighbouring symbol is renamed.

    The line MOVED when the structural fix landed -- option A's guarantee is
    now `if identity is None` in `_target_scoped_base` rather than `if not
    active` in a function that no longer exists -- so the probe moved with it.
    Repointing a probe at the same guarantee in its new home is not the same as
    loosening it: gutting the return still has to break this."""
    real_root = Path(__file__).parent.parent.parent
    state = json.loads((real_root / STATE_REL).read_text(encoding="utf-8"))
    entry = next(i for i in state["already_shipped"]
                 if i["name"].startswith("STATE-PROBE-NULL-POINTER"))
    pattern = entry["verify"]["pattern"]
    src = (real_root / entry["verify"]["path"]).read_text(encoding="utf-8")

    assert re.search(pattern, src, re.M), "the entry's probe does not match the real file"
    reverted = re.sub(pattern, "pass", src, count=1)
    assert not re.search(pattern, reverted, re.M), (
        "the probe still certifies this shipped with the early return removed"
    )


# --- merging main into the branch must not import main's round numbers ------

def _open_piece_then_merge_main_carrying(repo, main_subject: str) -> dict:
    """A piece is opened on the branch, main gains another piece's round in
    the meantime, and the branch merges origin/main to stay current -- the
    order MANUAL-IBKR-CONFIRM-AS-ERROR actually took with A5c's round 4."""
    # A state commit that predates the entry, so the scoped base narrows to
    # the commit that introduces it (the real branch carried the decision
    # commit first).
    repo.write_state(_piece_state(None, []), "Record the decision")
    piece = _piece_state("the piece", [{"name": "the piece", "audit_rounds": 0}])
    repo.write_state(piece, "Open the piece")
    repo.commit("round 1: fixes on the piece")

    repo.git("checkout", "-q", "main")
    (repo.path / "main.txt").write_text(main_subject, encoding="utf-8")
    repo.git("add", "-A")
    repo.git("commit", "-q", "-m", main_subject)   # own file: the merge must not conflict
    repo.set_origin_main("main")
    repo.git("checkout", "-q", "feature")
    repo.git("merge", "-q", "--no-ff", "--no-edit", "origin/main")

    piece["already_shipped"][0].update(audit_rounds=1, audit_clean=True)
    repo.write_state(piece, "Record the piece: clean after 1 round")
    return piece


def test_rounds_merged_in_from_main_are_not_this_pieces(repo):
    """THE DEFERRED FALSE POSITIVE. The scoped base is the commit that
    introduced the entry, and `sha..HEAD` alone includes every commit the
    branch merged in from main after that sha -- so another piece's already
    merged "round 4" subject counted against an honest file declaring 1."""
    piece = _open_piece_then_merge_main_carrying(repo, "round 4: fixes on another piece")

    assert _mod._target_scoped_base("origin/main", piece) != "origin/main"
    assert _mod.audit_bookkeeping_drift(piece) is None


def test_merging_main_does_not_hide_this_pieces_own_undercount(repo):
    """The exclusion drops only what main already carries: this branch's own
    rounds still count after the merge, so an undercount stays drift."""
    piece = _open_piece_then_merge_main_carrying(repo, "unrelated work on main")
    repo.commit("round 2: fixes on the piece")

    severity, message = _mod.audit_bookkeeping_drift(piece)
    assert severity == "drift"
    assert "reach round 2" in message


def test_a_rounds_arriving_by_a_sibling_merge_still_count(repo):
    """Why the exclusion is `^merged_ref` and not `--first-parent`. This
    piece's round can reach the branch through a merge of ANOTHER branch
    (MANUAL-IBKR-CONFIRM-AS-ERROR's own decision commit came in that way from
    claude/jolly-thompson-0q7paq). First-parent would drop it and hide the
    undercount; excluding only what main carries keeps it."""
    piece = _open_piece_then_merge_main_carrying(repo, "unrelated work on main")
    repo.git("checkout", "-q", "-b", "sibling")
    (repo.path / "sibling.txt").write_text("s", encoding="utf-8")
    repo.git("add", "-A")
    repo.git("commit", "-q", "-m", "round 3: fixes on the piece")
    repo.git("checkout", "-q", "feature")
    repo.git("merge", "-q", "--no-ff", "--no-edit", "sibling")

    severity, message = _mod.audit_bookkeeping_drift(piece)
    assert severity == "drift"
    assert "reach round 3" in message


def test_the_merged_main_entrys_verify_probe_tracks_the_exclusion(repo):
    """Same modelling error as ROUND 1 FINDING 4, refused up front: the probe
    must die when the exclusion is reverted, at the helper or at the call."""
    real_root = Path(__file__).parent.parent.parent
    state = json.loads((real_root / STATE_REL).read_text(encoding="utf-8"))
    entry = next(i for i in state["already_shipped"]
                 if i["name"].startswith("STATE-PROBE-MERGED-MAIN-ROUNDS"))
    pattern = entry["verify"]["pattern"]
    src = (real_root / entry["verify"]["path"]).read_text(encoding="utf-8")

    assert re.search(pattern, src, re.M), "the entry's probe does not match the real file"
    for old, new in (
        ('revs.append(f"^{merged_ref}")', "pass"),
        ("_target_scoped_base(base_ref, state), base_ref,", "_target_scoped_base(base_ref, state),"),
    ):
        reverted = src.replace(old, new)
        assert reverted != src, f"the revert fixture no longer matches: {old}"
        assert not re.search(pattern, reverted, re.M), (
            f"the probe still certifies this shipped with {old!r} reverted"
        )


def test_this_pieces_round_that_reached_main_first_is_dropped(repo):
    """THE SILENT COST, pinned so it is a decision rather than a surprise
    (round 1 finding 1). A sibling cut from main BEFORE the piece opened
    carries a round of this piece, reaches main, and comes back in the
    branch's main merge. In the graph that is the same shape as another
    piece's merged round, so it is dropped with them -- the unnarrowed span's
    rule that merged rounds are out of range, applied to the narrowed one."""
    repo.write_state(_piece_state(None, []), "Record the decision")
    piece = _piece_state("the piece", [{"name": "the piece", "audit_rounds": 0}])
    repo.write_state(piece, "Open the piece")
    repo.commit("round 1: fixes on the piece")

    repo.git("checkout", "-q", "-b", "sibling", "main")
    (repo.path / "sibling.txt").write_text("s", encoding="utf-8")
    repo.git("add", "-A")
    repo.git("commit", "-q", "-m", "round 3: fixes on the piece")
    repo.git("checkout", "-q", "main")
    repo.git("merge", "-q", "--no-ff", "--no-edit", "sibling")
    repo.set_origin_main("main")
    repo.git("checkout", "-q", "feature")
    repo.git("merge", "-q", "--no-ff", "--no-edit", "origin/main")

    piece["already_shipped"][0].update(audit_rounds=1, audit_clean=True)
    repo.write_state(piece, "Record the piece: clean after 1 round")
    assert _mod.audit_bookkeeping_drift(piece) is None


def test_the_excluded_ref_is_the_resolved_base_not_a_fixed_name(repo):
    """The common real shape: local main stale, origin/main advanced and merged
    into the branch. Tightest-wins picks origin/main, and THAT is what must be
    excluded -- excluding the stale local main would let main's round back in."""
    repo.write_state(_piece_state(None, []), "Record the decision")
    piece = _piece_state("the piece", [{"name": "the piece", "audit_rounds": 0}])
    repo.write_state(piece, "Open the piece")
    stale_main = repo.git("rev-parse", "main")

    repo.git("checkout", "-q", "--detach", "main")
    (repo.path / "main.txt").write_text("m", encoding="utf-8")
    repo.git("add", "-A")
    repo.git("commit", "-q", "-m", "round 4: fixes on another piece")
    repo.set_origin_main("HEAD")
    repo.git("checkout", "-q", "feature")
    repo.git("merge", "-q", "--no-ff", "--no-edit", "origin/main")
    assert repo.git("rev-parse", "main") == stale_main

    piece["already_shipped"][0].update(audit_rounds=0)
    repo.write_state(piece, "Record the piece")
    assert _mod._resolve_base_ref()[0] == "origin/main"
    assert _mod.audit_bookkeeping_drift(piece) is None
    # And a stale local main as the exclusion would NOT have been enough.
    scoped = _mod._target_scoped_base("origin/main", piece)
    assert _mod._round_numbers_in_branch_subjects(scoped, "main")[0] == 4


def test_a_malformed_merged_ref_degrades_to_no_evidence(repo):
    """The ref-shape guard covers `merged_ref` as it does `base_ref`: nothing
    that is not a plain ref name reaches git's argv."""
    repo.commit("round 2: fixes")
    assert _mod._round_numbers_in_branch_subjects("origin/main", "main")[0] == 2
    # A revision git WOULD accept (it yields round 2 unguarded), refused by shape.
    assert _mod._round_numbers_in_branch_subjects("origin/main", "HEAD~1") is None
    # A leading '-' is an OPTION to git, not a revision, and is refused by
    # shape (P6). Before that, git's own rejection of `^--all` produced this
    # None; since P6 D1 a git failure is a distinct COULD-NOT-RUN result, so
    # the shape guard is what holds this line now.
    assert _mod._round_numbers_in_branch_subjects("origin/main", "--all") is None


# --- P6 (D1, D2) -----------------------------------------------------------

def test_a_failed_git_log_warns_instead_of_reading_as_no_drift(repo, monkeypatch):
    """P6 D1. The base ref resolves, then `git log` over it fails (the ref
    vanished in between). This used to return None -- "No drift"."""
    repo.commit("round 2: fixes")
    real_run = _mod.subprocess.run

    def failing_log(args, *a, **k):
        if args[:2] == ["git", "log"]:
            return subprocess.CompletedProcess(args, 128, "", "fatal: bad revision")
        return real_run(args, *a, **k)

    monkeypatch.setattr(_mod.subprocess, "run", failing_log)
    severity, message = _mod.audit_bookkeeping_drift(_state(active="A"))
    assert severity == "warn", "an unrunnable check must not exit non-zero"
    assert "COULD NOT RUN" in message


def test_a_git_log_that_raises_warns_too(repo, monkeypatch):
    repo.commit("round 2: fixes")
    real_run = _mod.subprocess.run

    def raising_log(args, *a, **k):
        if args[:2] == ["git", "log"]:
            raise subprocess.TimeoutExpired(args, 10)
        return real_run(args, *a, **k)

    monkeypatch.setattr(_mod.subprocess, "run", raising_log)
    assert _mod.audit_bookkeeping_drift(_state(active="A"))[0] == "warn"


@pytest.mark.parametrize("declared, expected", [
    ("3", None),          # a numeric string reads as its number: 2 <= 3
    (" 3 ", None),
    ("1", "drift"),       # ...and still catches an undercount
    (3.0, None),          # json.loads gives a float for `3.0`; whole, so read
    (1.0, "drift"),       # ...and an undercount through a float still drifts
])
def test_a_numeric_string_audit_rounds_is_read_as_its_number(repo, declared, expected):
    """P6 D2. `declared = target.get("audit_rounds") or 0` then `git_max >
    declared` raised TypeError on a hand-edited string -- inside the
    SessionStart hook."""
    repo.commit("round 2: fixes")
    phases = [{"id": "A", "name": "Phase A", "audit_rounds": declared, "audit_clean": True}]
    result = _mod.audit_bookkeeping_drift(_state(active="A", phases=phases))
    assert (result[0] if result else None) == expected


@pytest.mark.parametrize("declared", ["three", 2.5, [2], True])
def test_a_non_numeric_audit_rounds_warns_instead_of_raising(repo, declared):
    repo.commit("round 2: fixes")
    phases = [{"id": "A", "name": "Phase A", "audit_rounds": declared, "audit_clean": True}]
    severity, message = _mod.audit_bookkeeping_drift(_state(active="A", phases=phases))
    assert severity == "warn"
    assert "not a whole number" in message


@pytest.mark.parametrize("declared", ["three", 2.5, True, [2]])
def test_a_non_numeric_audit_rounds_still_trips_the_hard_cap(repo, declared):
    """P6 unit D, code round 6. The non-numeric warn returned BEFORE the hard
    cap, so round 5 on a target that is not clean exited 0. The cap never reads
    `declared`, so it must still fire."""
    repo.commit("round 5: fixes")
    phases = [{"id": "A", "name": "Phase A", "audit_rounds": declared, "audit_clean": False}]
    severity, message = _mod.audit_bookkeeping_drift(_state(active="A", phases=phases))
    assert severity == "drift"
    assert "HARD CAP" in message
