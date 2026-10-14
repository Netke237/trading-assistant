#!/usr/bin/env python3
"""Render and VERIFY docs/superpowers/PROJECT_STATE.json.

The point of this script is drift. A status document that is only prose starts
lying the moment someone builds something and forgets to update it -- which is
exactly how a previous session came to believe pieces were unbuilt that were,
and built that were not.

So every phase in PROJECT_STATE.json carries a `verify` probe: a pattern whose
presence or absence in the real code checks the code-existence part of the
declared status. This script runs all of them and exits non-zero when that
claim and the codebase disagree. `built` records code that exists but is
unmerged; `shipped` records merged work. Probes do not establish merge status.

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

3. A BASE REF THAT DOES NOT RESOLVE -- except that it no longer fails silently.
   Round 1 finding 1: with no `origin/main` and no `main` (a `--single-branch`
   or `--depth 1` clone does this) the check cannot run at all, and it used to
   return None, which renders as "No drift" -- a clean bill for a check that
   never happened, the exact observable the base-ref fix exists to remove. It
   now says so in the UNAUDITED block instead. It still exits 0: git being
   unavailable is not evidence of drift.

4. `audit_clean` AT ALL. Nothing here can verify the assertion that a round came
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
BUILT_STATUSES = {"built", "shipped", "shipped_unaudited"}

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
    "built":              (YELLOW, "BUILT"),
    "shipped":            (GREEN,  "SHIPPED"),
    "shipped_unaudited":  (YELLOW, "SHIPPED*"),
    "not_started":        (DIM,    "not started"),
    "needs_spec":         (DIM,    "needs spec"),
    "in_progress":        (YELLOW, "in progress"),
}


def probe(v: dict) -> tuple[bool, str]:
    """Run one verify probe. Returns (code_exists, detail), not proof of merge or audit."""
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


def _git(*args: str) -> str | None:
    """Run one git command in ROOT. Returns stdout, or None on any failure.

    Collapsing "git is missing", "git errored" and "git timed out" into one
    None is deliberate and matches how this probe has always degraded: a check
    that cries drift whenever git is unavailable trains the reader to scroll
    past a red banner. The CALLERS distinguish "could not look" from "looked
    and found nothing" -- see round 1 finding 1.
    """
    try:
        proc = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


# Returned by `_round_numbers_in_branch_subjects` when `git log` itself could not
# run (raised, timed out, or exited non-zero). Distinct from None, which means
# "looked and found no rounds" -- P6 D1: collapsing the two let a failed log
# render as "No drift", a clean bill for a check that never ran.
_GIT_FAILED = object()


# A round number as this repo's subjects actually write it (STATE-PROBE-FIXES,
# G1): "round 3", "Round-3", "rounds 6-7", "r3", "r1..r4", "r2+r3". `\bround\s+`
# alone missed every form but the first -- 57 of 300 subjects -- and an entry
# under-counted against "X r1..r4" rendered "No drift". Every number in a range
# counts, so the highest is the range's end. `rN` is lower-case only: upper-case
# R1-R9 is how plans number requirements. A false match is a false ALARM, the
# direction this probe accepts; a missed one is silence. Round 3 finding F2
# added the count written BEFORE the word -- "clean after 7 rounds", the Phase
# A/B/C/E merge subjects -- plus "rounds 1, 2 and 3", "round #3" and "audit_r3".
# Plural only there: "step 3 round 2" names round 2, not 3.
_ROUND_RE = re.compile(
    r"(?:\b(?i:rounds?)[\s#-]*|(?<![A-Za-z0-9])r)\d+"
    r"(?:\s*(?:-|–|\.\.|\+|/|&|,|\band\b|\bto\b)\s*(?:r|(?i:round)[\s#-]*)?\d+)*"
    r"(?![\w])"
    r"|\b\d+\s+(?i:rounds)\b"
)


# Only this canonical prefix assigns a subject to a phase; shorthand and
# arbitrary mentions remain unowned evidence.
_ROUND_OWNER_RE = re.compile(
    r"^docs\(state\): (?P<owner>\S+) (?:(?:plan|code) )?round \d+(?![\w])"
)


# The stage word written straight before a round: "plan round 3", "code r2".
_STAGE_TAG_RE = re.compile(r"\b(?i:(plan|code))[\s-]+$")


def _round_hits(line: str) -> list[tuple[int, str | None]]:
    """Every round number one subject names, each with the stage word written
    before it ("plan" / "code", lower-cased) or None when there is none.

    Only the per-stage cap reads the tag, through `_staged_hits`, which also
    gives untagged rounds a stage; everything else reads the numbers alone. Every number in a range carries
    its range's tag: "code rounds 1-2" is code rounds 1 and 2.
    """
    hits: list[tuple[int, str | None]] = []
    for match in _ROUND_RE.finditer(line):
        text = match.group(0)
        tag = _STAGE_TAG_RE.search(line[:match.start()])
        stage = tag.group(1).lower() if tag else None
        numbers = list(re.finditer(r"\d+", text))
        implicit = [
            number for number in numbers[1:]
            if not re.search(r"(?:r|(?i:round)[\s#-]*)$", text[:number.start()])
        ]
        # Only a sole comma-introduced implicit K in "round N, K findings"
        # is a finding count. Explicit rounds and ambiguous lists stay evidence.
        finding_count = None
        if re.match(r"(?i:round)\b", text) and len(implicit) == 1:
            number = implicit[0]
            if (re.search(r",\s*$", text[:number.start()])
                    and re.match(r"\s+(?i:findings?)\b", line[match.start() + number.end():])):
                finding_count = number
        hits.extend((int(number.group(0)), stage) for number in numbers
                    if number is not finding_count)
    return hits


def _round_numbers_in_branch_subjects(
    base_ref: str | None, merged_ref: str | None = None, *,
    active_phase: str | None = None, known_phase_ids: set[str] | None = None,
) -> "tuple[int, list[str]] | None | object":
    """Highest `round N` mentioned in this branch's commit SUBJECTS.

    `base_ref` is where the span starts -- the resolved base, or the narrower
    commit `_target_scoped_base` picked. `merged_ref` is the resolved base
    itself, and every commit it already carries is dropped from the span.
    Without that, a narrowed `sha..HEAD` took in every commit the branch
    MERGED IN from main after `sha`, so a branch that merged origin/main to
    stay current answered for other pieces' already-merged rounds: A5c's
    "round 4" subject drew drift on MANUAL-IBKR-CONFIRM-AS-ERROR's honest
    count of 3. Merged history is out of range on the unnarrowed span; this
    makes the narrowed span agree. It is `^merged_ref`, not `--first-parent`:
    first-parent would also drop this branch's OWN commits that arrived by
    merging a sibling branch that has NOT reached main, and those are exactly
    the rounds an undercount hides in.

    WHAT IT COSTS, stated rather than discovered (round 1 of this piece):

      - SILENT: a round of THIS piece that reached main on a sibling branch
        before this branch merged main is dropped too. In the graph it is the
        same shape as another piece's merged round, so git cannot tell them
        apart. It is the unnarrowed span's existing rule -- merged rounds are
        out of range -- now applied to the narrowed one.
      - LOUD: only the ONE ref `_resolve_base_ref` picked is excluded, not
        every candidate. When tightest-wins picks a ref that does not hold the
        merged main commits (a local main moved onto the branch and never
        pushed), their rounds still count. Excluding every candidate would
        close that by widening the silent case above, so it stays a false
        alarm.
      - LOUD: this branch's own merge commit is not on main, so a subject like
        "Merge origin/main (A5c round 4 clean) into ..." still counts. Name
        rounds in merge subjects only for this branch's own piece.
      - LOUD: rounds for ANOTHER piece that have not reached main still
        count unless their subjects explicitly assign them to a different
        known phase below. Unowned and shorthand records still cause alarms.
      - PRE-EXISTING, unchanged: a sibling cut from this branch AFTER the
        entry's introducing commit that reaches main first puts that commit on
        main, so no narrowing happens and its rounds are out of range.

    Returns (max_n, matching_subjects), or None when there is no evidence to
    read -- no resolvable base, a ref refused by shape, or a branch whose span
    holds no `round N` subject. Returns `_GIT_FAILED` when `git log` itself did
    not run, which the caller reports as COULD NOT RUN (P6 D1).
    Degrading to None is deliberate: this probe runs on every SessionStart, and
    a check that cries drift whenever git is unavailable would train the reader
    to scroll past a red banner.

    With a resolved active phase and known phase IDs, a canonical subject
    beginning `docs(state): FULL-PHASE-ID round N` (or `plan round N` / `code
    round N` after the ID) belongs to that known phase, case-sensitively. Skip
    it only when it belongs to a DIFFERENT phase and the active ID is absent
    as a whole token from the rest of the subject. Mixed subjects stay evidence.
    Unknown owners, shorthand and other prefixes stay evidence too. With no
    resolved active phase, or for callers omitting these keywords, keep all
    evidence as before. IDs use word characters and hyphens for token boundaries.

    For singular `round N, K findings`, a sole comma-introduced implicit K is
    a finding count, not a round. Primary and explicitly marked round/r numbers,
    plural round lists, other delimiters and ambiguous multiple implicit numbers
    stay evidence.
    This parsing rule applies even when ownership filtering is not enabled.

    SUBJECTS ONLY, never bodies. Commit bodies here are full of legitimate
    backward references ("round 12's follow-ups", "round 7 rejected finding 8")
    that would fire this on every session.
    """
    # No leading '-': such a "ref" is an option to git, not a revision.
    ref_shape = r"[0-9A-Za-z._/][0-9A-Za-z._/-]*"
    if not base_ref or not re.fullmatch(ref_shape, base_ref):
        return None
    revs = [f"{base_ref}..HEAD"]
    if merged_ref and merged_ref != base_ref:
        if not re.fullmatch(ref_shape, merged_ref):
            return None
        revs.append(f"^{merged_ref}")
    try:
        proc = subprocess.run(
            ["git", "log", "--format=%s", *revs],
            cwd=ROOT, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return _GIT_FAILED
    if proc.returncode != 0:
        return _GIT_FAILED

    active_token = (
        re.compile(r"(?<![\w-])" + re.escape(active_phase) + r"(?![\w-])")
        if active_phase and known_phase_ids and active_phase in known_phase_ids else None
    )
    best = 0
    subjects: list[str] = []
    for line in proc.stdout.splitlines():
        owner = _ROUND_OWNER_RE.match(line) if active_token else None
        if (owner and owner["owner"] in known_phase_ids
                and owner["owner"] != active_phase
                and not active_token.search(line[owner.end("owner"):])):
            continue
        hits = [n for n, _ in _round_hits(line)]
        if not hits:
            continue
        subjects.append(line.strip())
        best = max(best, *hits)
    if not best:
        return None
    return best, subjects


_BASE_REF_CANDIDATES = ("origin/main", "main")

# Cap on how far back to read the state file when scoping rounds to the current
# pointer. A branch under audit is a handful of commits; anything past this is a
# repo shape this probe should degrade on rather than stall a SessionStart.
_POINTER_SCAN_LIMIT = 100


def _resolve_base_ref() -> tuple[str | None, str]:
    """The ref this branch's rounds are measured against. Asked of git, not of
    the state file. Returns (ref, detail); ref is None when nothing resolved and
    detail then says WHY, because the caller has to be able to say so.

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

    TIGHTEST WINS, not a fixed order (round 1 finding 3). Preferring
    `origin/main` outright was wrong for the shape this project actually
    produces: it merges with a local `--no-ff` and pushes afterwards, and
    pushing from these containers has 403'd before now. Between the merge and
    the push, `origin/main` is the STALE one, so preferring it kept a banner up
    that the merge was supposed to clear -- and "push to clear it" is not
    always a route that exists. The ref yielding the FEWEST commits in
    `ref..HEAD` is the one that already contains the most merged work, which is
    exactly the base that should not be counted twice. Ties go to the earlier
    candidate.
    """
    measured: list[tuple[int, int, str]] = []
    for rank, ref in enumerate(_BASE_REF_CANDIDATES):
        # Each candidate is measured independently: a transient failure on one
        # must not skip the other. The first version returned None from inside
        # this loop, which made a timeout on `origin/main` silently discard the
        # `main` fallback.
        if _git("rev-parse", "--verify", "--quiet", ref) is None:
            continue
        out = _git("rev-list", "--count", f"{ref}..HEAD")
        if out is None:
            continue
        try:
            measured.append((int(out.strip()), rank, ref))
        except ValueError:
            continue

    if not measured:
        if _git("rev-parse", "--git-dir") is None:
            return None, "there is no usable git repository here"
        return None, (
            "neither origin/main nor main resolves in this checkout -- a "
            "--single-branch or --depth 1 clone does this, and so does a "
            "repository with no commits on it yet"
        )
    measured.sort()
    ref = measured[0][2]
    return ref, f"base {ref}"


_TARGET_UNREADABLE = object()   # a historical blob that is not a state file
_TARGET_ABSENT = object()       # parses fine, but this target is not in it


def _target_identity(state: dict) -> tuple[str, str] | None:
    """The (pool, key) pair naming whatever `active_phase` RESOLVES to, or None
    when it resolves to nothing.

    None covers both the unset pointer and the truthy one that names something
    in neither pool -- a typo, or an `already_shipped` entry renamed while the
    pointer still holds the old string. Those were separate cases until round 1
    of STATE-PROBE-NULL-POINTER, and keeping them separate was the bug: the
    dangling pointer took the NARROWING path here and the UNPHASED path in
    `audit_bookkeeping_drift` at the same time, so the escalation ran against a
    window the same nonsense value had just emptied. A pointer that resolves to
    nothing is the ABSENCE of a target, exactly as a null one is.
    """
    active = state.get("active_phase")
    if not active:
        return None
    for ph in state.get("phases", []):
        if isinstance(ph, dict) and ph.get("id") == active:
            return "phase", active
    for item in state.get("already_shipped", []):
        if isinstance(item, dict) and item.get("name") == active:
            return "shipped", active
    return None


def _entry_rounds(entries, pool: str, key: str) -> int | None:
    """This target's `audit_rounds` inside one `phases`/`already_shipped` list,
    or None when the list does not carry it. A non-int count is a malformed
    entry rather than a high-water mark, so it reads as 0."""
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("id" if pool == "phase" else "name") == key:
            value = entry.get("audit_rounds")
            ok = isinstance(value, int) and not isinstance(value, bool)
            return value if ok else 0
    return None


def _declared_rounds_at(blob: str, identity: tuple[str, str]):
    """This target's `audit_rounds` in one HISTORICAL state file.

    Returns an int, `_TARGET_ABSENT` when the file parsed but does not carry
    this target, or `_TARGET_UNREADABLE` when it could not be parsed at all.
    Absence is NOT zero: it marks the commit before the piece existed, and that
    distinction is what keeps a new piece from answering for the rounds of the
    piece before it.
    """
    try:
        old = json.loads(blob)
    except ValueError:
        return _TARGET_UNREADABLE
    if not isinstance(old, dict):
        return _TARGET_UNREADABLE

    pool, key = identity
    entries = old.get("phases" if pool == "phase" else "already_shipped", [])
    if not isinstance(entries, list):
        return _TARGET_UNREADABLE
    rounds = _entry_rounds(entries, pool, key)
    return _TARGET_ABSENT if rounds is None else rounds


def _target_scoped_base(base_ref: str, state: dict) -> str:
    """Narrow `base_ref..HEAD` to the span the ACTIVE TARGET'S OWN COUNT covers.

    ROUND 1 FINDING 2 (of STATE-PROBE-REVIVAL) is why any narrowing exists.
    `_round_numbers_in_branch_subjects` takes the highest round over the whole
    branch while the pointer resolves exactly one piece, and nothing tied the
    two together -- so a branch carrying two pieces answered for the earlier
    one's round numbers, drawing a red banner on an entirely honest file whose
    printed remedy could only be satisfied by writing a number known to be
    false. That fix is preserved here; only its KEY has changed.

    IT USED TO KEY ON THE POINTER'S CURRENT VALUE, and that was the root cause
    of three findings across three consecutive rounds. `active_phase` is
    hand-written state in the very file whose honesty this check exists to
    test, so every escape was a variant of "move the pointer":

      - Round 3: clearing the pointer to `null` made the clearing commit the
        excluded boundary and collapsed the window to empty. Four rounds and a
        recorded undercount rendered "No drift" at exit 0.
      - Round 1 of the fix for that (option A), finding 1: RE-POINTING at the
        same piece with the false count left intact did the same thing, and
        needed no commit at all -- a working-tree edit was enough, because the
        walk hit `was != active` on the newest committed state file and fell
        through to `HEAD`, making `HEAD..HEAD` empty.
      - The same round, finding 2: a pointer that was truthy but resolved to
        nothing took the narrowing path AND the unphased path together.

    KENNETH CHOSE THE STRUCTURAL FIX on 2026-09-16 over patching those doors
    one at a time, on the evidence that three consecutive fixes had each
    contained the next instance of the same shape.

    SO THE BOUNDARY IS THE COMMIT THAT INTRODUCED THE ENTRY, and nothing else.
    Everything after it is this piece's to answer for.

    IT WAS BRIEFLY THE COUNT'S OWN HISTORY TOO -- "the newest commit where this
    target's `audit_rounds` was LOWER than the value now declared" -- and that
    shipped at d5fcbce as a REGRESSION, caught by the next round and reverted
    here. The reasoning behind it was inverted: raising `declared` makes MORE
    historical commits qualify as "lower", and since the newest qualifying one
    wins, raising the count moved the boundary FORWARD. In this repo's actual
    style, where every branch commit touches this file, the newest state-file
    commit almost always declares less than the live one -- so it became the
    boundary, the window collapsed, and EVERY undercount above zero rendered
    "No drift" at exit 0. It was strictly worse than the code it replaced, and
    it was worse in the direction this probe exists to refuse. Measured: five
    rounds in the subjects, file declaring anything from 1 to 4, silent.

    The introducing commit cannot be moved that way. It is where the entry
    APPEARED, not what the entry SAYS, so recording a number -- true or false,
    committed or not -- leaves it exactly where it was.

    What that buys, case by case:

      - The pointer's value no longer scopes anything. Clearing it, re-pointing
        at the piece, or misspelling it changes only WHICH target resolves, and
        when none resolves `_target_identity` returns None and this function
        does not narrow at all, so the unphased banner fires over the whole
        branch.
      - The two-piece branch stays fixed. A piece that has just opened is
        ABSENT from every commit before it, so its boundary is the commit that
        introduced it and the previous piece's rounds fall outside.

    THE ACCEPTED COST, stated rather than discovered: a piece whose entry
    predates the branch point is never ABSENT inside the range, so it gets NO
    narrowing and answers for the whole branch -- including an earlier piece's
    round numbers, on a file that is telling the truth. That is a false ALARM,
    it is visible, and it clears by merging or by recording the count. It is
    the deliberate trade for never going silent on an undercount, and it is the
    original Phase A catch's behaviour.

    AND ONE ROUTE REMAINS OPEN, KENNETH'S CALL, NOT PATCHED HERE: the entry's
    NAME and PRESENCE are still hand-written in the audited file, so renaming an
    `already_shipped` entry, moving it between `phases` and `already_shipped`,
    or dropping and restoring it makes every older commit read as ABSENT and
    resets the boundary to that commit. See the round record in
    PROJECT_STATE.json. Fixing it is not another patch of this shape: the round
    that found it argues a boundary computed from the audited file's own
    contents cannot both scope out a previous piece and detect an undercount of
    the current one, because both are the same edit.

    The boundary commit is EXCLUDED, since `git log sha..HEAD` excludes `sha`
    itself. A commit that both lowers the count and carries a round of the new
    count's work would be missed, but that ordering is backwards: the count is
    lowered when a piece opens, before it has had a round.
    """
    identity = _target_identity(state)
    if identity is None:
        # Nothing resolves, so there is nothing to scope to. Answer for the
        # whole branch and let the unphased path speak -- see the three
        # findings above, every one of which reached silence through this case.
        return base_ref

    try:
        rel = STATE.relative_to(ROOT).as_posix()
    except ValueError:
        # The state file is not under ROOT (only reachable when a caller has
        # repointed one of them). Cannot locate its history, so cannot narrow:
        # fall back to the full range rather than guess a boundary.
        return base_ref

    # `None` when even the newest COMMITTED state file lacks this entry -- the
    # piece exists only in the working tree. There is then no history to scope
    # by, so refuse to narrow rather than answer for the commits that happen to
    # follow the newest state-file commit: invent an entry, point at it, declare
    # 0, and the window would empty.
    boundary = _introducing_commit(base_ref, identity, rel)
    if boundary is None:
        return base_ref
    return boundary


def _blob_ids(specs: list[str]) -> dict[str, str | None] | None:
    """`<commit>:<path>` -> blob id, or None where that commit has no such
    file. One `git cat-file --batch-check` for all of them. None on failure."""
    try:
        proc = subprocess.run(
            ["git", "cat-file", "--batch-check"], cwd=ROOT, capture_output=True,
            text=True, timeout=10, input="".join(f"{s}\n" for s in specs),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    lines = proc.stdout.splitlines()
    if proc.returncode != 0 or len(lines) != len(specs):
        return None
    return {
        spec: (line.split()[0] if line.split()[1:2] == ["blob"] else None)
        for spec, line in zip(specs, lines)
    }


def _introducing_commit(base_ref: str, identity: tuple[str, str], rel: str) -> str | None:
    """The commit in `base_ref..HEAD` that INTRODUCED this entry: it carries
    the entry and none of its parents do. None when no commit in range does
    (the entry predates the branch, or exists only in the working tree).

    BY ANCESTRY, NOT DATE (STATE-PROBE-FIXES, G2). It used to walk `git log`'s
    date order and stop at the first commit lacking the entry, taking the one
    walked just before it. Merging a sibling branch whose later-dated
    state-file commit lacked the entry put that commit first in the walk, so
    the MERGE became the boundary and the window emptied: four rounds against
    one declared, silent. A parent is a fact of the graph, so asking each
    commit's own parents cannot be reordered by a merge.

    Newest first in topological order, so a dropped-and-restored entry still
    resets to the restoring commit -- the accepted hole the round record names.
    Past `_POINTER_SCAN_LIMIT` commits, falls back to the oldest commit walked
    that CONFIRMED carries the entry rather than widening to the full range.
    """
    out = _git("log", "--topo-order", "--format=%H %P", f"{base_ref}..HEAD", "--", rel)
    if out is None:
        return None
    rows = [line.split() for line in out.splitlines() if line.strip()]
    truncated = len(rows) > _POINTER_SCAN_LIMIT
    rows = rows[:_POINTER_SCAN_LIMIT]
    specs = sorted({f"{sha}:{rel}" for row in rows for sha in row})
    oids = _blob_ids(specs)
    if oids is None:
        return None
    parsed: dict[str, object] = {}

    def rounds_at(sha: str):
        oid = oids.get(f"{sha}:{rel}")
        if oid is None:
            return _TARGET_ABSENT       # no state file at all in that commit
        if oid not in parsed:
            blob = _git("cat-file", "-p", oid)
            parsed[oid] = (_TARGET_UNREADABLE if blob is None
                           else _declared_rounds_at(blob, identity))
        return parsed[oid]

    oldest_carrier: str | None = None
    for sha, *parents in rows:
        here = rounds_at(sha)
        if here is _TARGET_ABSENT or here is _TARGET_UNREADABLE:
            continue
        oldest_carrier = sha
        # An unreadable parent is not proof of absence, so it is not a
        # boundary to trust: the walk goes on and the window stays wider.
        if all(rounds_at(p) is _TARGET_ABSENT for p in parents):
            return sha
    return oldest_carrier if truncated else None


def _whole_number(raw) -> int | None:
    """`audit_rounds` read as a whole number in any spelling JSON allows (3,
    3.0, "3"); None when it is not one. A missing count is 0."""
    if raw is None:
        return 0
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float) and raw.is_integer():
        return int(raw)
    # isdecimal, not isdigit: '²' passes isdigit and int('²') raises, a
    # traceback in the SessionStart hook (open question P6 UNIT D round 7).
    if isinstance(raw, str) and raw.strip().isdecimal():
        return int(raw.strip())
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
        # ROUND 1 FINDING 8: `""`, `0` and `False` all land here and all
        # reported as "null", so a reader grepping this file for the value they
        # saw would not find it. The null wording stays for the null case.
        if active is None:
            return None, "active_phase is null"
        return None, f"active_phase is {active!r}, which is falsy and names nothing"
    for ph in state["phases"]:
        if ph["id"] == active:
            return ph, f"Phase {ph['id']} ({ph['name']})"
    for item in state.get("already_shipped", []):
        if item.get("name") == active:
            return item, f"shipped item '{item['name']}'"
    return None, (
        f"active_phase names '{active}', which is in neither phases nor already_shipped"
    )


_CODE_WORD_RE = re.compile(r"\b(?i:code)\b")
_PLAN_WORD_RE = re.compile(r"\b(?i:plan)\b")
# Any word that can turn "clean" into its opposite, anywhere in the subject.
_NEGATION_RE = re.compile(r"\b(?i:not|no|never|none|without|yet|unclean)\b|(?i:n't)\b")


def _clean_plan_round_re(n: int) -> re.Pattern:
    """A subject saying plan round `n` came back clean, in the canonical shape
    only: "clean" straight after the round's own number ("plan round 3 CLEAN",
    "plan r3: clean"), never "clean up". Round 2 finding G1: "clean" anywhere
    in the subject let "plan round 3 did not come back clean" and "4 gate
    findings, tests clean" prove a clean close. The caller also refuses any
    subject carrying `_NEGATION_RE`, so "plan round 3 clean? no" is not proof.
    """
    return re.compile(
        r"\b(?i:plan)[\s-]+(?:(?i:round)[\s#-]*|r)" + str(n)
        + r"(?!\d)\s*[:(\-–—]*\s*(?i:clean)\b(?!\s*-?\s*(?i:up)\b)"
    )


# One round written with both its numbers side by side: "round 4 (code round
# 1)" (m1, k1) or "code round 2 = round 5" (k2, m2). Only spaces, "(", "[" and
# "=" may sit between them -- not ";", ",", a dash or a word, which is how a
# subject moves on to a DIFFERENT round ("code round 2 fixed; round 3").
_ROUND_WORD = r"(?:(?i:round)[\s#-]*|(?<![A-Za-z0-9])r)"
_PAIR_RE = re.compile(
    _ROUND_WORD + r"(?P<m1>\d+)[\s(\[=]*\b(?i:code)[\s-]+" + _ROUND_WORD + r"(?P<k1>\d+)(?!\d)"
    r"|\b(?i:code)[\s-]+" + _ROUND_WORD + r"(?P<k2>\d+)[\s(\[=]*" + _ROUND_WORD + r"(?P<m2>\d+)(?!\d)"
)


def _staged_hits(subject: str, plan_rounds: int) -> list[tuple[int, str | None]]:
    """`_round_hits`, with a stage given to the rounds that carry no stage word
    of their own -- read only once a `plan_stage` holds, at `plan_rounds`.

    Round 1 finding F1 of STATE-PER-STAGE-CAP: this repo spells code rounds
    more ways than "code round N" -- "A5 round 3 (code): not clean -- hard cap
    reached", "ALERT-INDICATOR-ID-MAP code audit r3", "Code audit round 2" --
    and reading those as continuous numbering put a code stage at its cap
    under "No drift". So an untagged round M is:

      - CONTINUOUS (None) only when it is written SIDE BY SIDE with a tagged
        "code round K" as one round -- separated by nothing but spaces, "(",
        "[" or "=" (`_PAIR_RE`) -- and M - plan_rounds == K: the record's form,
        "round 4 (code round 1)", or "code round 2 = round 5";
      - otherwise a CODE round M when "code" appears anywhere in the subject,
        tagged code round beside it or not (round 2 finding G2, and round 3
        finding H1: "code round 2 fixed; round 3 NOT CLEAN" is code round 3
        whatever the plan stage's length -- pairing on the arithmetic alone
        read it as code round 2 whenever the plan stage closed at round 1);
      - otherwise a PLAN round M when "plan" does ("docs(plan): X round 4");
      - otherwise CONTINUOUS.

    WHICH WAY EACH RULE ERRS. The code-word rules read M at face value, so a
    stray "code" ("round 4 records the code fixes") is a false alarm. The
    pairing rule reads lower only when the subject writes both numbers of one
    round side by side. The plan-word rule and the last rule read lower, and
    silence a code round M numbered from 1 in a subject naming no "code" --
    the accepted cost `_stage_round_max` states.
    """
    hits = _round_hits(subject)
    paired = set()
    for pair in _PAIR_RE.finditer(subject):
        if pair["m1"]:
            m, k = int(pair["m1"]), int(pair["k1"])
        else:
            m, k = int(pair["m2"]), int(pair["k2"])
        if m - plan_rounds == k:
            paired.add(m)
    if _CODE_WORD_RE.search(subject):
        inferred = "code"
    elif _PLAN_WORD_RE.search(subject):
        inferred = "plan"
    else:
        inferred = None
    return [
        (n, stage) if stage
        else (n, None) if n in paired
        else (n, inferred)
        for n, stage in hits
    ]


def _plan_stage(
    target: dict, key, declared: int | None, state: dict, subjects: list[str],
) -> tuple[int | None, str | None]:
    """Where this target's PLAN stage ended, read off its optional
    `plan_stage: {"rounds": N, "closed_by": "<decision id>" | "clean"}`.

    audit_rule's HARD CAP is counted PER STAGE (AUDIT-CAP-PER-STAGE-2026-09-25)
    while records and subjects number rounds continuously, so a plan stage that
    closed at round 3 left every round after it reading as past the cap: the
    whole build stage under a red banner it could not clear. The field moves
    where the cap starts counting, and nothing else.

    IT IS NOT AN ACKNOWLEDGEMENT FLAG, and every bound below is what keeps it
    from becoming one. It can move the threshold by at most the cap itself; it
    cannot claim more rounds than the target declares it ran; a decision it
    cites must exist and name this target; "clean" must be backed by a subject
    on this branch saying plan round N was clean, in `_clean_plan_round_re`'s
    canonical shape and with no negation word anywhere in it (round 1 finding
    F2: unchecked, one word silenced a plan stage at 3 rounds NOT clean); and a
    plan round
    above N on this branch, as `_staged_hits` reads them, contradicts it
    outright. Any of those, and the field is ignored -- the cap counts from
    round 1, exactly as if it were absent -- and the reason is returned so the
    caller can say so. What the code stage then trips on is `_stage_round_max`.

    Returns (N, None) when it holds, (None, None) when it is absent, and
    (None, reason) when it is present but refused.
    """
    raw = target.get("plan_stage")
    if raw is None:
        return None, None

    def refused(why: str) -> tuple[None, str]:
        return None, (
            f"plan_stage={raw!r} is IGNORED ({why}), so the hard cap counts this "
            f"target's rounds from round 1."
        )

    if not isinstance(raw, dict):
        return refused("it is not an object")
    rounds = raw.get("rounds")
    if (not isinstance(rounds, int) or isinstance(rounds, bool)
            or not 1 <= rounds <= UNPHASED_FAIL_ROUND):
        return refused(
            f"rounds must be a whole number from 1 to {UNPHASED_FAIL_ROUND}, the "
            f"most a plan stage can run under the cap"
        )
    if declared is None:
        return refused("audit_rounds is not a whole number to check it against")
    if rounds > declared:
        return refused(f"rounds is more than the {declared} audit_rounds the target declares")
    staged = [(subject, _staged_hits(subject, rounds)) for subject in subjects]
    closed_by = raw.get("closed_by")
    if closed_by == "clean":
        clean_round = _clean_plan_round_re(rounds)
        if not any(
            clean_round.search(subject) and not _NEGATION_RE.search(subject)
            for subject in subjects
        ):
            return refused(
                f'closed_by is "clean" but no subject on this branch says plan '
                f"round {rounds} was clean"
            )
    else:
        # Round 1 finding F3: both are hand-edited, and a traceback here is a
        # crash in the SessionStart hook.
        decisions = state.get("decisions")
        if not isinstance(key, str) or not key.split() or not isinstance(decisions, list):
            return refused("there is no target id or decisions[] list to check closed_by against")
        name = key.split()[0]
        decision = next(
            (d for d in decisions
             if isinstance(d, dict) and isinstance(closed_by, str) and d.get("id") == closed_by),
            None,
        )
        if decision is None:
            return refused('closed_by must be "clean" or the id of an entry in decisions[]')
        token = re.compile(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])")
        if not token.search(json.dumps(decision, ensure_ascii=False)):
            return refused(f"decision {closed_by} does not name {name}")
    later = [n for _, hits in staged for n, stage in hits if stage == "plan" and n > rounds]
    if later:
        return refused(f"this branch's subjects name plan round {max(later)}, after it closed")
    return rounds, None


def _plan_stages(target, key, declared, state, subjects):
    """Validate cumulative plan intervals; return a precise drift reason or None.

    This path never changes persisted counters and never falls back to singular
    metadata. Only recorded answers authorize each following interval.
    """
    stages = target['plan_stages']
    if 'plan_stage' in target:
        return 'simultaneous plan_stage and plan_stages are ambiguous'
    if not isinstance(stages, list) or not stages:
        return 'plan_stages must be a nonempty ordered array'
    if declared is None:
        return 'audit_rounds must be a valid whole number'
    endpoints = []
    total = 0
    for stage in stages:
        if not isinstance(stage, dict):
            return 'each plan_stages entry must be an object'
        n = stage.get('rounds')
        if type(n) is not int or not 1 <= n <= UNPHASED_FAIL_ROUND:
            return 'plan stage rounds must be an integer from 1 to 3'
        total += n
        endpoints.append(total)
    if total > declared:
        return 'plan stages sum exceeds declared audit_rounds'
    if not isinstance(key, str) or not key.split():
        return 'plan stages have no target token'
    token = re.compile(r'(?<![\w-])' + re.escape(key.split()[0]) + r'(?![\w-])')
    decisions = state.get('decisions')
    openings = [None]
    # Bound the declaration before unrelated later prose (including negation).
    opening = re.compile(
        r'\bopen(?:s|ed)?\b[^.;!?]*?\bnew\s+plan\s+stage\b'
        r'[^.;!?]*?\bplan\s+rounds\s+(\d+)\s*[-–]\s*(\d+)\b', re.I)
    negative = re.compile(r"\b(?:not|never|no|cannot|can\s+not|decline\w*|reject\w*|without)\b|n't\b", re.I)
    for i in range(1, len(stages)):
        ident = stages[i].get('opened_by')
        matches = [d for d in decisions if isinstance(d, dict) and isinstance(ident, str)
                   and d.get('id') == ident] if isinstance(decisions, list) else []
        if len(matches) != 1:
            return 'opened_by must identify a unique decision in decisions[]'
        d = matches[0]
        if not token.search(json.dumps(d, ensure_ascii=False)):
            return 'opening decision does not name the target token'
        answer = d.get('a')
        if not isinstance(answer, str):
            return 'opening declaration must be in decision a'
        declarations = list(opening.finditer(answer))
        if len(declarations) != 1:
            return 'opening answer must contain exactly one bounded opening declaration'
        match = declarations[0]
        boundary = max(answer.rfind(c, 0, match.start()) for c in '.;!?') + 1
        # Only recognized fire-call policy prose may follow a colon/dash outside
        # the approval clause. Unknown suffixes fail closed, including indirect
        # approval qualifications and chained separators.
        following = re.search(r'[.;!?:]|\s--\s', answer[match.end():])
        if following and (following[0] == ':' or '--' in following[0]):
            suffix_start = match.end() + following.end()
            # Validate the entire excluded tail, including chained punctuation.
            # Only complete known policy controls qualify; a calls prefix cannot
            # hide opening conditions, denials, owners or different round ranges.
            policy = ' '.join(answer[suffix_start:].split()).casefold()
            controls = ('fire calls never wait',
                        'deadline-bound auto-trade fire-path tradier calls never wait')
            accepted = {control + tail for control in controls
                        for tail in ('', '.', '. not a merge approval.')}
            accepted.add(
                'deadline-bound auto-trade fire-path tradier calls '
                '(regime fetch incl. intraday, earnings veto, market-open price check) '
                'never wait and never fail on the limiter -- they take a slot if free, '
                'otherwise go anyway and book an overdraft '
                '(bucket negative, floored at -capacity 15); bulk traffic '
                '(scans, prewarm, monitors, probes) waits until it is repaid, '
                "so the average stays 120/min; the stock scan's earnings lookup "
                'waits for its slot before its 5 s deadline starts. q3 yes: a burst '
                'of at most 15 extra requests is accepted. q2 not needed. no counter '
                'reset: plan rounds 1-3 stay recorded; the scan-slowdown merge question '
                "stays pre-accepted ('ok go ahead', 2026-10-10). not a merge approval."
            )
            if policy not in accepted:
                return 'opening declaration has an unsupported colon/dash qualification'
        end = match.end() + following.start() if following else len(answer)
        local = answer[boundary:end]
        if (re.search(r'\b(?:should|could|would|might|may|whether|if)\b', local, re.I)
                or (following and following[0] == '?')):
            return 'opening declaration is conditional or interrogative, not affirmative'
        if negative.search(local):
            return 'opening declaration is locally negated'
        # A question's target mention cannot override an explicitly qualified
        # answer. Prefix qualifiers are bounded by the opening verb; suffix
        # qualifiers name identifier tokens, not later prose about the redesign.
        prefix = answer[boundary:match.start()]
        qualifiers = re.findall(r'\bfor\s+([^,:]+)', prefix, re.I)
        bare = re.fullmatch(r'\s*([\w-]+)\s*:\s*', prefix)
        if bare:
            qualifiers.append(bare[1])
        # Identifier ownership is case-insensitive even before trailing prose.
        # Article-led policy descriptions such as "for the overdraft redesign"
        # do not name a bare owner identifier.
        qualifiers += re.findall(
            r'\bfor\s+(?!(?:the|a|an)\b)'
            r'([\w-]+(?:\s+(?:or|and)\s+[\w-]+)*)\b',
            answer[match.start():end], re.I)
        question = d.get('q') if isinstance(d.get('q'), str) else ''
        alternatives = re.findall(
            token.pattern + r'\s+(?:or|and)\s+([\w-]+)', question, re.I)
        alternatives += re.findall(
            r'([\w-]+)\s+(?:or|and)\s+' + token.pattern, question, re.I)
        # Also recognize the question's competing identifier in lower-case
        # answer qualifiers, without treating ordinary redesign prose as an ID.
        for name in [key.split()[0], *alternatives]:
            if re.search(r'\bfor\s+(?:[\w-]+\s+(?:or|and)\s+)*'
                         + re.escape(name) + r'(?![\w-])',
                         answer[match.start():end], re.I):
                qualifiers.append(name)
        if any(q.strip().casefold() != key.split()[0].casefold() for q in qualifiers):
            return 'opening declaration qualifies a conflicting or ambiguous target'
        if alternatives and not qualifiers:
            return 'opening declaration leaves competing question targets ambiguous'
        start = endpoints[i - 1] + 1
        if (int(match[1]), int(match[2])) != (start, start + 2):
            return f'opening decision must authorize plan rounds {start}-{start + 2}'
        openings.append(ident)
    for i, stage in enumerate(stages):
        closure = stage.get('closed_by')
        if closure == 'clean':
            proof = _clean_plan_round_re(endpoints[i])
            evidence = [s for s in subjects if proof.search(s)]
            # Opposing clean claims at this endpoint cannot certify closure.
            relevant = [s for s in subjects if (endpoints[i], 'plan') in _staged_hits(s, total)]
            if not any(not _NEGATION_RE.search(s) for s in evidence) or any(
                    _NEGATION_RE.search(s) and re.search(r'\bclean\b', s, re.I) for s in relevant):
                return f'no uncontradicted clean proof for plan round {endpoints[i]}'
        elif i < len(stages) - 1:
            if closure != openings[i + 1]:
                return 'earlier stage must close clean or by the verified next opening decision'
        elif 'closed_by' in stage:
            return 'final plan stage cannot close by an unpaired acknowledgment decision'
    closed = stages[-1].get('closed_by') == 'clean'
    for subject in subjects:
        for n, kind in _staged_hits(subject, total):
            if kind == 'plan' and (n < 1 or n > total):
                return f'explicit plan round {n} is outside recorded intervals'
            if not closed and kind == 'code':
                return 'code evidence is premature while final plan stage is open'
            if not closed and kind is None and n > total:
                return 'untagged continuous evidence exceeds open final plan endpoint'
    if not closed:
        previous = endpoints[-2] if len(stages) > 1 else 0
        plan_max = max((n for s in subjects for n, kind in _staged_hits(s, total)
                        if kind != 'code'), default=0)
        if plan_max - previous >= UNPHASED_FAIL_ROUND:
            return 'HARD CAP: open final plan stage reaches its third non-clean round'
    else:
        code_max = _stage_round_max(subjects, total)
        if code_max > UNPHASED_FAIL_ROUND or (
                code_max == UNPHASED_FAIL_ROUND and target.get('audit_clean') is not True):
            return f'HARD CAP: code round {code_max}'
    return None


def _stage_round_max(subjects: list[str], plan_rounds: int) -> int:
    """The highest CODE-stage round these subjects reach, once the plan stage
    closed at `plan_rounds`, with stages as `_staged_hits` reads them: a code
    round is its own number; a continuous one ("round 4" in "round 4 (code
    round 1)", or a subject naming no stage) is N - plan_rounds; a plan round
    is not a code round at all.

    THE ACCEPTED COST: a subject with no "code" in it that numbers a code
    round from 1 ("H round 3 not clean", or "H round 3 -- off the plan",
    meaning code round 3) reads `plan_rounds` too low, or not at all. Name the stage in subjects -- the canonical
    `docs(state): <ID> code round N` does.
    """
    best = 0
    for subject in subjects:
        for n, stage in _staged_hits(subject, plan_rounds):
            if stage == "code":
                best = max(best, n)
            elif stage is None:
                best = max(best, n - plan_rounds)
    return best


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
    against the count declared by whatever `active_phase` points at -- over the
    span since that target's entry was INTRODUCED, not the whole branch (round 1
    finding 2: a branch carrying two pieces otherwise answers for the earlier
    one's round numbers). The pointer itself no longer scopes anything; see
    `_target_scoped_base`. Scoping to
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
    base_ref, base_detail = _resolve_base_ref()
    if base_ref is None:
        # ROUND 1 FINDING 1. This returned None, and None renders as "No drift"
        # -- a clean bill for a check that never ran, which is the same
        # observable the base-ref fix exists to remove. Say it could not look.
        # WARN, not drift: git being unavailable is not evidence of anything,
        # and a red banner for it would train the reader to scroll past the
        # real ones.
        return "warn", (
            f"Audit bookkeeping COULD NOT RUN: {base_detail}. This is the only "
            f"check here that reads git rather than a code symbol, so "
            f"audit_rounds/audit_clean were not verified against anything on "
            f"this run. That is an UNCHECKED bill, not a clean one."
        )

    identity = _target_identity(state)
    active_phase = identity[1] if identity and identity[0] == "phase" else None
    known_phase_ids = {
        phase["id"] for phase in state.get("phases", [])
        if isinstance(phase, dict) and isinstance(phase.get("id"), str)
    }
    evidence = _round_numbers_in_branch_subjects(
        _target_scoped_base(base_ref, state), base_ref,
        active_phase=active_phase, known_phase_ids=known_phase_ids,
    )
    if evidence is _GIT_FAILED:
        # P6 D1. The base ref resolved, then `git log` over it failed (e.g. the
        # ref vanished in between). Same tier and reason as the unresolved-base
        # branch above: an unchecked bill is not a clean one.
        return "warn", (
            "Audit bookkeeping COULD NOT RUN: `git log` over the resolved base "
            f"'{base_ref}' failed. audit_rounds/audit_clean were not verified "
            "against anything on this run. That is an UNCHECKED bill, not a clean one."
        )
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

    # P6 D2: a hand-edited string must not become a TypeError inside the
    # SessionStart hook. A whole number in any spelling JSON allows (3, 3.0,
    # "3") is read as that number. Anything else is None: it cannot be
    # compared, so the undercount check is skipped -- but the HARD CAP below
    # never reads `declared` and still runs (code round 6: an early warn here
    # turned a round-5, not-clean breach into exit 0). Only after the cap does
    # a non-numeric count get its warning. Deliberately ONE cap check, not a
    # copy here: STATE-PROBE-TARGET-SCOPING's verify pattern anchors on it.
    raw = target.get("audit_rounds")
    declared = _whole_number(raw)
    if declared is not None and git_max > declared:
        return "drift", (
            f"Audit bookkeeping: this branch's commit subjects reach round {git_max}, but "
            f"{label} -- the active target -- declares {declared}. "
            f"A round ran and was never written down — subjects: {shown}"
        )

    if 'plan_stages' in target:
        reason = _plan_stages(target, _target_identity(state)[1], declared, state, subjects)
        return ('drift', f'Audit bookkeeping: {label}: invalid plan_stages: {reason}. Subjects: {shown}') if reason else None

    # THE HARD CAP ON THE RESOLVED PATH. It used to live only in the `target is
    # None` branch above, which made it effectively OPT-OUT: once a pointer
    # resolved and the declared count kept up with the evidence, this function
    # returned None at ANY round count, so a piece could run 3, 8 or 30 rounds
    # without going clean and the script said "No drift" throughout. Worse, the
    # unphased message's own printed remedy -- point active_phase at the entry
    # and record the count there -- is precisely the move from the branch that
    # escalates to the branch that could not. Following the instruction turned
    # the check off. Phase D's thirteen rounds would never have tripped it.
    #
    # READ OFF `git_max`, NOT `declared`. Gating on the self-reported total was
    # the first version and it made the banner unclearable, which is round 4
    # finding 6's rule broken by the block that cites it: a piece past three
    # unclean rounds whose work cannot yet merge had no truthful way back --
    # going clean is only honest when it IS clean, lowering the count trips the
    # undercount check, and re-pointing moves the complaint rather than
    # answering it. Worse, it re-fired forever on work whose cap had already
    # been escalated to Kenneth and merged, and it fired on a stale pointer
    # left at a finished piece. Counting what THIS BRANCH still carries keeps
    # the signal where the unfinished rounds are, and merging empties the range
    # exactly as it does for the unphased banner above.
    #
    # IT CLEARS THE TWO WAYS THE UNPHASED BANNER DOES, which is what keeps it
    # inside round 4 finding 6's rule that a red banner nobody can clear is
    # worse than no banner: go clean (the honest end of an audit), or merge,
    # after which the range is empty, `evidence` is None and this never runs.
    # Acknowledging it is deliberately NOT a third route -- an acknowledgement
    # flag would be one more editable field that switches the check off, which
    # is the exact shape of the three findings the scoping rework just closed.
    #
    # `is not True`, not `not ...` (STATE-PROBE-FIXES, G4): the string "false"
    # is truthy, so a hand-typed quote switched the cap off.
    #
    # COUNTED PER STAGE (STATE-PER-STAGE-CAP): once a target's `plan_stage`
    # holds, `stage_max` is its code stage's round, not the continuous one --
    # see `_plan_stage` for why that field cannot switch the cap off.
    plan_rounds, plan_note = _plan_stage(
        target, _target_identity(state)[1], declared, state, subjects,
    )
    stage = "" if plan_rounds is None else (
        f" -- code round {_stage_round_max(subjects, plan_rounds)}, its plan stage "
        f"having closed at round {plan_rounds} ({target['plan_stage']['closed_by']})"
    )
    stage_max = git_max if plan_rounds is None else _stage_round_max(subjects, plan_rounds)
    if stage_max >= UNPHASED_FAIL_ROUND and target.get("audit_clean") is not True:
        return "drift", (
            f"Audit bookkeeping: {label} -- the active target -- declares {declared} "
            f"round(s), NONE of them clean, and this branch still carries round "
            f"{git_max}{stage}. audit_rule's HARD CAP is {UNPHASED_FAIL_ROUND} per stage: "
            f"STOP AUDITING AND TELL KENNETH -- that is evidence the batch is too big to "
            f"audit, not that it needs another round. Clears by going clean, by merging, "
            f"or by moving active_phase if it is pointing at finished work."
            f"{' ' + plan_note if plan_note else ''} Subjects: {shown}"
        )
    if plan_note:
        return "warn", f"Audit bookkeeping: {label}'s {plan_note}"

    if declared is None:
        return "warn", (
            f"Audit bookkeeping: {label} has audit_rounds={raw!r}, which is not a "
            f"whole number, so the round count was NOT checked against git "
            f"(this branch reaches round {git_max}). Fix the field."
        )
    return None


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
        declared_built = ph["status"] in BUILT_STATUSES
        code_built, detail = probe(ph["verify"])

        # `probe` already returns "does the code for this exist?" for every
        # kind, "absent" and "defect_marker" included. There is nothing left to
        # branch on here.
        actual_built = code_built

        if declared_built != actual_built:
            drift.append(
                f"Phase {ph['id']} ({ph['name']}): declared '{ph['status']}' but the code says "
                f"{'BUILT' if actual_built else 'NOT BUILT'} — {detail}"
            )

        # `is True` (G4): the string "false" is truthy and rendered "clean after N".
        rounds, clean = ph["audit_rounds"], ph["audit_clean"] is True
        if declared_built and not clean:
            unaudited.append(f"Phase {ph['id']} ({ph['name']}) — {rounds} round(s) run, none clean")

        if not quiet:
            colour, label = STATUS_STYLE.get(ph["status"], ("", ph["status"]))
            if clean:
                audit = f"{GREEN}clean after {rounds}{RESET}"
            elif rounds:
                audit = f"{RED}{rounds} run, NOT clean{RESET}"
            elif declared_built:
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
        if item.get("audit_clean") is not True:
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
            code_built, detail = probe(v)
            if not code_built:
                drift.append(
                    f"Shipped item '{item['name']}': declared shipped but the code "
                    f"says NOT BUILT — {detail}"
                )

    bookkeeping = audit_bookkeeping_drift(state)
    if bookkeeping:
        severity, message = bookkeeping
        # "drift" joins the red block and exits non-zero; "warn" joins the
        # yellow UNAUDITED block and exits 0. Both blocks print even under
        # --quiet, so a bookkeeping warning survives the one caller that passes
        # it. (The SessionStart hook does NOT: it runs the full render. An
        # earlier version of this comment said otherwise -- round 1 caught it.)
        (drift if severity == "drift" else unaudited).append(message)

    if not quiet:
        print(f"\n  {DIM}BUILT = code exists, unmerged; audit status is shown separately.{RESET}")
        print(f"  {DIM}SHIPPED* = legacy code-exists status without a clean adversarial round.{RESET}")
        if shipped_items:
            print(f"\n  {BOLD}{'':<2} {'ALREADY SHIPPED':<42} {'STATUS':<13} {'AUDIT':<22}{RESET}")
            for item in shipped_items:
                clean = item.get("audit_clean") is True
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
