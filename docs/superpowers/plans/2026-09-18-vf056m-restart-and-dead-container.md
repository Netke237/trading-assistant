# `vf056m` restarted from main, and a container that died before it pushed

**Date:** 2026-09-18
**Branch:** `claude/session-retrieval-continuation-vf056m`, restarted at `origin/main` (`4b131f25`)
**Discarded tip:** `7753b743d7b116d688c88c93c741b0535b7b4175`
**Preserved at:** `origin/archive/vf056m-round3-7753b743`
**Session:** `session_01M9RYB89DoQy13t2dW8LANC`

This file exists so that three things nobody can reconstruct from `git log`
are on the record: a container's work that never reached git, a branch tip
that a restart removed from a ref, and the one line of that tip worth keeping.

---

## 1. A container took the sizing handoff and died before pushing anything

A session on 2026-09-18, in a container other than the one that wrote this,
was handed the Piece A handoff (implement on a fresh branch cut from `main`).
It oriented, ran `git checkout -B`, and hit its usage limit. Its last visible
state showed a `+615 −3` working-tree diff.

**Nothing from it reached git, and the diff is not recoverable.** The evidence
is an absence, so it is worth stating how the absence was established rather
than asserting it:

```
git fetch origin
for b in $(git for-each-ref --format='%(refname)' refs/remotes/origin); do
    printf "%s  %s\n" "$(git log -1 --format=%ci $b)" "$b"
done | sort -r | head -3
```

The newest commit on any remote ref was `bf0f222d` at **13:17 UTC** — the
previous session's own last commit, the one the handoff was written from. The
dead container ran afterwards and moved nothing. A container-local working
tree is reclaimed with the container.

What is testimony and what is repo evidence, kept apart deliberately: the
`+615 −3` figure and the timing are **testimony** (a screenshot of that
session's last message). The absence from every remote ref is **repo
evidence**. Do not go looking for that work. It was two tool calls of setup,
and this branch redoes it.

## 2. `vf056m` had already forked the audit loop the supersede note warned about

`docs/superpowers/plans/2026-09-18-session-handoff-vf056m-to-ne4h8w.md`, on
main since `2c6c6c3c` (06:01 UTC), records this branch as SUPERSEDED and tells
any session resuming on it to stop, because continuing it forks the
adversarial-audit loop mid-round.

**It forked anyway.** `7753b743` ("Round 3 findings, and the cap") was pushed
to `vf056m` at 09:02 UTC — three hours after that note — while
`claude/session-continuation-docs-ne4h8w` ran its own round 3 (`3dc14b4f`) and
reached a clean round 4 (`caeabb9c`), which merged to main. Both branches
audited the same Step-5 gate work in parallel, which is exactly the failure
mode `working_branch` records twice.

Main won, and should have: main carries the **round-4-clean** `statusTooltips.ts`,
`gateDrivers` and the `hasIv`/`ivGated` pair; `7753b743` carries the
round-3-unclean version of the same files. Rebasing that tip onto main would
have regressed clean work, so this restart does not rebase it.

## 3. What was salvaged from the discarded tip, and what was not

`git cherry -v origin/main origin/claude/session-retrieval-continuation-vf056m`
reported exactly one unmerged commit, `7753b743`. Its frontend content is
superseded per §2. One hunk was **not** superseded and is carried forward here:

`backend/scripts/run_bearish_tests.py` accepted `-k EXPR` and `-k=EXPR` but not
the bare attached `-kEXPR`, which pytest honours. The attached form fell
through to `rest`, landed *after* the script's own `-k`, and pytest's last-wins
rule dropped the bearish filter entirely — so `run_bearish_tests.py -kstructural`
ran the whole repo's structural suite, bullish tests included, under a script
whose name promises the opposite. Measured on main's version before porting:

```
['-k', 'structural']  ->  (bearish) and (structural)
['-k=structural']     ->  (bearish) and (structural)
['-kstructural']      ->  bearish          # + '-kstructural' appended after it
```

and after the port, all three narrow to `(bearish) and (structural)`.

`7753b743` is no longer reachable from `vf056m`, and it is **not** left to a
written-down sha and the remote's willingness not to collect it. Before the
restart was pushed, the commit was pushed to its own ref:

```
git fetch origin && git log --oneline -1 origin/archive/vf056m-round3-7753b743
```

That ref exists to hold one commit and nothing else. Do not build on it, do not
merge it, and do not delete it to tidy up — its whole job is to keep an object
reachable that a reader may one day want to diff against. This is the same
posture the supersede note took, carried one step further: *merged* is a
property of commits, not of a branch name, and neither is *kept*.

## 4. Why the restart was from `main`, and what it bought

Piece C's option 1 — cut the code loop from `main` so `git_max` starts at zero
— was the reason, and it is now **measured, not assumed**. `state.py` reads the
highest `round N` in this branch's commit *subjects* measured against a base
ref asked of git. A branch cut at `origin/main` has no such subjects.

With the three Piece A/B/C plan docs and the corrected `PROJECT_STATE.json`
ported from `claude/auto-trader-direction-sizing-2026-09-18` (unmerged; the
plans live nowhere else), `python3 scripts/state.py` **exits 0** on this
branch. The hard cap that fired at `bf0f222d` does not follow the plan across.

This does not settle Piece C. It settles its first question only: a piece can
enter a fresh code-audit loop without inheriting the plan loop's rounds. How
Piece A satisfies its own §4 on the way *out* is still open.

## 5. Still true, and still open

- The live defect is untouched, but THIS NOTE ORIGINALLY NAMED THE WRONG
  BRANCH and the correction is the whole point of the sizing piece. Read
  `2026-09-18-auto-trader-direction-sizing-plan.md` §1.1 and §1.2, and
  `PROJECT_STATE.json`'s `pending_kenneth[1]`, not the sentence this bullet
  used to carry.
  - RETRACTED: "`auto_trader.py:176` mirrors bearish conviction as
    `100 - conviction` on a signed scale". The arithmetic is wrong, but it sits
    on the SELL branch, and `strategy.action` is `"BUY"` for every armed trade
    -- `AutoTradeArm/index.tsx:207` is the only production caller of
    `armAutoTrade` and hardcodes it (correctly: a bearish trade here is a LONG
    PUT, which is buy-to-open), and `routers/auto_trade.py:83` is the only
    production call site of `auto_trader.arm`. So that branch is unreachable
    from the UI and "fixing" it would change no live trade while appearing to
    close the bug.
  - STANDS: the BUY branch feeds the signed conviction straight into
    `conviction_mult`, so a bearish arm is sized on a negative conviction. It
    reaches live broker order sizes and bites from armed quantity 2 upward; at
    qty 1 -- common for a single-leg option arm -- it has no effect at all.
- Pieces B and C remain open questions, in their own files.
- `claude/auto-trader-direction-sizing-2026-09-18` is unmerged and is the only
  place the plan's round-by-round history exists. Do not delete it.
