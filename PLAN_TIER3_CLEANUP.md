# Implementation Plan — Tier 3: Mechanical Cleanup & Hardening

Status: DRAFT — pending adversarial review (lighter rigor than Tiers 1-2; these are low-blast-radius
items, but still deserve one adversarial pass since several touch security-adjacent code).

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

Five files hardcode `color: #fff` for white text on solid status-color backgrounds (buttons/badges
on `--reject`, etc.): `NavItems.module.css:60`, `StepNavBar.module.css:98`,
`RunScanButton/index.module.css:128`, `ConfirmDialog.module.css:56`, `AlertBadge.module.css:12`.

**Fix:** no existing "inverse text" / "text on solid" token exists in `app/globals.css` today —
add one (e.g. `--text-on-solid: #fff;` in the `:root` token block, alongside the existing
`--pass`/`--caution`/`--reject` definitions), then replace all 5 hardcoded `#fff` with
`var(--text-on-solid)`. Check whether the token needs a different value in light vs. dark theme
(inspect `app/globals.css`'s `[data-theme="light"]` override block for how other tokens handle
this) — white-on-saturated-status-color usually reads fine in both themes, but verify against the
actual `--reject`/`--pass`/`--caution` color values in both theme blocks before assuming one value
suffices for both.

**Test plan:** none needed (pure CSS token substitution, visually verify in both themes via the
dev server per CLAUDE.md's "test the golden path" guidance for UI changes — a screenshot diff in
light and dark mode of the 5 affected components is sufficient).

---

## 3. Redundant double-POST on options paper-order placement (#13)

`frontend/app/(frame)/screener/step-7-trade-card/page.tsx:498,507` — `persistPosition(pos)` POSTs
the new position, then on success `addPosition(pos)` (from `portfolioStore.ts`) independently
POSTs the same position again via its own internal `postPosition()` call. The second POST is
swallowed as a harmless 409 today.

**Fix — need to determine the *intended* division of labor between `persistPosition` and
`addPosition` before removing either call, since they may not be pure duplicates:**
1. Read `persistPosition`'s full implementation (likely local to this page or a shared helper) and
   `portfolioStore.ts`'s `addPosition` in full — confirm both really do send an equivalent POST to
   the same endpoint with the same payload shape, not just "both eventually POST something."
2. If `persistPosition` exists specifically to get `saved.ok`/`saved.adjustedQty` (exposure-limit
   feedback) back synchronously before deciding whether to also add to local store state, then
   `addPosition`'s internal POST is the truly redundant one — check if `addPosition` has (or can
   be given) a variant/parameter that updates local Zustand state *without* re-POSTing, since the
   position was already persisted successfully by `persistPosition`.
3. If no such variant exists, add one (e.g. `addPosition(pos, { skipPost: true })` or a separate
   `addPositionLocal(pos)` that only updates client state) rather than reworking the whole
   store's POST logic — this keeps `addPosition`'s existing behavior intact for every *other* call
   site that doesn't first call `persistPosition` (e.g. the stock-path call sites from
   `SELL_CLOSE_SEMANTICS_PLAN.md`, which call `addPosition` directly with no separate persist
   step).

**Test plan:** a test asserting exactly one POST to the position-create endpoint per
`placeLimitPaper`/`placeMarketNow` call in `step-7-trade-card`, not two.

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
file before the atomic rename, so there's no window where the final file has permissive
permissions). Also chmod the final path once, in case an existing file predates this fix and still
has broad permissions from before:
```python
tmp.write_text(yaml.dump(data_copy, default_flow_style=False))
os.chmod(tmp, 0o600)
os.replace(tmp, self._path)
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

`backend/scripts/update_sp500_liquidity.py:134-150` rewrites `backend/app/data/sp500.csv`
unconditionally; a bad yfinance batch could write a mostly-zeroed `liquidity` column over the file
that drives the sector heatmap and universe filters.

**Fix:**
1. Add a `--dry-run` flag that runs the full fetch/compute pipeline but prints the would-be
   summary (the existing "Done. N/M symbols have liquidity > 0" line, plus per-symbol WARN lines)
   without writing the CSV.
2. Before writing, back up the existing file (`shutil.copy2(CSV_PATH, CSV_PATH.with_suffix('.csv.bak'))`)
   so a bad run can be manually reverted.
3. Add a sanity threshold: if the fraction of symbols with `liquidity == 0` after a run exceeds
   some threshold (e.g. >20%, tunable) compared to before, print a loud warning (and consider
   exiting non-zero without writing, gated behind a `--force` flag to override) rather than
   silently completing — this is the actual scenario the finding describes (a transient
   yfinance outage returning mostly-empty data).

**Scope guard:** this is a maintenance script run manually or via `sp500_scheduler.py` — don't
over-engineer it into a full CLI framework; argparse with 1-2 flags is sufficient.

**Test plan:** if this script has any existing test coverage, extend it; if not, a lightweight
test isn't required for scope — this is a low-frequency manual/scheduled maintenance script, and
the `--dry-run` flag itself is the primary safety net, verifiable by manual invocation.

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
