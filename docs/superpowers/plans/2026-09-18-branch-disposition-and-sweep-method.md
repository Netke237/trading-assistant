# Branch disposition, and how to sweep for unmerged work without getting it wrong

**Written 2026-09-18 against `main` at `73649c7c`.** Records the verified disposition of every
remote branch, and — more importantly — the METHOD, because this project has got this question
wrong six times and the answer rots while the method does not.

---

## 1. Why this document exists

`working_branch` in `PROJECT_STATE.json` has been wrong about which branches carry unmerged work
**six times**. Once it claimed two branches were "both fully on main" when neither was; deleting on
that claim would have discarded three fixes, one of them a live 1.5x position-sizing divergence on
a broker order. Twice on 2026-09-18 alone.

A field that is wrong six times is not a field people should trust. The fix is not a better
sentence in that field — it is to **re-derive the answer from git every time**, with a method that
does not lie. That method is §3. The current answer is §2, and it will go stale.

---

## 2. Verified disposition, 2026-09-18

> **RE-SWEPT 2026-09-20 against `main` at `e058e99f`. The table below still holds for the five
> branches it calls 'fully dealt with' — every count reproduced exactly. But it is WRONG about
> two branches it calls merged, and the sweep that produced it cannot be run in a fresh container
> without a step this document did not have. See §5 before acting on anything here.**

Every branch below was compared to `main` **file by file, by content hash**, not by commit count.

| Branch | `rev-list` says | Reality |
|---|---|---|
| `claude/session-continuation-docs-ne4h8w` | 0 | Merged at `fb085887`. |
| `claude/o4-auto-trade-books-a-position-2026-09-15` | 0 | Merged at `7a792bb7`, docs only. |
| `claude/session-retrieval-continuation-vf056m` | 0 | Reached main through `ne4h8w` as ancestors. |
| `claude/gracious-mayer-g738w8` | **22 ahead** | **Fully dealt with.** |
| `claude/journal-startup-exit-audit-q8aw8v` | **14 ahead** | **Fully dealt with.** |
| `claude/terminated-session-details-ozquzb` | **12 ahead** | **Fully dealt with.** |
| `claude/previous-session-token-limit-bgs1df` | **4 ahead** | **Fully dealt with.** |
| `worktree-agent-a070a8845cd9ddd2c` | **1 ahead** | **Fully dealt with.** |

### The evidence, per branch

**`gracious-mayer-g738w8`** — 9 of its 11 changed files are byte-identical on main.
`PROJECT_STATE.json` differs because main is far ahead. The remaining file,
`backend/scripts/run_bearish_tests.py`, holds the branch's **older** hardcoded six-file list;
main's version selects by keyword and its own docstring documents the hardcoded version as
"wrong on day one". Measured: main's `-k bearish` collects **122** tests, the branch's six files
collect **30**. Main is a strict superset.

**`journal-startup-exit-audit-q8aw8v`** — 2 of 2 changed files byte-identical.

**`worktree-agent-a070a8845cd9ddd2c`** — 1 of 1 byte-identical.

**`previous-session-token-limit-bgs1df`** — `indicator_compute.py` and
`test_indicator_vwap_session_anchor.py` byte-identical to main.

**`terminated-session-details-ozquzb`** — 11 of 18 identical; 5 files where main is ahead;
`frontend/lib/chartWS.ts` differs **only** by an em-dash where the branch has three hyphens,
inside two comments; and `PLAN_CHART_DEFERRED_FIXES.md`, the one file genuinely absent at its
original path, was **already rescued** on 2026-09-17 to
`docs/superpowers/plans/2026-08-27-chart-lookback-deferred-fixes.md` — byte-identical content plus
a 6-line rescue header (402 lines vs 396, the difference being exactly that header).

### Deletion status

**Deletion of the five is SAFE on the evidence above. IT HAS NOT BEEN DONE.** No remote branch was
deleted in producing this document. Deleting a remote branch is not something to do on a document's
say-so — re-run §3 at the moment you act, then delete.

---

## 3. The method — the part that does not go stale

### 3.1 Enumerate. Do not recall.

```bash
git fetch --all --prune
git branch -r --format='%(refname:short)' | grep -v 'origin/HEAD'
```

Sweeping the branch names you happen to remember is how five branches were missed on 2026-09-18.
**The tool enumerates; you do not.**

### 3.2 Commit counts overstate. So does `git cherry`.

This project **re-applies** fixes on fresh bases instead of cherry-picking. That changes the
patch-id, so a defect already fixed on main still counts as "ahead" under both
`git rev-list` and `git cherry`.

Proof: `main` carries **three separate commits** whose subject is verbatim
`fix(indicators): session-anchor VWAP so it no longer depends on loaded history`. A branch can sit
22 commits "ahead" and hold nothing main lacks.

**Never report a backlog from a commit count.**

### 3.3 Compare content, per file, from the merge-base

```bash
B=origin/<branch>
BASE=$(git merge-base main $B)
git diff --name-only $BASE $B | while read -r f; do
  if ! git cat-file -e "main:$f" 2>/dev/null; then
    echo "ABSENT FROM MAIN: $f"                      # the only true finding
  elif [ "$(git rev-parse "$B:$f")" = "$(git rev-parse "main:$f")" ]; then
    echo "identical:        $f"
  else
    echo "differs:          $f"                      # open it; direction matters
  fi
done
```

For each `differs`, decide **direction**: `git diff --numstat main:$f $B:$f` — more deletions than
additions means main is ahead. Then read the hunks. A file can differ by punctuation.

### 3.4 Test existence with `git cat-file -e`, never `git rev-parse`

```bash
git cat-file -e "main:$path" 2>/dev/null   # correct
```

`git rev-parse main:$path` **prints the unresolved path to stdout before exiting non-zero**, so

```bash
mh=$(git rev-parse "main:$f" 2>/dev/null || echo MISSING)   # WRONG
```

captures `"<path>\nMISSING"`, which never equals `MISSING`. On 2026-09-18 this reported
`absent from main: 0` while a 396-line document was genuinely absent. It was caught only because
the differing files were opened by hand.

### 3.5 A document that exists on exactly one branch is the real risk

Code gets re-applied; a plan written once does not. `PLAN_CHART_DEFERRED_FIXES.md` existed in
exactly one place on origin, on a branch slated for deletion. **Before deleting any branch, check
for files absent from main — §3.3's first case — and rescue them.** The rescue convention is the
one used on 2026-09-17: move it under `docs/superpowers/plans/` with the branch's own date, keep the
content byte-identical, and add a header saying where it came from and that the work shipped.

---

### 3.6 First, prove the clone can answer the question at all

```bash
git rev-parse --is-shallow-repository    # MUST print false
git fetch --unshallow --all              # if it prints true
```

**Added 2026-09-20, and it is the seventh way this question has been got wrong.** Claude Code
web containers clone SHALLOW. On 2026-09-20 the container held 217 commits of a 1905-commit
history, and `git merge-base main origin/<branch>` returned **the empty string** for four
branches — no error, no message, exit status ignored inside a `$(...)`. §3.3's `BASE` was then
empty, `git diff --name-only "" $B` silently became a diff against the WORKING TREE, and the
sweep reported 311, 402, 405 and 449 phantom `differs` on branches whose real answer is 0 or 2.

It fails in the dangerous direction: it INVENTS a backlog rather than hiding one, so it does not
risk a bad deletion — but it makes the sweep useless exactly when someone is trying to clean up,
and an operator who trusted it would conclude five settled branches were full of unmerged work.
The tell is a count in the hundreds where §2 recorded single digits. `git fetch --unshallow`
took under a minute here and restored 1688 commits; after it, every number in §2 reproduced.

**Guard the base explicitly — an empty `BASE` must stop the sweep, not run it:**

```bash
BASE=$(git merge-base origin/main $B 2>/dev/null)
[ -z "$BASE" ] && { echo "!! NO MERGE BASE: $B (cannot sweep)"; continue; }
```

---

## 4. Checklist before deleting any branch

1. `git fetch --all --prune`, then **enumerate** `git branch -r`.
2. Run §3.3 for the branch. Resolve every `differs` by reading it.
3. Confirm **zero** `ABSENT FROM MAIN`, or rescue each per §3.5.
4. Only then delete — and record it here, with the date and the evidence.

---

## 5. Re-sweep, 2026-09-20, against `main` at `e058e99f`

Run after `git fetch --unshallow` (see §3.6), by content, per file, from the merge-base.

### 5.1 The five "fully dealt with" branches are still fully dealt with

Every count in §2 reproduced exactly: `gracious-mayer-g738w8` 22 ahead / 9 identical / 2 differs,
`journal-startup-exit-audit-q8aw8v` 14 / 2 / 0, `previous-session-token-limit-bgs1df` 4 / 8 / 5,
`terminated-session-details-ozquzb` 12 / 11 / 6, `worktree-agent-a070a8845cd9ddd2c` 1 / 1 / 0.
`PLAN_CHART_DEFERRED_FIXES.md` is still the only file absent from main on `ozquzb`, and is still
already rescued. **No new finding. Deletion of the five remains SAFE on the evidence, and still
has not been done.**

### 5.2 §2 IS WRONG ABOUT TWO BRANCHES, AND THIS IS A RESCUE CASE

> **UNDERSTATED. SUPERSEDED BY §6, WRITTEN HOURS LATER THE SAME DAY.** What this section calls
> two orphan files is the visible corner of 24 unmerged commits. Read §6 first.

§2 records `session-continuation-docs-ne4h8w` as "Merged at `fb085887`" and
`session-retrieval-continuation-vf056m` as "Reached main through `ne4h8w` as ancestors". Both
were true of the merge. **Both branches then kept being worked on**, and each now carries five
files absent from main. Three of the five (the `2026-09-18-{auto-trader-direction-sizing-plan,
B-armed-strategy-runtime-validation,C-state-py-gates-for-split-audit-loops}.md` plans) are carried
forward on the live sizing branch at NEWER blobs, so they are safe. **Two are not:**

| File | On | Absent from |
|---|---|---|
| `backend/tests/test_short_suite_arg_merging.py` | `ne4h8w`, `vf056m` only | main AND the live branch |
| `docs/superpowers/plans/2026-09-18-vf056m-restart-and-dead-container.md` | `ne4h8w`, `vf056m` only | main AND the live branch |

These are §3.5's exact risk case — a test and a document that exist on no other ref. **Rescue
both before either branch is deleted.** Neither branch was on the deletion list, which is the
only reason this has not already cost anything.

### 5.3 `archive/vf056m-round3-7753b743` — leave it

Not in §2's table. One commit ahead, seven files differing, **zero absent from main**. It is a
deliberate snapshot of the screener-layout work at its unclean round 3; main carries the round-4
clean version that merged at `fb085887`, and is ahead on every differing file. Its name says
`archive/`. It is preserved history, not a backlog. Not a deletion candidate.

---

## 6. CORRECTION, 2026-09-20 — §5.2 understated this badly

**This is the eighth wrong answer to this question, and the first one produced by skipping a step
this very document prescribes.** §5.2 was written after checking only the first case of §3.3 —
files ABSENT from main. §3.3's second half says: *"For each `differs`, decide direction."* That
was not done. Doing it changes the answer from "two orphan files to rescue" to "a branch whose
unmerged work main does not have".

### 6.1 What is actually unmerged

```
git rev-list --left-right --count origin/main...origin/claude/session-continuation-docs-ne4h8w
0       24
git diff --shortstat origin/main origin/claude/session-continuation-docs-ne4h8w
11 files changed, 2907 insertions(+), 88 deletions(-)
```

**`origin/main` is a STRICT ANCESTOR of `ne4h8w`.** The branch is main plus 24 commits. It is not
"merged with a bit of drift"; it is a superset. `fb085887` *is* an ancestor of it — the merge §2
records really happened — and then **the branch kept being worked on for 24 more commits that
never came back.**

**`vf056m` is FULLY CONTAINED in `ne4h8w`** (`rev-list --left-right` reads `0 8`). There is one
branch to deal with here, not two.

### 6.2 The files, by line count — not by numstat

| File | main | `ne4h8w` |
|---|---|---|
| `frontend/app/(frame)/screener/step-5-vol-events/page.tsx` | 389 | **737** |
| `frontend/app/(frame)/screener/step-5-vol-events/__tests__/gateSummary.test.tsx` | 299 | **1495** |
| `backend/scripts/run_bearish_tests.py` | 62 | **231** |
| `frontend/components/molecules/TableRow/index.tsx` | 65 | **73** |
| `backend/tests/test_short_suite_arg_merging.py` | *absent* | **286** |
| `docs/superpowers/plans/2026-09-18-vf056m-restart-and-dead-container.md` | *absent* | present |

Only `PROJECT_STATE.json` and the three `2026-09-18-*` plan docs also exist on the live sizing
branch. **The seven other files are on `ne4h8w` alone.**

### 6.3 The orphan test is orphaned from its IMPLEMENTATION, not just from main

`test_short_suite_arg_merging.py` imports `build_args`, `build_cmd` and `KeywordArgError` from
`scripts/run_bearish_tests.py`, at module scope. **None of those three exist on main's 62-line
copy of that script** (only `BEARISH_EXPR` does). Copying the test across on its own produces an
AttributeError at collection. The script's whole hand-rolled argument parser — the thing the test
exists to pin, after three separate defects each of which silently ran 51 tests instead of 6 and
exited 0 — is part of the same unmerged 169 lines.

### 6.4 The 24 commits are not scratch work

They carry completed adversarial rounds with recorded verdicts, including `Target B round 3:
CLEAN at the gate` and `Target A hit the cap: three rounds, none clean, stopping per decisions[0]`
— i.e. both outcomes this project's audit rule defines, already paid for. Deleting `ne4h8w` would
discard those rounds along with the code.

### 6.5 What this changes

1. **`ne4h8w` and `vf056m` are NOT deletion candidates and must not be treated as merged.** §2
   says both are done. Both claims are stale in the direction that loses work.
2. **This is a MERGE decision, not a rescue.** Copying two files would leave ~2900 lines and a
   broken import behind. The question for Kenneth is whether `ne4h8w` merges to main — and since
   main is a strict ancestor, that merge is a fast-forward-shaped `--no-ff`, not a conflict
   resolution.
3. **The five branches in §5.1 are unaffected.** Their content re-verified clean, and none of them
   is `ne4h8w` or `vf056m`.
4. **Method:** §3.3's direction check is not optional, and a `differs` on a PRODUCTION file is the
   one to open first. A count of ABSENT files alone will report a clean sweep over a branch that
   is 2907 insertions ahead.

---

## 7. Re-sweep, 2026-09-20 (second of the day, AFTER the ne4h8w merge)

Run on an unshallowed clone with the empty-`BASE` guard (§3.6), against `main` at `2e9084ba`,
resolving DIRECTION on every `differs` as §3.3 requires — the step §5 skipped and §6 corrected.

### 7.1 §6 IS NOW CLOSED. Nothing is stranded anywhere.

`claude/session-continuation-docs-ne4h8w` and `claude/session-retrieval-continuation-vf056m`
both read **ahead=0, differs=0, ABSENT=0**. The `bff42997` merge landed all 24 commits, and the
two files §5.2 flagged as existing on no other ref — `backend/tests/test_short_suite_arg_merging.py`
and `docs/superpowers/plans/2026-09-18-vf056m-restart-and-dead-container.md` — are on main. **The
rescue requirement is discharged. It was never actioned as a rescue; the merge did it.**

### 7.2 One branch carries every unmerged line

| Branch | ahead | Verdict |
|---|---|---|
| `claude/session-recovery-version-o2vklp` | 39 | **The live branch.** All unmerged work. |
| `claude/auto-trader-direction-sizing-2026-09-18` | 26 | **Fully contained in the live branch** (`merge-base --is-ancestor` true). Nothing unique. |
| `claude/session-continuation-docs-ne4h8w` | 0 | Merged at `bff42997`. |
| `claude/session-retrieval-continuation-vf056m` | 0 | Merged at `bff42997`. |
| `claude/o4-auto-trade-books-a-position-2026-09-15` | 0 | Merged. |
| `claude/gracious-mayer-g738w8` | 22 | Dealt with. No file where the branch is ahead. |
| `claude/journal-startup-exit-audit-q8aw8v` | 14 | Dealt with. 2 of 2 identical. |
| `claude/previous-session-token-limit-bgs1df` | 4 | Dealt with. No file where the branch is ahead. |
| `claude/terminated-session-details-ozquzb` | 12 | Dealt with. Only `PLAN_CHART_DEFERRED_FIXES.md` absent, already rescued 2026-09-17. |
| `worktree-agent-a070a8845cd9ddd2c` | 1 | Dealt with. 1 of 1 identical. |
| `archive/vf056m-round3-7753b743` | 1 | Deliberate archive; main ahead on all 7 differing files. |

**Deletion is SAFE on this evidence for all of: `ne4h8w`, `vf056m`, `o4-auto-trade-books-a-position`,
`gracious-mayer-g738w8`, `journal-startup-exit-audit-q8aw8v`, `previous-session-token-limit-bgs1df`,
`terminated-session-details-ozquzb`, `worktree-agent-a070a8845cd9ddd2c`, and
`auto-trader-direction-sizing-2026-09-18`** (the last only because the live branch contains it —
delete it and the live branch still holds every line). NOTHING HAS BEEN DELETED. Kenneth decides,
and §4's checklist is re-run at the moment of acting. Keep `archive/` and the live branch.

### 7.3 The bearish scan material is already on main

`docs/superpowers/measurements/scans/2026-09-18/` holds eight request/result pairs (SP500 Position
bullish+bearish options, and stocks SP500 Swing+Position bullish+bearish), and
`docs/superpowers/measurements/scan-funnel.jsonl` holds 6 rows. On main since `e058e99f`. Nothing
to sync. This container's local `main` is byte-identical to `origin/main` (`0 0`).

---

## 8. DELETED 2026-09-20 — the first deletions this project has ever performed

**Kenneth ran them from his own machine against `origin/main` at `2e9084ba`, after §4's checklist
was re-run the same hour** (§7). Eight remote branches, one `git push origin --delete`:

```
 - [deleted]  claude/gracious-mayer-g738w8
 - [deleted]  claude/journal-startup-exit-audit-q8aw8v
 - [deleted]  claude/o4-auto-trade-books-a-position-2026-09-15
 - [deleted]  claude/previous-session-token-limit-bgs1df
 - [deleted]  claude/session-continuation-docs-ne4h8w
 - [deleted]  claude/session-retrieval-continuation-vf056m
 - [deleted]  claude/terminated-session-details-ozquzb
 - [deleted]  worktree-agent-a070a8845cd9ddd2c
```

### 8.1 The evidence each one was deleted on

`ne4h8w`, `vf056m` and `o4-auto-trade-books-a-position` read **ahead=0 / differs=0 / ABSENT=0**
against `origin/main` — fully merged, nothing to lose. The other five were "ahead" by commit count
and **fully dealt with by content**: zero files absent from main, and zero files where the branch
was ahead (direction resolved per §3.3, not assumed).

`terminated-session-details-ozquzb` was the one re-checked hardest, because it carried one file
absent from main. `PLAN_CHART_DEFERRED_FIXES.md` was rescued on 2026-09-17 to
`docs/superpowers/plans/2026-08-27-chart-lookback-deferred-fixes.md`, and that rescue was
**re-verified by diff at the moment of deleting**: 402 lines against the branch's 396, and the diff
is exactly the six-line rescue header. Content byte-identical.

### 8.2 What survived, and why

| Branch | Why kept |
|---|---|
| `claude/session-recovery-version-o2vklp` | **The live branch.** 41 commits ahead of main. Every unmerged line. |
| `claude/auto-trader-direction-sizing-2026-09-18` | Safe to delete (the live branch contains all 26 of its commits, re-verified) but **deliberately kept as a second copy** until the live branch merges. Its content is not on main. Delete it in the same session that merges. |
| `archive/vf056m-round3-7753b743` | Deliberate archive of an unclean round; main is ahead on all seven differing files. |

### 8.3 The local sync that preceded it

Kenneth's local `main` was at `e058e99f`, 26 behind. `git rev-list --left-right --count
main...origin/main` read `0 26` — **left 0, so no local-only commits** — and the fast-forward was
clean: 11 files, 2911 insertions, 92 deletions. An uncommitted local edit to
`backend/config/strategy_watches.yaml` was checked first and survived untouched, because none of
the 26 incoming commits touch that file and it is byte-identical at both ends.

**Run §3.6 and §4 again before the next deletion. This section is the answer for 2026-09-20 only.**
