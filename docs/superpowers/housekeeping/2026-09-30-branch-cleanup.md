# Remote branch cleanup, verified 2026-09-30 (WP0-HOUSEKEEPING)

Claude sessions cannot delete remote branches: the session git proxy only allows
pushes to the session's own branch, and a delete attempt is cut off. So this list
is for Kenneth to run from a local clone. Every entry was checked against
`origin/main` at `599b9da2`. Every command below is guarded, so it deletes nothing
that changed after the check:

- **Section 1:** deletes a branch only if `main` still contains all of it.
- **Section 2:** each delete is pinned to the tip commit that was checked
  (`--force-with-lease`). If the branch moved since, the push is refused.

## 1. Fully merged: every commit is already in main (safe)

Branches whose tip is from 2026-09-30 are left out on purpose, because their
session may still be live: see section 3.

```bash
git fetch --prune origin
for b in \
  claude/auto-trader-direction-sizing-2026-09-18 \
  claude/blissful-maxwell-c8g4nk claude/bold-ride-7nf8wj claude/busy-wright-lntyc3 \
  claude/clever-planck-rpz8yh claude/composite-momentum-confirmations \
  claude/confident-volta-mja4lz claude/cool-allen-5ih4v0 claude/cool-heisenberg-6lsa3a \
  claude/docc-2-options-regime claude/docc-money-blocks claude/ecstatic-planck-qi9c39 \
  claude/exciting-wozniak-dqdqy8 claude/happy-planck-yu5e4b claude/hopeful-volta-ujru28 \
  claude/jolly-thompson-0q7paq claude/keen-ramanujan-3gwcnw claude/optimistic-wozniak-nwe8nz \
  claude/peaceful-ritchie-b59i77 claude/quirky-pasteur-r1kt0v \
  claude/session-recovery-version-o2vklp claude/session-retrieval-continuation-vf056m \
  claude/shortlist-rank-dte-floor claude/sleepy-gates-4084r7 claude/sweet-meitner-9q8hch \
  claude/wizardly-lovelace-cub58h claude/wizardly-ritchie-ndb5sg \
  claude/youthful-rubin-l0p9ed
do
  git rev-parse -q --verify "origin/$b" >/dev/null || { echo "GONE (already deleted): $b"; continue; }
  if git merge-base --is-ancestor "origin/$b" origin/main; then
    git push origin --delete "$b"
  else
    echo "SKIPPED (no longer fully in main): $b"
  fi
done
```

## 2. Superseded, with commits not in main (checked one by one)

These hold commits that `main` does not have, but the work was rebuilt elsewhere
or is otherwise dead. Ledger items that still apply to `main` were copied into
`main`'s ledger. Items superseded by `main`'s own rebuild were left behind on purpose,
and each row says which.

| Branch | Verified tip | Why it can go |
|---|---|---|
| `claude/eager-thompson-2jfen9` | `07dde683` | PR #22, closed 2026-09-30. `main` chose a different skill set in `5060e30b` (it removed K-quality-benchmark and k-trading-software-reviewer). This branch instead removes the four other repo skill copies, which `main` still has, and keeps the two `main` removed. None of it was adopted. |
| `claude/loving-mayer-sdyltu` | `153407e2` | Its only file, the A4g plan, is on main (113/127 lines identical); the ledger calls it a superseded copy. |
| `claude/dazzling-ride-0unofk` | `36220467` | Parallel A4f plan session that never merged; A4f shipped from `claude/wizardly-ritchie-ndb5sg`. Ledger: superseded copy. |
| `claude/guard-i-snapshot-decision-m50w6u` | `cefa4d47` | Ledger: superseded unmerged copy (piece B shipped as AUTOTRADE-PIECE-B-DIRECTION-RUNTIME-GUARD). |
| `claude/unclaimed-tasks-xb6tiz` | `c637e450` | Earlier WATCH-UNDELIVERED-EVENT-RESEND build (plan r4, 09-26); the phase was rebuilt and merged 09-27 from `claude/clever-planck-rpz8yh`. Its one finding that still applies to main (head-of-line blocking in the resend queue) is now an open question in `main`'s ledger. Its two decisions were superseded by `main`'s WATCH-RESEND-QUEUE-2026-09-27 and were not carried. |
| `claims-probe-tmp` | `197fb012` | One empty commit ("probe"), no files, no shared history with main. |
| `claude/order-booking-safety-7evlql` | `9c5c09b0` | Superseded stock save-first build (STOCK-SENDS shipped instead). Its round-3 C1/C2 findings, whose fixes never reached main, are now an open question in `PROJECT_STATE.json` (search `9c5c09b0`). Delete it after that open question is handled, if you want to keep its version of the fix to hand until then. |
| `claude/clever-goldberg-ssmf4z` | `d4c6db1d` | **Only after the WP0 PR is merged.** Its MEAS plan, runner, request bodies, phase, decisions and closed item are copied to main by that PR. |

```bash
git fetch --prune origin
del() {  # delete branch $1 only if it is still at the verified tip $2
  git push --force-with-lease="refs/heads/$1:$2" origin ":refs/heads/$1"
}
del claude/eager-thompson-2jfen9            07dde683c95f234cbdde0e4f6df25fb8746336a2
del claude/loving-mayer-sdyltu              153407e2df40ef642027bc3079ce6b20d27c1986
del claude/dazzling-ride-0unofk             36220467b1e93d656e08e601d9cfb91a5bb02cc2
del claude/guard-i-snapshot-decision-m50w6u cefa4d478dca5c642cf7438b9f730307faed742b
del claude/unclaimed-tasks-xb6tiz           c637e450ac3c6d7d2b5e1bdc9646c45c29c422ff
del claims-probe-tmp                        197fb012f6ca7a8699e2085e32fd525e0dc993c4
# after the C1/C2 open question is handled:
del claude/order-booking-safety-7evlql      9c5c09b0498c4cecece419c4a6bd47e45ca752c7
# after the WP0 PR is merged:
del claude/clever-goldberg-ssmf4z           d4c6db1dfa66c024e98b85466d64dd5689fa6d21
```

## 3. Keep, or later

- `archive/vf056m-round3-7753b743`, `archive/peaceful-ritchie-a5b-4796924`: archives, kept deliberately (ledger).
- `claims`: the task-claim ledger. Never delete.
- `ccr-2fe3aef8-jpt3lz`: live DOCC-4-CONFIG-HEALTH work (YAML-CONFIG-INTEGRITY slicing decision, DOCC-4 plan revisions); 7 unmerged commits at the check.
- `ccr-55258cbe-hpvjcf`, `claude/amazing-planck-b4033x` (tip `311f4adb`, the OPTIONS-SHORTLIST-RANK audit's merge of REGIME-SIZING-AUDIT), `claude/practical-dirac-ebenkq` (REGIME-SIZING-AUDIT, merged in #24), `claude/options-shortlist-rank-audit` (OPTIONS-SHORTLIST-RANK, merged at `599b9da2`), `claude/pensive-cori-we2hm6`: fully merged but touched today; once their sessions are done, add them to the section 1 loop and run it.
- `claude/q2-hardening-merged-a2wx5g`: **your call.** One commit of 2026-09-24 parallel-session launch briefs and an open-topic inventory (docs only, now historical; 1/168 lines on main).
