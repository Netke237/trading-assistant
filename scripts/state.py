#!/usr/bin/env python3
"""Render and VERIFY docs/superpowers/PROJECT_STATE.json.

The point of this script is drift. A status document that is only prose starts
lying the moment someone builds something and forgets to update it -- which is
exactly how a previous session came to believe pieces were unbuilt that were,
and built that were not.

So every phase in PROJECT_STATE.json carries a `verify` probe: a pattern whose
presence or absence in the real code proves the declared status. This script
runs all of them and exits non-zero when a claim and the codebase disagree.

One field pair is checked differently, because no code symbol could ever prove
it: `audit_rounds` / `audit_clean`. See `audit_bookkeeping_drift`, which reads
git history rather than source.

WHAT IT CANNOT CATCH, stated so nobody reads a green "No drift" as more than it
is:

1. BEHAVIOUR. Every `verify` probe is a regex PRESENCE test. It answers "does
   this symbol still exist?", never "does it still do what the document says".
   Round 7 found the worked example: the badge probe is
   `present:"formatStopLossHeadline"`, which passes no matter what that
   function returns -- and the schematic had meanwhile been amended to describe
   a badge string the code does not produce. Drift in BEHAVIOUR is what the
   adversarial rounds are for; this script only pins existence.

2. AN AUDIT ROUND THAT LEFT NO COMMIT. The bookkeeping check's only evidence is
   commit subjects on this branch. A round that found nothing, or whose fixes
   were folded into a commit whose subject does not name a round, is invisible
   to it. It catches the case that actually happened; it is not a proof that
   the count is right. It is also blind once the work MERGES, by design: the
   range it reads is empty from then on, which is what stops it holding up a
   banner nobody can clear.

3. `audit_clean` AT ALL. Nothing here can verify the assertion that a round came
   back with zero findings. That claim rests entirely on whoever wrote it.

Usage:
    python3 scripts/state.py           # render + verify (exit 1 on drift)
    python3 scripts/state.py --quiet   # verify only, print nothing when clean

Stdlib only, so it runs before any venv exists.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "docs" / "superpowers" / "PROJECT_STATE.json"

# Statuses that mean "the code for this exists".
SHIPPED = {"shipped", "shipped_unaudited"}

# Rounds running on this branch with NOTHING in the state file counting them
# warn below this number and are drift at or above it. It is audit_rule's HARD
# CAP -- three rounds without going clean means STOP AUDITING AND TELL KENNETH
# -- so the banner that blocks a session is the same threshold the rule already
# states. Kenneth's call, 2026-09-16.
UNPHASED_FAIL_ROUND = 3

BOLD, DIM, RED, GREEN, YELLOW, RESET = (
    "\033[1m", "\033[2m", "\033[31m", "\033[32m", "\033[33m", "\033[0m"
)

STATUS_STYLE = {
    "shipped":            (GREEN,  "SHIPPED"),
    "shipped_unaudited":  (YELLOW, "SHIPPED*"),
    "not_started":        (DIM,    "not started"),
    "needs_spec":         (DIM,    "needs spec"),
    "in_progress":        (YELLOW, "in progress"),
}


def probe(v: dict) -> tuple[bool, str]:
    """Run one verify probe. Returns (code_says_shipped, detail)."""
    path = ROOT / v["path"]
    if not path.exists():
        return False, f"{v['path']} does not exist"
    text = path.read_text(encoding="utf-8", errors="ignore")
    found = re.search(v["pattern"], text, re.M) is not None
    where = f"{v['pattern']!r} in {v['path']}"
    if v["kind"] == "present":
        return found, ("found " if found else "MISSING ") + where
    if v["kind"] == "defect_marker":
        # The pattern IS the unfixed defect. Finding it proves the work is
        # still outstanding -- the inverse of the other two kinds. Phase F is
        # the case that forced this: `v0_grid` merely EXISTING says nothing
        # about whether the calibration was fixed; the hardcoded `[0.04]`
        # literal is what says it was not.
        return (not found), ("defect still present: " if found else "defect gone: ") + where
    # kind == "absent": the SAME presence test as "present", with wording tuned
    # for a phase that has not shipped yet ("absent X" reads better than
    # "MISSING X" when absence is the expected state). The distinction is
    # cosmetic and nothing downstream branches on it -- said plainly here
    # because it previously looked load-bearing: main() carried an
    # `if kind == "absent" and means_shipped_if_present:` whose two branches
    # were character-for-character identical.
    return found, ("found " if found else "absent ") + where


def _round_numbers_in_branch_subjects(base_ref: str | None) -> tuple[int, list[str]] | None:
    """Highest `round N` mentioned in this branch's commit SUBJECTS.

    Returns (max_n, matching_subjects), or None when there is no evidence to
    read -- no git, no resolvable base, or a branch that is not ahead of it.
    Degrading to None is deliberate: this probe runs on every SessionStart, and
    a check that cries drift whenever git is unavailable would train the reader
    to scroll past a red banner.

    SUBJECTS ONLY, never bodies. Commit bodies here are full of legitimate
    backward references ("round 12's follow-ups", "round 7 rejected finding 8")
    that would fire this on every session.
    """
    if not base_ref or not re.fullmatch(r"[0-9A-Za-z._/-]+", base_ref):
        return None
    try:
        proc = subprocess.run(
            ["git", "log", "--format=%s", f"{base_ref}..HEAD"],
            cwd=ROOT, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None

    best = 0
    subjects: list[str] = []
    for line in proc.stdout.splitlines():
        hits = [int(m.group(1)) for m in re.finditer(r"\bround\s+(\d+)", line, re.I)]
        if not hits:
            continue
        subjects.append(line.strip())
        best = max(best, *hits)
    if not best:
        return None
    return best, subjects


def _resolve_base_ref() -> str | None:
    """The ref this branch's rounds are measured against. Asked of git, not of
    the state file.

    It used to come from `state["main"]`, which was a bare sha when this probe
    was written (2026-09-07) and became a narrative paragraph two days later
    (2242f36, "Point the state file at merged main"). From that commit on the
    ref guard in `_round_numbers_in_branch_subjects` rejected it, so this whole
    check returned None on EVERY run -- silently, for a week, through F1, F2,
    Phase G and the bearish direction-conviction gate fix. The check the file
    documents as its one non-code probe was dead and rendered "No drift".

    The lesson is narrower than "that field was wrong": a field that doubles as
    prose for a human reader cannot also be a machine input, because the humans
    will keep writing prose into it and nothing will complain. So ask git.
    `origin/main` first -- it is the base work is actually cut from, and a
    local `main` can be stale, which would widen the range and overcount.
    """
    for ref in ("origin/main", "main"):
        try:
            proc = subprocess.run(
                ["git", "rev-parse", "--verify", "--quiet", ref],
                cwd=ROOT, capture_output=True, text=True, timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if proc.returncode == 0:
            return ref
    return None


def _pointer_target(state: dict) -> tuple[dict | None, str]:
    """Resolve `active_phase` against BOTH pools that carry audit counts.

    It was resolved against `phases` alone, which is why work that is not a
    phase had nowhere to point: O4, G5-1 and the bearish gate fix are scoped
    pieces, and a piece cannot set a pointer that only accepts phase ids. The
    audit_rule says in as many words that it "applies to `already_shipped`
    entries identically", and those entries carry the same
    `audit_rounds`/`audit_clean` pair, so an entry there is just as valid a
    target. Matched on `name`, because they have no `id`.

    Returns (entry, label). `entry` is None when the pointer is unset or names
    something in neither pool; `label` describes the pointer either way, so the
    message can say which of those two it was.
    """
    active = state.get("active_phase")
    if not active:
        return None, "active_phase is null"
    for ph in state["phases"]:
        if ph["id"] == active:
            return ph, f"Phase {ph['id']} ({ph['name']})"
    for item in state.get("already_shipped", []):
        if item.get("name") == active:
            return item, f"shipped item '{item['name']}'"
    return None, (
        f"active_phase names '{active}', which is in neither phases nor already_shipped"
    )


def audit_bookkeeping_drift(state: dict) -> tuple[str, str] | None:
    """Check the ONE pair of fields no verify probe covers.

    `audit_rounds` and `audit_clean` are read, rendered, and drive this
    project's central rule -- nothing is done until a round comes back clean --
    while every `verify` probe tests a code symbol instead. So the bookkeeping
    itself was verified against nothing, and it drifted: three Phase A rounds
    had run while the file said one, because round 2 recorded its findings in a
    commit message and never here. This script printed "No drift" throughout.

    The evidence git actually holds is that a round produced commits. So: take
    the highest `round N` in this branch's commit subjects and compare it
    against the count declared by whatever `active_phase` points at. Scoping to
    that one target is what makes the comparison mean anything: Phase D's 13
    clean rounds are the global maximum, so comparing against every entry could
    never fire, and comparing against merely-open work fires forever once the
    active target goes clean (round 4 finding 6).

    Returns (severity, message), where severity is "drift" (exit non-zero) or
    "warn" (printed, exit 0), or None when there is nothing to say.

    One-directional on purpose. A file claiming MORE rounds than git shows is
    not evidence of anything: rounds legitimately run without producing a
    commit, and merged history moves out of the range.
    """
    evidence = _round_numbers_in_branch_subjects(_resolve_base_ref())
    if evidence is None:
        return None
    git_max, subjects = evidence
    shown = "; ".join(subjects[:3])

    target, label = _pointer_target(state)

    if target is None:
        # UNPHASED ROUNDS -- rounds are running and NOTHING in the file counts
        # them. This returned None, silently, and that silence is how four
        # adversarial rounds on the bearish gate fix ran while the render said
        # "No drift": the work was a scoped piece, so active_phase was null,
        # and the git evidence computed immediately above was thrown away.
        #
        # ROUND 4 FINDING 6 objected to exactly this shape of banner, and the
        # objection still stands where it applies: a red banner that cannot be
        # cleared trains the reader to scroll past the real ones. This one CAN
        # be cleared, by two separate routes -- point active_phase at the phase
        # or already_shipped entry these rounds belong to and record the count
        # there, or merge, after which the range is empty and this goes quiet
        # on its own. Finding 6's case had neither route: it compared against a
        # pool of not-started phases that no action could satisfy.
        severity = "drift" if git_max >= UNPHASED_FAIL_ROUND else "warn"
        cap = (
            f"audit_rule's HARD CAP is {UNPHASED_FAIL_ROUND} rounds without going "
            f"clean: STOP AUDITING AND TELL KENNETH -- that is evidence the batch "
            f"is too big to audit, not that it needs another round."
            if severity == "drift" else
            f"Escalates to drift at round {UNPHASED_FAIL_ROUND}, audit_rule's HARD CAP."
        )
        return severity, (
            f"Audit bookkeeping: this branch's commit subjects reach round {git_max}, "
            f"and nothing in PROJECT_STATE.json is counting them ({label}). Point "
            f"active_phase at the phase or already_shipped entry these rounds belong "
            f"to, and record the count there. {cap} Subjects: {shown}"
        )

    declared = target.get("audit_rounds") or 0
    if git_max <= declared:
        return None

    return "drift", (
        f"Audit bookkeeping: this branch's commit subjects reach round {git_max}, but "
        f"{label} -- the active target -- declares {declared}. "
        f"A round ran and was never written down — subjects: {shown}"
    )


def main() -> int:
    quiet = "--quiet" in sys.argv
    state = json.loads(STATE.read_text(encoding="utf-8"))
    drift: list[str] = []
    unaudited: list[str] = []

    if not quiet:
        print(f"\n{BOLD}Bamendjou — stop-model state{RESET}  "
              f"{DIM}(source: docs/superpowers/PROJECT_STATE.json, updated {state['updated']}){RESET}")
        print(f"{DIM}main {state['main']} · branch {state['working_branch']}{RESET}\n")
        print(f"  {BOLD}{'':<2} {'PHASE':<42} {'STATUS':<13} {'AUDIT':<22}{RESET}")

    for ph in state["phases"]:
        declared_shipped = ph["status"] in SHIPPED
        code_shipped, detail = probe(ph["verify"])

        # `probe` already returns "does the code say this shipped?" for every
        # kind, "absent" and "defect_marker" included. There is nothing left to
        # branch on here.
        actual_shipped = code_shipped

        if declared_shipped != actual_shipped:
            drift.append(
                f"Phase {ph['id']} ({ph['name']}): declared '{ph['status']}' but the code says "
                f"{'BUILT' if actual_shipped else 'NOT BUILT'} — {detail}"
            )

        rounds, clean = ph["audit_rounds"], ph["audit_clean"]
        if declared_shipped and not clean:
            unaudited.append(f"Phase {ph['id']} ({ph['name']}) — {rounds} round(s) run, none clean")

        if not quiet:
            colour, label = STATUS_STYLE.get(ph["status"], ("", ph["status"]))
            if clean:
                audit = f"{GREEN}clean after {rounds}{RESET}"
            elif rounds:
                audit = f"{RED}{rounds} run, NOT clean{RESET}"
            elif declared_shipped:
                audit = f"{RED}NEVER AUDITED{RESET}"
            else:
                audit = f"{DIM}—{RESET}"
            dep = ph.get("depends_on")
            gate = f" {DIM}(needs {'+'.join(dep)}){RESET}" if dep else ""
            print(f"  {BOLD}{ph['id']:<2}{RESET} {ph['name'][:42]:<42} "
                  f"{colour}{label:<13}{RESET} {audit}{gate}")

    # already_shipped is not a second-class list. It holds work that is finished
    # as CODE, which says nothing about whether it is finished as WORK -- the
    # audit rule applies to every line of it exactly as it applies to a phase.
    # Walking only `phases` is how the stop-cost notation rework came to sit
    # here with audit_clean=false and never once appear in a session's target
    # list: the render showed it as shipped, the UNAUDITED block never named it,
    # and the next session planned an audit around a list that was missing it.
    shipped_items = state.get("already_shipped", [])
    for item in shipped_items:
        if not item.get("audit_clean"):
            rounds = item.get("audit_rounds", 0)
            unaudited.append(
                f"Shipped: {item['name']} — {rounds} round(s) run, none clean"
            )
        # A verify probe is OPTIONAL here (several of these predate the state
        # file and have no single load-bearing marker), but where one is given
        # it is checked exactly as a phase's is. Declaring something shipped is
        # a claim about the code, wherever in the file the claim is written.
        v = item.get("verify")
        if v:
            code_shipped, detail = probe(v)
            if not code_shipped:
                drift.append(
                    f"Shipped item '{item['name']}': declared shipped but the code "
                    f"says NOT BUILT — {detail}"
                )

    bookkeeping = audit_bookkeeping_drift(state)
    if bookkeeping:
        severity, message = bookkeeping
        # "drift" joins the red block and exits non-zero; "warn" joins the
        # yellow UNAUDITED block and exits 0. Both blocks print even under
        # --quiet, which is the point: a bookkeeping warning that only shows in
        # the full render is invisible to the SessionStart hook that runs this.
        (drift if severity == "drift" else unaudited).append(message)

    if not quiet:
        print(f"\n  {DIM}SHIPPED* = code exists but has never survived an adversarial round.{RESET}")
        if shipped_items:
            print(f"\n  {BOLD}{'':<2} {'ALREADY SHIPPED':<42} {'STATUS':<13} {'AUDIT':<22}{RESET}")
            for item in shipped_items:
                clean = item.get("audit_clean")
                rounds = item.get("audit_rounds", 0)
                if clean:
                    audit = f"{GREEN}clean{RESET}"
                elif rounds:
                    audit = f"{RED}{rounds} run, NOT clean{RESET}"
                else:
                    audit = f"{RED}NEVER AUDITED{RESET}"
                colour = GREEN if clean else YELLOW
                label = "shipped" if clean else "SHIPPED*"
                print(f"  {BOLD}{'·':<2}{RESET} {item['name'][:42]:<42} "
                      f"{colour}{label:<13}{RESET} {audit}")
        if state.get("pending_kenneth"):
            print(f"\n  {BOLD}Waiting on Kenneth:{RESET}")
            for item in state["pending_kenneth"]:
                print(f"    · {item[:110]}")
        if state.get("open_questions"):
            print(f"\n  {BOLD}Open questions:{RESET}")
            for q in state["open_questions"]:
                print(f"    · {q[:110]}")
            # The 2026-09-08 triage moved two kinds of entry out of this list:
            # settled ones (`closed_questions`) and round-finding dumps
            # (`archived_round_records`). Neither is a decision anyone owes, so
            # neither is printed in full — but they are NOT deleted, and a list
            # that vanishes silently is how a session comes to believe the
            # record is shorter than it is. One counted line keeps them findable.
            filed = [
                (len(state.get(k, {}).get("items", [])), label)
                for k, label in (("closed_questions", "closed"),
                                 ("archived_round_records", "archived round records"))
            ]
            if any(n for n, _ in filed):
                print(f"    {DIM}(+ {', '.join(f'{n} {label}' for n, label in filed if n)} "
                      f"— in PROJECT_STATE.json, not printed){RESET}")
        print(f"\n  {BOLD}Read first:{RESET}")
        for d in state["authoritative_documents"][:4]:
            print(f"    · {d['path']}")
        print()

    if unaudited:
        print(f"{YELLOW}{BOLD}UNAUDITED WORK — the rule is nothing is done until a round comes back clean:{RESET}")
        for u in unaudited:
            print(f"  {YELLOW}!{RESET} {u}")
        print()

    if drift:
        print(f"{RED}{BOLD}STATE DRIFT — PROJECT_STATE.json disagrees with the code:{RESET}")
        for d in drift:
            print(f"  {RED}x{RESET} {d}")
        print(f"\n  {DIM}Fix the JSON (or the code) before trusting anything else in it.{RESET}\n")
        return 1

    if not quiet:
        print(f"  {GREEN}No drift: every declared status matches the code.{RESET}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
