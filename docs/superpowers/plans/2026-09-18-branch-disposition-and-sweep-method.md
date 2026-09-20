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
