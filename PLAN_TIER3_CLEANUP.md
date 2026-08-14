# Implementation Plan — Tier 3: Mechanical Cleanup & Hardening

Status: REVISED after adversarial review round 1. Three items had severity-5 findings: #2 rested
on a false "no existing token" premise (one already exists) and undercounted affected files ~2x;
#3's original recommendation risked a real data-loss bug (silently dropping a placed order on a
network hiccup); #7 targeted the wrong file — the actual unattended nightly cron path is a
different, undocumented duplicate script that was left completely unprotected. All three revised
below.

Scope: findings #11, #12, #13, #14, #25, #26, #27, #28, #29, plus two deferred residual notes from
`SELL_CLOSE_SEMANTICS_PLAN.md` (Tradier `sell_short` margin caveat, IBKR/Alpaca auto-infer
verification).

---

## 1. Stale `settingsStore.ts` header comment (#11)

`frontend/lib/settingsStore.ts:4` — "Persists broker config, alertDeduplicationHours, and IV
thresholds." IV thresholds were removed in the v18 migration; they now live in
`ivThresholdsStore.ts`.

**Fix:** update the comment to accurately describe current contents. Read the store's actual
persisted fields (its `partialize`/state shape) rather than guessing, so the corrected comment is
itself accurate rather than just less-wrong.

---

## 2. Hardcoded `#fff` bypasses the CSS-token-only rule (#12)

**Round 1 review found the "no existing token" premise was false, and the file count was
undercounted by roughly 2x. Corrected below.**

A token for exactly this purpose already exists: `frontend/styles/tokens.css:51,112` defines
`--accent-text: #FFFFFF;` in both the dark (`:root`) and light (`[data-theme="light"]`) blocks,
already used 22 times across the codebase for white-text-on-solid-background. Confirming this
isn't a "different but similar" token: `RunScanButton/index.module.css` itself uses
`var(--accent-text)` at line 19 **and** a hardcoded `#fff` at line 128 in the same file — the
inconsistency is already present within one file, which is the strongest signal the fix is a
rename/reuse, not a new addition.

Also: `app/globals.css` is just 2 lines (`@import` of `styles/tokens.css` and `styles/reset.css`)
— the actual token definitions live in `frontend/styles/tokens.css`, not `app/globals.css`. Any
edit belongs there.

**Corrected file list** (round 1 review's fuller grep for `color: #fff` on a solid status/accent
background): the original 5 —
`NavItems.module.css:60`, `StepNavBar.module.css:98`, `RunScanButton/index.module.css:128`,
`ConfirmDialog.module.css:56`, `AlertBadge.module.css:12` — plus 6 more the original audit missed:
`step-7-position-card/page.module.css:18-19` (on `--pass`/`--caution`),
`step-7-trade-card/page.module.css:3-4` (same), `portfolio/page.module.css:379` (on `--reject`),
`AutoTradeArm/AutoTradeArm.module.css:9` (on `--caution`), and two on `--accent`:
`alerts/page.module.css:367`, `ClosePositionDrawer.module.css:11`. **11 sites total, not 5** —
fixing only the original 5 would leave the codebase with two competing idioms for the identical
purpose, arguably worse than the current single (if inconsistent) one.

**Fix:** replace all 11 hardcoded `color: #fff` occurrences with `var(--accent-text)` (reusing the
existing token — do not add a new one). If the name `--accent-text` reads awkwardly for some of
the new sites (e.g. text on `--reject`/`--pass`/`--caution`, not just `--accent`), consider
whether a rename to something more general like `--text-on-solid` is warranted — but that would
mean updating all 22 *existing* call sites too, which is a larger, purely-cosmetic rename with no
functional benefit; recommend keeping the existing `--accent-text` name and just extending its
usage, unless the implementer finds a concrete reason the current name is actively misleading.

**Test plan:** none needed (pure CSS token substitution, visually verify in both themes via the
dev server per CLAUDE.md's "test the golden path" guidance — a screenshot diff in light and dark
mode of the 11 affected components is sufficient).

---

## 3. Redundant double-POST on options paper-order placement (#13)

**Round 1 review found the original fix recommendation contained a real data-loss trap. Corrected
below — this is now the most important item in this tier.**

`frontend/app/(frame)/screener/step-7-trade-card/page.tsx:499,508` (line numbers corrected — not
498/507) — `persistPosition(pos)` POSTs the new position, then on success `addPosition(pos)` (from
`portfolioStore.ts`) independently POSTs the same position again via its own internal
`postPosition()` call. The second POST is swallowed as a harmless 409 today. **The identical
pattern is duplicated in `placeMarketNow` at lines ~533/542 — any fix must cover both, not just
`placeLimitPaper`.**

**Why the obvious fix ("skip `addPosition`'s POST since `persistPosition` already succeeded") is
unsafe:** `persistPosition`'s network-failure branch is deliberately lenient —
`catch { return { ok: true }; }` — it reports `ok: true` on a connection failure, i.e. it can
report "success" when *nothing was actually persisted*. The only thing currently catching that and
doing the right thing is `addPosition`'s own internal `postPosition()` call, whose
network-failure branch instead returns a `{kind: 'network'}` result, which `addPosition` turns
into `syncStatus: 'pending'` — a state `syncFromBackend`'s reconcile loop explicitly retries
(unit-tested: `portfolioStore.test.ts:554`). If a "skip re-POST when `saved.ok`" variant trusts
`persistPosition`'s optimistic `ok: true` on a network hiccup, the position gets inserted locally
as `syncStatus: 'synced'` despite never reaching the backend — and `syncFromBackend`'s own
reconcile logic treats a synced-but-absent-from-backend row as "a genuine phantom... drop it"
(~line 520). **That would silently delete a just-placed paper order from the user's portfolio on
a network hiccup** — the opposite of the intended fix, and the highest-consequence failure mode
in this entire tier.

**Corrected fix:** the skip-re-POST path must only trigger on a *genuine* successful response from
`persistPosition`, never on its offline-optimistic fallback. Two ways to make this safe:
- **(A)** Change `persistPosition` itself to stop conflating "offline" with "ok" — have its
  catch branch return a distinguishable result (e.g. `{ ok: false, offline: true }` or a
  `kind: 'network'` shape matching `addPosition`'s own internal convention) instead of
  `{ ok: true }`. Then only skip `addPosition`'s POST when `persistPosition` returns a real,
  confirmed-successful response — on the offline/network-failure case, still call `addPosition`
  normally (with its own POST) so the existing pending/retry path still engages exactly as it
  does today.
- **(B)** Simpler, smaller diff: leave `persistPosition` unchanged, and only skip `addPosition`'s
  internal POST when `persistPosition`'s result carries a real backend-confirmed identifier/field
  that only a genuine successful response would have (if one exists in the response shape) —
  distinguishing "really succeeded" from "optimistically assumed succeeded" without needing to
  change `persistPosition`'s return shape.

**Recommend (A)** — it fixes the ambiguity at its source rather than working around it at each
call site, and makes `persistPosition`'s return value trustworthy for any future caller too, not
just this one. Whichever is chosen, **do not ship a fix here without a test that specifically
simulates a network failure during `persistPosition` and asserts the position still ends up
`syncStatus: 'pending'` (retryable), not silently dropped** — this is the actual regression the
original "just skip the second POST" idea would have introduced, and the happy-path-only test the
original plan proposed would not have caught it.

**Test plan:**
1. Happy path: exactly one POST to the position-create endpoint per `placeLimitPaper`/
   `placeMarketNow` call (both call sites), not two.
2. **Regression-critical:** simulate a network failure in `persistPosition`'s call, confirm the
   resulting position is NOT marked `synced` and IS retried via the existing pending-sync path —
   proving the fix didn't reintroduce the data-loss failure mode described above.

---

## 4. Bare `except Exception: pass` spot-check (#14)

Several sites in `backend/app/data/market.py` and `backend/app/main.py` swallow `Exception`
broadly. The original audit found these "mostly documented as deliberate non-fatal fallbacks" —
this is a **spot-check item, not a confirmed bug list**. Two representative examples re-verified:
- `market.py` (Tradier token resolution) — swallows any exception while trying to read a
  paper-broker token override, falling back to the env-var token. Reasonable: a malformed
  credentials file shouldn't crash price fetching.
- `market.py` (day-list construction) — swallows any exception building a list comprehension,
  falling through to return nothing. Less obviously safe — worth checking what exception types are
  actually plausible here and whether silently returning empty vs. logging a warning is the right
  call.

**Fix approach:** for each of the ~7 flagged sites, do NOT reflexively narrow every
`except Exception` to something specific — that risks turning a deliberately-broad safety net into
a crash site if an unanticipated exception type occurs. Instead, for each site:
1. Confirm (via a comment, or by reasoning about the surrounding code) whether the *intent* is
   "swallow I/O/parsing failures, not logic bugs."
2. Where the intent is genuinely "swallow anything, never let this take down a request/startup,"
   add a one-line comment saying so explicitly (several already have this; a few don't) — this
   converts an ambiguous-looking bare except into a documented, deliberate one.
3. Where a site is swallowing exceptions in a code path that should probably surface programming
   errors (e.g., anything doing dict/attribute access on a data shape assumed-but-not-verified to
   be correct), consider narrowing to `except (KeyError, AttributeError, ValueError, TypeError)`
   *only* if confident that's the full plausible set — otherwise leave broad and just log at
   `logger.debug` or `logger.warning` instead of silently passing, so the failure is at least
   observable without changing behavior.

**This is a judgment-call item — flag any site where the right call isn't clear-cut for the
adversarial reviewer to weigh in on, rather than guessing.**

---

## 5. `/ws/alerts` has no authentication (#25)

`backend/app/routers/ws_alerts.py:12-38` accepts any WebSocket connection with no token/session
check, unlike `credential_store.py`'s explicit documented single-user-local-machine assumption
(lines 28-35 there).

**Fix — documentation, not a security fix, given the existing product assumption:** add a comment
at the top of `ws_alerts.py` (or on the route handler) explicitly stating the same
single-user-local-machine assumption `credential_store.py` documents, so this reads as a
deliberate, reviewed decision rather than an oversight. **Do not add authentication machinery**
(tokens, session cookies) unless the product's threat model is actually changing (e.g., the app is
being made reachable beyond localhost) — that would be a real feature/scope decision belonging to
the user, not something to add unprompted. If in doubt, ask before adding auth machinery here;
default to the documentation-only fix.

---

## 6. Credential file has no permission hardening (#26)

`backend/app/services/credential_store.py:71-79` (`save()`) writes `local_credentials.yaml`
(plaintext broker secrets) via `os.replace` with no `os.chmod(0o600)`.

**Fix:** add `os.chmod(tmp, 0o600)` before the `os.replace(tmp, self._path)` call (chmod the temp
file before the atomic rename — `os.replace` preserves the source inode's permission bits, so this
also fixes the final path's permissions going forward, confirmed by round 1 review). **Round 1
review caught that this alone doesn't cover a file that already exists from before this fix
shipped** (its permissions won't change until the next `save()` call, which may be a long time for
a file that's rarely re-saved) — also add a one-time `os.chmod(self._path, 0o600)` in `load()` (or
wherever the store is initialized) if `self._path.exists()`, so an already-broadly-permissioned
file gets tightened on the next app start, not just the next save:
```python
# in save():
tmp.write_text(yaml.dump(data_copy, default_flow_style=False))
os.chmod(tmp, 0o600)
os.replace(tmp, self._path)

# in load() or __init__, if self._path.exists():
os.chmod(self._path, 0o600)
```
Cross-platform note: `os.chmod` is a no-op-ish/best-effort on Windows (doesn't map cleanly to NTFS
ACLs) — check if this codebase has any Windows-dev-environment expectations (CLAUDE.md's dev
workflow only mentions `npm run dev`/`pytest`, no OS-specific guidance found) before assuming this
is purely beneficial with no downside; if Windows dev is a real target, note that this fix is
POSIX-effective only, not a false promise of protection there.

**Test plan:** a test that calls `save()` and asserts the resulting file's mode bits
(`oct(os.stat(path).st_mode)[-3:] == '600'`) — skip/guard the assertion on Windows if the test
suite runs there (check CI's `runs-on:` — currently `ubuntu-latest` per `ci.yml`, so this isn't
an immediate concern, but note it for completeness).

---

## 7. `update_sp500_liquidity.py` overwrites production config with no backup/dry-run (#27)

**Round 1 review found this item was targeting the wrong file — the actual unattended nightly
cron path is a separate, undocumented duplicate implementation that the original plan left
completely unprotected. Corrected below.**

`backend/scripts/update_sp500_liquidity.py:134-150` rewrites `backend/app/data/sp500.csv`
unconditionally — but this is a **standalone manual script**, not what actually runs unattended.
CLAUDE.md documents `sp500_scheduler.py` as the cron job that "updates sp500.csv via yfinance," and
that scheduler does **not** call this script — it calls
`backend/app/services/sp500_update_service.py`'s `start_update_task()` → `_run()`, a **separate,
duplicated implementation** (confirmed: `sp500_update_service.py:94-103`) with its own
unconditional CSV overwrite, no backup, no dry-run, no sanity threshold. That's the code path that
runs every night with nobody watching stdout — the higher-risk copy of this bug, not the manual
script (which at least has a human present who might notice bad output).

**Corrected fix — apply the same hardening to both, sharing logic rather than duplicating it a
third time:**
1. Given `sp500_update_service.py` and `update_sp500_liquidity.py` are already an undocumented
   duplication of the same fetch/write logic, consider (as a stretch goal, not required for this
   fix to be complete) whether `sp500_update_service.py`'s scheduled path should just call the
   script's logic directly instead of maintaining a parallel implementation — but don't let a
   larger refactor block shipping the safety fix; if consolidating them is too large a change for
   this pass, apply the same three protections (dry-run capability, backup, sanity threshold) to
   **both** files independently.
2. `update_sp500_liquidity.py` (manual script): as originally planned —
   `--dry-run` flag, pre-write backup (`shutil.copy2`), sanity threshold on the zero-liquidity
   fraction with a loud warning (and non-zero exit, gated behind `--force` to override).
3. `sp500_update_service.py` (the actual unattended nightly path — the more important half of this
   fix): add the pre-write backup and the sanity-threshold check as non-interactive safety nets
   (no `--dry-run` concept needed here since it's not invoked with CLI args, but the backup and
   the "don't write if liquidity data looks mostly-empty compared to before" check both apply
   directly, and matter more here since nobody's watching this path run).

**Scope guard:** this is still maintenance-script/scheduled-job hardening, not a rewrite — argparse
with 1-2 flags for the manual script, and a couple of defensive checks added to the service
function, not a new framework.

**Test plan:** if either file has existing test coverage, extend it. For `sp500_update_service.py`
specifically — since it's the actual unattended path — a test simulating a "yfinance returns
mostly-empty data" scenario and asserting the CSV is NOT overwritten (or is overwritten but a
warning is logged, per whichever behavior is chosen) is worth adding even if the manual script's
`--dry-run` flag doesn't get equivalent test coverage, since this is the path most likely to
actually run unattended and do damage.

---

## 8. Stale doc comment on `AlertConfig.keepAlertsDays` (#28)

`frontend/types/domain.ts:456` — comment says "default 10"; the real default
(`frontend/lib/alertStore.ts:28`) is `30`.

**Fix:** one-line comment correction: `// default 30 — auto-purge after N days`.

---

## 9. Redundant duplicate PRD file at repo root (#29)

`temp_prd.md` is a confirmed byte-for-byte duplicate of
`PRD-02 Master Phased PRD — Options Screener and Recommendation Assistant.md`.

**Fix:** delete `temp_prd.md`. Before doing so, grep the repo (including `llm-contexts/` and
`docs/superpowers/`) for any reference to the filename `temp_prd.md` specifically — if nothing
references it by name, it's safe to remove outright. This is folded into the doc cleanup in
`PLAN_TIER4_DOCS.md` for sequencing (it's a doc-tree change), but the underlying action is trivial
enough to do as its own tiny commit if easier.

---

## 10. Deferred residual notes from `SELL_CLOSE_SEMANTICS_PLAN.md` — verification tasks, not code
    changes

- **Tradier `sell_short` margin-account caveat:** no pre-flight check was added when the SELL/CLOSE
  fix shipped; `sell_short` may be rejected by Tradier for a cash account or a hard-to-borrow
  symbol. **Action:** confirm this is an acceptable, clearly-surfaced error today (does the
  existing generic `RuntimeError` → 502 propagation include Tradier's actual rejection reason in
  the response body, per `tradier_paper.py`'s error handling?) — if the broker's real rejection
  text reaches the frontend's `orderError` state (it should, per `step-7-position-card`'s existing
  `catch (e) { setError(String(e)) }` pattern), this may already be "good enough" without new code;
  confirm and document rather than assume more work is needed.
- **IBKR/Alpaca "auto-infers open vs. close from account state" assumption:** re-verify against
  each platform's actual API documentation (not just the existing code comments, which is what the
  original assumption was based on) — IBKR Client Portal API docs and Alpaca's trading API docs.
  If confirmed accurate, remove the "residual risk, unverified" language from
  `SELL_CLOSE_SEMANTICS_PLAN.md`'s §2.1 and replace with a confirmed citation. If NOT confirmed
  (i.e., either platform actually does need an explicit open/close qualifier in some scenario),
  this becomes a real follow-up bug fix, scoped separately — do not silently patch code based on
  a docs-reading without also adding adapter-level tests proving the corrected behavior, matching
  the rigor the original SELL_CLOSE work used for Tradier/Tastytrade.

---

## Sequencing

Independent items, no ordering dependency. Suggested order by effort: #8, #1 (both one-line doc
comments) → #9 (file deletion) → #6 (chmod) → #2 (CSS token) → #5 (doc-only) → #3 (needs the
`persistPosition`/`addPosition` investigation) → #7 (script hardening) → #4 (judgment-call spot
check, do last since it may turn up sub-items needing their own follow-up) → #10 (verification
tasks, can run in parallel with anything else since they're read-only investigation plus maybe a
doc update).
