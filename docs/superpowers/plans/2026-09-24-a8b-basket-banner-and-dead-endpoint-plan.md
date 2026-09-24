# A8b — the basket failure banner's lifetime + the reader-less stop-premium route (plan)

Date: 2026-09-24. Planned against main at `5726e12`. Two independent layers, one commit each.

Kenneth's decision `A8B-BASKET-BANNER-AND-DEAD-ENDPOINT-2026-09-24`, both on the proposal put to him:

| # | Item | Decision |
|---|---|---|
| 1 | The basket's "Some orders were not saved" banner still dies on Prev/Next, while A8 made the basket's dropped-stop notices survive it | Same lifetime as the notices |
| 2 | `GET /api/config/stop-premium-thresholds` has had no caller since A8 deleted `stopPremiumThresholdsStore` | Delete the route; keep `pass_max_fraction_for()` |

---

## 1. The basket failure banner (frontend)

### Defect, verified on today's tree

`frontend/app/(frame)/screener/step-7-trade-card/page.tsx`:

- `:478` one `orderError` slot serves **both** the direct paths (`placeLimitPaper` `:1075/:1080`,
  `placeMarketNow` `:1126/:1131`) **and** the basket (`handleSubmit` `:1248`,
  `Some orders were not saved — <SYM>: <detail>; …`).
- `:597` the `[active]` effect clears `orderError` on every Prev/Next.

So after a basket where one order was rejected, pressing Next erases the banner. The rejected row
was rolled back and the toast counts only placed/queued orders and auto-dismisses at 6 s, so the
banner is the **only** disclosure that an order was not saved. A8 already moved the basket's
dropped-stop notices to their own `basketNotes` state for exactly this reason (`:488-494`).

### Change

1. New state beside `basketNotes`:
   `const [basketError, setBasketError] = useState<string | null>(null);` with a comment giving the
   lifetime and pointing at the `basketNotes` comment for the reason.
2. `handleSubmit` `:1248`: `setOrderError(\`Some orders were not saved — …\`)` →
   `setBasketError(...)`. Its start-of-submit resets add `setBasketError(null)`; it **keeps**
   `setOrderError(null)` (a basket send is a send "of any kind"; a stale direct-path error must not
   sit over it — the property the existing "does not leave the previous submit's banner" test
   guards, now split across two slots).
3. `placeLimitPaper` `:1048` and `placeMarketNow` `:1103`: add `setBasketError(null)` to the reset
   line that already clears `setBasketNotes([])`.
4. The `[active]` effect `:597` is **unchanged** — it must not touch `basketError`, and it must keep
   clearing `orderError` (direct-path errors keep their per-card lifetime; decision text).
5. Render `{basketError && <Text size={12} tone="reject">{basketError}</Text>}` next to the
   `orderError` line `:1509`, i.e. **outside** the `selectedBroker` gate (ROUND 12 finding 2 — the
   basket never sets a broker). Update the ROUND 12 comment block above it, which names
   `setOrderError` as the basket's rejection channel.
6. Fix the comment inside `handleSubmit` (`:1159-1166`) that describes the three resets, so it names
   the new slot.

No other writer of `orderError` exists (grep: 6 `setOrderError` sites, all above). Nothing outside
this file reads either slot. Not persisted, no store.

### Tests — `__tests__/edited-fields-sync.test.tsx`, block `spec §8 #8`

All run with `selectedBroker: null` (the block's beforeEach) unless the test clicks a broker.
Every test that reaches `incrementDaily` restores `useRiskStore.dailyRecommendations` at its end —
the cap of 5 is shared by the file and never reset (see the A8 basket test at `:837`).

- **T1 (new)** — *keeps the basket's failure banner across Prev/Next until the next send.*
  422 fetch → pin AAA → send → `Some orders were not saved — AAA:` shown. Next (wait for `BBB Inc.`)
  → still shown. Prev → still shown. Swap fetch to ok, Next, pin BBB, send basket → banner gone
  (`waitFor … not.toBeInTheDocument`) and 1 position saved. Restore the daily count.
- **T2 (new)** — *a DIRECT send clears the basket's failure banner.* `editAllThree()` (the direct
  buttons need the edited plan/pick, as in the `:720` test), 422 fetch, pin + send basket → banner.
  Swap fetch to ok, click `ibkr paper`, click `Place Limit @…` → banner gone and one position.
  Restore the daily count.
- **T3 (new)** — *a DIRECT-path error still clears on navigation* (pins the half of the decision that
  did **not** change, which no test covers today). Click `ibkr paper`, make `api.postOptionOrder`
  reject once, click `Place Limit @…` → the error text shown. Next → gone.
- **Existing, must stay green unchanged:** `shows the rejection banner for a BASKET order with no
  broker selected` (`:874`) and `does not leave the previous submit's banner over a successful one`
  (`:895`).

### Mutation checks (each must turn a named test red, then be reverted)

| Mutant | Must fail |
|---|---|
| M1: add `setBasketError(null)` to the `[active]` effect | T1 |
| M2: write the basket failure back into `setOrderError` | T1 |
| M3: drop `setBasketError(null)` from `handleSubmit` | T1 (last assertion) and `:895` |
| M4: drop `setBasketError(null)` from `placeLimitPaper` | T2 |
| M5: remove `setOrderError(null)` from the `[active]` effect | T3 |
| M6: render `basketError` inside the `selectedBroker` gate | T1 and `:874` |

`placeMarketNow`'s reset is the same one-token edit as `placeLimitPaper`'s and has no own test (the
Right Now button's test surface would duplicate T2); stated here rather than left implied.

---

## 2. Delete the reader-less route (backend)

### Verified on today's tree

- `backend/app/routers/config.py:47-68` `get_stop_premium_thresholds` — `grep -r` over `frontend/`
  (excl. `node_modules`) for `stop-premium-thresholds` / `getStopPremiumThresholds` /
  `HorizonStopPremiumThresholds`: **zero hits** (A8 deleted the client).
- The gate's real reader is `backend/app/scoring/stop_cost.py:152` `pass_max_fraction_for()`, called
  at `:242`. It never read the endpoint; deleting the route changes no behaviour.

### Change

1. Delete the route and its docstring from `routers/config.py`. `load_scoring_cfg` stays imported
   (the other routes use it).
2. `stop_cost.py:155` docstring: drop "the same one /api/config/stop-premium-thresholds serves the
   client from"; keep the one-source-of-truth point (no hardcoded copy on the scorer).
3. `stop_cost.py:89-90` comment: "Same choice … as the frontend's `getStopPremiumThresholds`
   fallback" names a deleted function — reword to state the reason on its own. (Not in the phase
   note; found by the grep.)
4. `tests/test_config_score_thresholds.py`
   - `:21 test_stop_premium_thresholds_endpoint_mirrors_yaml` → **re-point** at
     `pass_max_fraction_for`: for each of intraday/swing/position,
     `pass_max_fraction_for(label) == horizons[key]["stop_premium"]["pass_max_fraction"]`. Renamed
     `test_pass_max_fraction_for_mirrors_yaml`.
   - `:36 test_stop_premium_thresholds_are_coherent` → **re-point**: keep the `0 < frac <= 1`
     value-sanity check via `pass_max_fraction_for` for the three horizons; replace the payload
     key-set check (the client type is gone) with the YAML-level guard it stood for: each
     horizon's `stop_premium` block has exactly `{"pass_max_fraction"}` — the D8 "no
     reject_fraction" guard, now asserted where the value actually lives.
5. `tests/test_stop_cost_gate.py`
   - `:128 test_endpoint_key_set_matches_the_client_type_exactly` → **delete** (its subject, the
     client type, is gone; its no-`reject_fraction` guard survives in 4b; its value equality is
     covered by `:118`).
   - `:146` docstring "Same choice as the frontend's getStopPremiumThresholds." → reword.

### Test-count accounting (main: 3000 passed / 1 skipped)

−1 (`test_endpoint_key_set_matches_the_client_type_exactly` deleted); the two
`test_config_score_thresholds` tests are re-pointed, not removed. **Expected: 2999 passed / 1
skipped.** Any other delta is a finding.

### Mutation checks

- Change one horizon's `pass_max_fraction` in `pass_max_fraction_for` (e.g. force `horizon_key` to
  `"swing"`) → the re-pointed mirror test fails.
- Add a `reject_fraction: 0.9` to one horizon's `stop_premium` block in `scoring_rules.yaml` → the
  re-pointed coherence test fails.

### Grep gate

`grep -rn "stop-premium-thresholds\|get_stop_premium_thresholds\|getStopPremiumThresholds\|HorizonStopPremiumThresholds"`
over `backend/ frontend/` (excl. `node_modules`, `.venv`, `__pycache__`) returns nothing. Hits in
`docs/superpowers/` history (plans, PROJECT_STATE records) are left as history.

---

## 3. State + verification

- `PROJECT_STATE.json`: phase `A8B-BASKET-BANNER-AND-DEAD-ENDPOINT` → status/rounds per the
  adversarial rounds; the `defect_marker` probe goes quiet when the route is gone — switch its
  `verify` to a presence probe on the new `basketError` state in `page.tsx` so the phase stays pinned.
- Frontend: `npx tsc --noEmit`, full `npx jest` — expected 137 suites / 1818 tests (1815 + T1-T3).
- Backend: `.venv/bin/python -m pytest -q` — 2999 passed / 1 skipped.
- `python3 scripts/state.py` exits 0.
- Merge to main only after the code round comes back clean. Cap: 3 rounds.
