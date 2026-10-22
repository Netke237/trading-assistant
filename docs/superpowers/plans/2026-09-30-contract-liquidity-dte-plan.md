# CONTRACT-LIQUIDITY-DTE — plan (r6: r5 refreshed onto main 48ff4ce9 after NO-LIVE-QUOTE; new plan stage; nothing built)

- **Phase:** `CONTRACT-LIQUIDITY-DTE` (PROJECT_STATE.json). Board item / tracking issue **#161**.
- **Branch:** `board/contract-liquidity-dte-3c0a1edd`, cut from `board/contract-liquidity-dte-b714cd2a`
  (= `claude/contract-liquidity-dte`, bed0ab4f), with `origin/main` 48ff4ce9 merged in (dcb3bca5).
- **Why r6.** r5 was written on 2026-09-30 against main 4c520006. Since then NO-LIVE-QUOTE (#119, PR #202) has
  rewritten the quote side of contract selection, and main has moved about 540 commits. Kenneth chose option (a)
  on #161 (2026-10-10): refresh r5 onto current main, keep **only fix 1 and fix 2 exactly as answered on
  2026-09-30**, check what NO-LIVE-QUOTE already covers, and open **one new plan stage** (cap 3), then tickets,
  build and a code audit (cap 3). Decision `CONTRACT-LIQUIDITY-DTE-REFRESH-STAGE-2026-10-10`.
- **What r6 changes against r5:** line references re-based; §0 re-derives the round-5 gate finding against
  current main; §1 adds the consumers main grew since r5 (`contract_explanation`, config health, the
  pipeline-diagnostics parser, `test_step6_contract_rules.py`'s liquidity tests); §3 drops the merge-hold
  residual; §4 lists the tests the change breaks, **measured** by applying fixes 1+2 to a scratch copy and running
  the full backend suite; §5 cuts the work into three tickets; §6 replaces r5's `shipped_unaudited` bookkeeping
  with today's `built` rules. The design (fix 1, fix 2) is unchanged.

## 0. The round-5 gate finding, re-derived on main 48ff4ce9

Round 5 (2026-09-30) found that after the close fix 1 let a volume 1–49 contract with a **fabricated 0% spread**
reach a broker order: via the scan's PASS trigger and an armed Step 7 card, or Step 7's direct send. Kenneth held
the merge until NO-LIVE-QUOTE landed. Each link of that path on current main:

1. **The fabricated spread no longer exists.** `market.py:907-917` and `:1665-1676` (the two chain builders) drop a row
   whose ask is not > 0; the fallback to `last` with `spread = 0.0` is gone. Off-hours rows carry the last close's
   real two-sided quotes (NLQ plan §1, measured 0 of 4,868 rows with ask 0).
2. **Every chain row carries `quoteLive`/`quoteState`** (`market.py:813-828`, `app/data/quote_liveness.py`).
   Outside the session every row is `session_closed`, so `quoteLive` is False.
3. **The scan rejects a non-live row outright.** `validate_contract(..., quote_mode="reject")` is the default
   (`contract_validator.py:481-531`): `reject_reasons == ["no_live_quote"]` and no other rule is judged. So an
   after-close scan has no PASS candidate and cannot reach `maybe_fire_on_scan`.
4. **Auto-trade re-checks the exact option's quote at fire time** (`auto_trader._option_quote_state`,
   `auto_trader.py:685-743`, called at `:2709` before the disarm): session closed → refused with the arm preserved, before any broker call.
5. **Step 7's direct send fetches a fresh quote at send time** and, when it is not live, sends nothing without an
   explicit per-contract confirm tick (NLQ plan §3e).
6. **Step 6 / the Watchlist** grade a non-live row in `quote_mode="label"` (`contracts.py:309`): graded as live
   on its **real** closing quote, then capped at CAUTION and flagged `no_live_quote`.

So the finding's premise (a fabricated spread graded as perfect) is gone, and every order path refuses or asks
first when the quote is not live. What fix 1 still changes after the close: Step 6 / the Watchlist show volume
1–49 contracts that today are `volume_too_low`, graded on their real closing spread and capped at CAUTION. That
is the intended effect of fix 1 (PRD FR-25), on real numbers. **No merge hold remains**; the plan does not
depend on decision `CONTRACT-LIQUIDITY-DTE-MERGE-HOLD-2026-09-30` any more (NO-LIVE-QUOTE is on main).

## 1. What is true on main (48ff4ce9)

1. `contract_validator._hard_reject_reasons` (`contract_validator.py:123-178`), volume branch `:144-147`:
   - `volume < hr["min_volume"]` (50) is a hard reject **unless** `volume == 0 and oi >= min_open_interest`.
   - `oi < min_open_interest` (200) is a separate hard reject (`:148-149`).
   - Result: volume 0 with OI 319 passes; volume 3 with OI 1,534 is rejected. The better-traded contract loses.
   - Since NO-LIVE-QUOTE, `_hard_reject_reasons` is not called at all for a non-live row in reject mode
     (`:527-533`).
2. `_score_liquidity` (`:196-227`) raises **two** soft flags from one axis, `low_volume` (< 200) and
   `low_open_interest` (< 1,000), at `:223-226`. `validate_contract` rejects at `max_soft_fail_count` = 3 flags
   (`:579-583`). A long-dated contract usually carries both, so one further soft miss rejects it.
3. `volume` is Tradier's session-to-date count (`market.py:920` and `:1679`, `int(c.get("volume") or 0)`).
4. Consumers of the liquidity flag names (grep of `backend/app`, `frontend/` excluding tests, `llm-contexts/`):
   - `validate_contract`: `soft_flags` and `len(soft_flags)` (`:579-580`);
   - the score explanation: `components.liquidity.flags = liq_flags` (`:742`), rendered raw by
     `frontend/components/molecules/ContractScoreExplanation/index.tsx:221-223` as "Rule notes: <flag>" (only
     `iv_rank_elevated` gets special text). A merged flag renders as `thin_liquidity`; no number changes;
   - `llm-contexts/22-contract-validation.md:221-223` (docs).
   Nothing branches on `low_volume` / `low_open_interest`.
5. Consumers of `min_volume` outside tests:
   - `backend/config/contract_rules.yaml:18` (the default) — the phase's defect-marker probe;
   - `contract_validator.py:146` (rule), `:374` (`_CONTRACT_OVERRIDES` key), `:613-620` (the blocker detail,
     threshold = the floor), `:872` (echo);
   - `backend/app/services/config_health.py:189` — key-presence/staleness only; after the YAML edit the
     config-health banner reads stale until the backend restarts (expected, as for any YAML change);
   - `frontend/lib/executionParamDefaults.ts:31` (`PARAM_DEFAULTS_POSITION`, shared by Position, Quarterly,
     SemiAnnual and Annual), `:59` (Intraday), `:85` (Swing), `:115` (Custom);
   - `frontend/app/(frame)/screener/step-3-direction/page.tsx:163-166` (field + hints), `:173-181` (block
     comment), `:182-185` (Preferred hints);
   - `frontend/lib/parsePipelineDiagnostics.ts:261` — labels a recorded `min_volume` override; reads no
     default; unchanged;
   - the seed profiles under `docs/search-profiles/` (§3 fix 1);
   - `frontend/e2e/fixtures/generate_contract_boundaries.json` — a captured scorer wire whose recorded config
     says `min_volume: 50.0`; its spec asserts spread inequalities only. Not regenerated (§7).
6. **Step 3 presets reach the scan only when edited.** `buildOptionsScanRequestBody`
   (`frontend/lib/resolveOptionsScanRequest.ts:92-121`) posts `scanOverrides`, which holds only user-edited keys.
   So the backend YAML is what grades a default scan; the preset value is what Step 3 shows and what an edit
   starts from. Both must move together (fix 1).
7. Stored values that carry an explicit `min_volume` keep it (Q1 (b)): saved search profiles (browser), a scan's
   stored `contract_rules`, and scheduled-scan entries' frozen request.
8. `_load_config` is `lru_cache`d (`contract_validator.py:56`).

## 2. Measurement (2026-09-30, 13:24 ET, in session; r5, unchanged — not re-measured, Kenneth chose (a) over (c))

**Method:** 60 symbols drawn at random (seed 7) from the scan's names that reached an option chain.
`GET /api/contracts` with calls, `limit=100`, `max_price=500`, and hold windows 5–15 / 15–45 / 45–60 / 98–105
days (DTE ≈ 2× hold; one expiry per chain). Kept only contracts with delta 0.20–0.85 (the current hard delta
band). Volume is **partial-day** (13:24 ET). One day, calls only, Tradier only, a sample biased toward names
that scored bullish. Enough to size the problem, not to set final numbers.

| Window (DTE) | Contracts / symbols | Volume p50 / p90 (share at 0) | OI p50 / p90 | Spread p50 / p90 |
|---|---|---|---|---|
| Swing (16–23) | 567 / 59 | 1 / 36 (49%) | 37 / 496 | 12.8% / 32.9% |
| Position (51) | 614 / 60 | 3 / 162 (39%) | 165 / 3,360 | 7.9% / 23.2% |
| Quarterly (107) | 798 / 57 | 1 / 60 (48%) | 432 / 4,729 | 7.3% / 21.4% |
| Semi-annual (198) | 472 / 29 | 0 / 7 (77%) | 16 / 231 | 8.9% / 31.2% |

Symbols with at least one contract that clears each rule set (and, second number, also has fewer than 3 of
the liquidity/spread/delta soft flags — DTE and IV flags not modelled, so this is optimistic):

| Window | Today's hard liquidity rules (clear → also < 3 flags) | OI ≥ 200 + spread ≤ 20% only (clear → also < 3 flags) | Same, with one merged liquidity flag (also < 3 flags) |
|---|---|---|---|
| Swing | 18 → 9 | 29 → 15 | 28 |
| Position | 30 → 19 | 38 → 29 | 35 |
| Quarterly | 48 → 28 | 51 → 39 | 48 |
| Semi-annual | 8 of 29 → 3 | 11 → 7 | 10 |

Contracts with OI ≥ 200 and spread ≤ 20% that are rejected **only** for 1–49 volume today: swing 58 (22 symbols),
position 148 (32), quarterly 268 (43), semi-annual 38 (8).

**What the numbers say:**

1. The zero-vs-small-volume inconsistency is real at every horizon, not just 6 months out, and it is the
   largest single avoidable loss (quarterly: 268 good contracts across 43 of 57 names).
2. Two liquidity soft flags are the next-largest loss. Merging them raises the names that also clear the
   soft-failure count from 15 → 28 (Swing), 29 → 35, 39 → 48 and 7 → 10. That roughly doubles only for Swing.
3. **Semi-annual is thin for real.** Only 29 of 60 names even list a ~198-day expiry, and their median OI is
   16. Even with fixes 1 and 2, about 10 of those 29 have a gradeable contract. Loosening the OI floor to
   make Semi-annual look healthy would admit genuinely illiquid contracts, so this plan does **not** scale
   the OI floor by DTE. The honest answer for Semi-annual is in §9 Q4, not in a lower bar.
4. The review's idea of DTE-scaled *preferred* minimums is not supported by the data: OI grows with DTE up to
   quarterly and then collapses; volume is low everywhere. A merged flag (fix 2) does the work without
   inventing a DTE curve.


## 3. Design (fixes 1 and 2, as answered 2026-09-30; unchanged from r5 except where marked)

**Fix 1 — volume is no longer a hard reject by default (FR-25; Q1 (b)).**
- Default `min_volume` goes from 50 to 0:
  - `backend/config/contract_rules.yaml:18`, `hard_reject.min_volume: 0`, with the comment changed to
    "optional hard floor; 0 = off (FR-25 treats volume as soft)". The comment must not contain the string
    `min_volume: 50` (the phase's defect marker matches `min_volume: 50\b` in that file).
  - the four literals in `frontend/lib/executionParamDefaults.ts` (`:31`, `:59`, `:85`, `:115`). The test covers
    every `PARAM_DEFAULTS_PER_HORIZON` key: Intraday, Swing, Position, Quarterly, SemiAnnual, Annual, Custom.
- `_hard_reject_reasons` (`contract_validator.py:146`): the volume branch gains an explicit
  `hr["min_volume"] > 0 and` guard. It changes nothing for integer volumes (`volume < 0` is never true); it states
  "0 = off" in code.
  - The **zero-volume exemption stays** for an explicit floor above 0, so for a user who opts into a floor,
    "vol 0 / OI ≥ 200 passes, vol 3 fails" stays as today (recorded residual). Its comment
    (`:144-145`, "volume == 0 is Tradier's off-hours sentinel") is **r6: reworded** to what NO-LIVE-QUOTE measured
    — the exemption is kept for an explicit floor, because a volume of 0 cannot be told apart from "no trades yet
    this session"; off-hours rows are rejected or labelled by the quote-liveness rule, not by this branch. No
    behaviour change.
- Step 3 (`step-3-direction/page.tsx`):
  - `:163` label → "Min option volume (0 = off)";
  - `:164` hint → an optional hard floor, off by default because volume is scored softly under Preferred
    Liquidity; the figure is **session-to-date** volume, so with a floor set, results change with the time of
    day; it keeps the "Hard floor only…" sentence, reworded for fix 2 (below);
  - `:166` (`min_open_interest` hint) and `:183` (`preferred_volume_min` hint, "Independent of the hard 'Min
    option volume' floor above, which rejects outright") reworded to match;
  - the field, its `min: 0` and the override key stay.
- Stored values are not rewritten (§1 item 7): each keeps its explicit `min_volume`; one without the key gets 0.
- **Canonical profile seed** (r5, round 3 finding 5). `docs/search-profiles/search-profiles-export.json` and the
  identical `RAW` string in `docs/search-profiles/import-search-profiles.js:21` seed 18 profiles: six `*_Loose_*`
  carry `min_volume: 20`; Intraday/Swing `*_Restrictive_*` 200; SemiAnnual `*_Restrictive_*` 50; Baselines none.
  After fix 1 every Loose profile would be stricter on volume than its Baseline, so:
  - **JSON and JS:** `min_volume: 0` on the six Loose profiles; their `updatedAt` moves to the build date
    (`README.md:69-71` convention). The JS `RAW` string stays byte-identical to the JSON (checked by a script:
    `JSON.parse` of `RAW` deep-equals the JSON file). Restrictive and Baseline profiles are untouched.
  - **The xlsx** (`Bamendjou_Options_Search_Profiles.xlsx`) mirrors the JSON: the six Baseline rows' Min Volume
    50 → 0; the six Loose rows' 20 → 0; the legend's "SemiAnnual_Restrictive keeps volume at the Baseline floor
    (50)" → "keeps an explicit 50; the Baseline floor is now 0 (off)"; "flagged 'low_volume'" / "flagged
    'low_open_interest'" → "flagged 'thin_liquidity' (volume and open interest together count as one soft
    miss)"; the Min Volume legend row → "optional hard floor; 0 = off". Edited with `openpyxl` from a throwaway
    install (not added to any requirements file); every other cell is checked unchanged by a before/after cell
    dump.
  - **README.md:** `:23` "min volume 50 (the Baseline floor)" → "an explicit min volume of 50 (the Baseline floor
    is now 0, off)"; `:125` "0.30/20/75" → "0.30/0/75".
  - Profiles already imported into a browser are not touched (settled 2026-09-30). Board item #187 (recalibrate
    the 18 profiles) runs after this phase and may change these values again.
- `min_open_interest` (200) and `max_bid_ask_spread_pct` (0.20) are unchanged; they remain the liquidity hard
  gates.

**Fix 2 — one liquidity soft flag (Q2).**
- `_score_liquidity` (`contract_validator.py:223-226`) appends one `thin_liquidity` flag when either
  `pref_volume_min > 0 and volume < pref_volume_min` or `pref_oi_min > 0 and oi < pref_oi_min`. It replaces
  `low_volume` and `low_open_interest`.
- The score arithmetic is unchanged (volume and OI still each weigh half); `detail["liquidity"]` and
  `explanation.components.liquidity` still carry volume, OI and both preferred minimums.
- Step 3: the `preferred_volume_min` / `preferred_oi_min` hints (`:183`, `:185`) say each "counts as one soft
  miss" → "volume and open interest together count as at most one soft miss"; the `min_volume` /
  `min_open_interest` hints' "(each Preferred floor it misses counts as one)" → "(the two Preferred liquidity
  floors together count as at most one)"; the block comment `:173-181` is updated the same way.
- `llm-contexts/22-contract-validation.md`: only the volume floor (`:113`, `:187-188`), the kept exemption, the
  merged flag (`:221-223`) and the "`volume=0` → `volume_too_low`" example (`:408`, `:427`). Other stale content
  in that file is not this phase's.

## 4. Tests, mutations, docs

**Measured, not guessed (r6).** Fixes 1 and 2 were applied to a scratch worktree of this branch (YAML
`min_volume: 0`; the two flags merged into `thin_liquidity`; nothing else) and the full backend suite was run on
Python 3.11 (Telegram env vars unset): **13 failed, 7763 passed, 9 skipped.** Every failure is an assertion of
the old default or the old flag names; there is no other kind. Each is handled below. **Rule for all of them:**
an assertion's *intent* is kept. A test that used the default floor of 50 to exercise the volume rule is
re-pointed at an explicit `overrides={"min_volume": 50}` (Q1 (b) keeps that floor available); a test of the soft
flags gets the new name; nothing is deleted or weakened, and no fixture is changed except where named.

*`backend/tests/test_contract_validator.py`* — new tests on `_contract_with_expiry(40, …)` (`:159-162`: expiry 40
days out, bid 2.00 / ask 2.10, delta 0.45, `iv_rank` 30 with no basis, vol 500, OI 2,000), `stock_score=70`,
each asserting the **exact** `soft_flags` list:
- **AAPL-315C shape:** vol 3, OI 1,534, spread 1.2% (bid 2.00 / ask 2.025) → `reject_reasons == []` at the
  default config.
- At the default floor, vol 0 and vol 3 (all else equal) → identical `reject_reasons` and `soft_flags` (scores
  not compared: `int(3/200*60) == 0`).
- `overrides={"min_volume": 50}`: vol 3 → `volume_too_low`; vol 0 with OI ≥ 200 → no `volume_too_low`
  (exemption kept); vol 0 with OI 150 → both `volume_too_low` and `open_interest_too_low` (kills a mutant that
  drops the exemption's OI clause).
- OI 150 → `open_interest_too_low`, at vol 0, 3 and 500.
- `thin_liquidity` exactly once when vol < pref and OI < pref, when only vol < pref, when only OI < pref; absent
  when both ≥ pref; `low_volume` / `low_open_interest` never appear.
- **One axis costs one slot:** vol 100, OI 500, spread in (8%, 20%) → `soft_flags == ["thin_liquidity",
  "spread_elevated"]`, `reject_reasons == []` (assert reasons only, never status: its weighted score, 44, is
  below caution 45 on the unmutated code — the implementer recomputes this and records it); adding delta 0.25 →
  three flags → `"too_many_soft_failures" in reject_reasons`.
- **Score unchanged:** vol 100 / OI 500 → `breakdown.liquidity_score == 30` exactly.
- Existing NO-LIVE-QUOTE label-mode tests (both fail under the fixes):
  - `test_label_mode_flag_does_not_count_as_a_soft_failure` (`:348-357`): its premise is "two real soft flags
    plus the label stay below 3". With fix 2, vol 100 / OI 500 gives one flag. The fixture gains **one more
    real soft miss** chosen so the live card is still `CAUTION` with exactly two flags (e.g. delta in
    [0.20, 0.30) or a spread just above 8%; the implementer picks one, asserts the exact two-flag list, and
    records the score). Every other assertion stays.
  - `test_label_mode_still_applies_every_other_hard_rule` (`:360-367`): uses vol 1 as "the other hard rule";
    re-pointed at `overrides={"min_volume": 50}` so `volume_too_low` is still the rule exercised.

*`backend/tests/test_overrides.py`* (all seven failures, plus the vacuous negatives):
- `test_preferred_volume_min_override_removes_soft_flag` (`:246-256`), `test_preferred_oi_min_override_removes_soft_flag`
  (`:258-267`), the two `…fractional_override_still_flags_…` tests (`:372-386`, renamed `…_still_flags_thin_liquidity`):
  `low_volume` / `low_open_interest` → `thin_liquidity`. Each fixture already sets the other axis at or above
  its preference (oi 2000 / vol 2000), so the positive and negative assertions both still discriminate.
- `test_preferred_liquidity_overrides_do_not_mutate_cached_config` (`:280-287`): fixture `oi=500` → `oi=2000`, so
  `card_a` carries no `thin_liquidity` from OI alone and the cache-mutation guard still discriminates; then
  `low_volume` → `thin_liquidity`.
- `test_loose_tier_combined_override_clears_both_hard_and_soft_liquidity_gates` (`:289-317`): the default card
  no longer has `volume_too_low` (vol 25 ≥ floor 0); the assertion becomes `"volume_too_low" not in` with
  `open_interest_too_low` still `in`; docstring "fails the DEFAULT hard floor on two axes" → one axis (OI); the
  Loose card's negatives → `"thin_liquidity" not in`.
- `test_low_nonzero_volume_is_rejected` (`:405-410`) and `test_zero_volume_with_adequate_oi_is_not_rejected`
  (`:391-396`, passes but would pin nothing): both re-pointed at `overrides={"min_volume": 50}`, docstrings
  updated.
- `test_preferred_volume_min_zero_…` / `test_preferred_oi_min_zero_…` (`:319-335`) negatives →
  `"thin_liquidity" not in` (each fixture's other axis is ≥ pref, so they still hold).
- `test_min_volume_override_rejects_illiquid` (`:218-224`): "passes default" stays true; docstring untouched.
- The `:247` docstring "above the hard default (50)" corrected.

*`backend/tests/test_step6_contract_rules.py`* (three failures; `_DUST` = vol 3 / OI 10):
- `test_zero_liquidity_floors_reach_the_validator` (`:268-277`): its point is "a non-zero floor rejects, zero
  floors do not". The non-zero baseline becomes an explicit `{"min_volume": 50}` scan (default `{}` now rejects
  on OI only); the expected reason string stays `volume_too_low(1), open_interest_too_low(1)`.
- `test_zero_floors_reach_the_validator_on_the_hold_window_path` (`:300-307`): same — baseline scan with
  `{"min_volume": 50}`.
- `test_a_thin_contract_with_one_more_soft_miss_is_too_many_soft_failures` (`:310-315`): its premise ("the two
  Preferred-floor misses plus one more") is exactly what fix 2 changes. It is rewritten to the new rule: the
  liquidity miss (one flag) plus **two** more soft misses (spread 0.30 on 2.50 = 12% → `spread_elevated`, plus a
  delta in [0.20, 0.30) → `delta_outside_preferred`) → `too_many_soft_failures(1)`; the docstring says one
  liquidity slot plus two others. The Step 3 hint the docstring cites is reworded in T3.
- The comment at `:21-24` ("below the YAML floor on volume AND OI") → "below the YAML OI floor (and below the
  former volume floor of 50)".

*`backend/tests/test_contract_explanation.py`*:
- `test_multi_blocker_fixture_shows_all_causes` (`:215-246`): it lists every blocker the explanation can show,
  volume included; it passes `overrides={"min_volume": 50}` so `volume_too_low` stays one of them. Its inline
  comment `# volume_too_low (< 50)` stays true.
- `test_zero_overrides_disable_soft_checks` (`:114-136`): its negatives at `:132-133` → `"thin_liquidity" not in liq["flags"]`.

*Frontend (Jest), T3:* `frontend/lib/__tests__/executionParamDefaults.minVolume.test.ts` (new, pattern of
`executionParamDefaults.preferredLiquidity.test.ts`) asserts `min_volume === 0` for every
`PARAM_DEFAULTS_PER_HORIZON` key and that `min_open_interest` (200) and `max_bid_ask_spread_pct` (0.20) are
unchanged. Existing tests that pass explicit `min_volume` values (`contractRules.test.tsx`, `api.test.ts:147`,
`contractGrading.test.ts`, `watchlist/__tests__/page.test.tsx`, …) are expected to stay green unchanged; full
Jest is the arbiter.

*Mutations* (scratch only, each must turn a named test red):
1. YAML default back to `min_volume: 50` → the AAPL-shape test.
2. One horizon row in `executionParamDefaults.ts` back to 50 → `executionParamDefaults.minVolume.test.ts`.
3. Restore the two flags → the exactly-once test, the one-axis-one-slot test, and
   `test_preferred_liquidity_overrides_do_not_mutate_cached_config`.
4. The merged flag fires on volume only → the OI-only case.
5. Delete the zero-volume exemption → the `min_volume=50`, vol 0 / OI ≥ 200 cases (new test and
   `test_zero_volume_with_adequate_oi_is_not_rejected`).

*Operational:* `_load_config` is cached, so the backend must restart to pick up the YAML default; config health
flags the stale cache until then. A persisted `scanResult` whose `contract_rules` lack `min_volume` is
re-graded in Step 6 at the new default 0 while its cards were graded at 50; Step 6 and Step 7 disagree until the
next scan. Accepted (r5).

## 5. Tickets (sequential; files disjoint)

| Ticket | Files (only these) | Done when |
|---|---|---|
| **T1 — backend: fixes 1 + 2** | `backend/config/contract_rules.yaml`; `backend/app/scoring/contract_validator.py`; the backend test files named in §4; `llm-contexts/22-contract-validation.md` | §4's backend tests written first and red for the predicted reason, then green; the five mutations each turn their named test red (scratch only, never committed); full backend suite (Python 3.11) green |
| **T2 — seed profiles** | `docs/search-profiles/search-profiles-export.json`, `import-search-profiles.js`, `Bamendjou_Options_Search_Profiles.xlsx`, `README.md` | the six Loose profiles carry `min_volume: 0` with a new `updatedAt`; `RAW` deep-equals the JSON; xlsx cell dump differs only in the cells §3 names; README `:23`/`:125` edited |
| **T3 — frontend: presets + Step 3 wording** | `frontend/lib/executionParamDefaults.ts`; `frontend/app/(frame)/screener/step-3-direction/page.tsx`; new `frontend/lib/__tests__/executionParamDefaults.minVolume.test.ts` | the new test red on main values, green after; mutation 2 red; typecheck clean; full Jest green |

Commits (one per ticket, plus the repo trailers):
- T1 `fix(contracts): volume is an optional hard floor (default 0) and liquidity is one soft flag (CONTRACT-LIQUIDITY-DTE T1)`
- T2 `docs(profiles): Loose seed profiles drop their volume floor to 0, matching the new default (CONTRACT-LIQUIDITY-DTE T2)`
- T3 `feat(step3): Min option volume defaults to 0 (off); liquidity hints name the merged soft miss (CONTRACT-LIQUIDITY-DTE T3)`

## 6. Bookkeeping (PROJECT_STATE.json; coordinator only)

- **This plan's record commit** (before plan round 6): `active_phase` → `CONTRACT-LIQUIDITY-DTE`; status
  `in_progress`; `tracking_issue` 161; `plan` stays this file; decision
  `CONTRACT-LIQUIDITY-DTE-REFRESH-STAGE-2026-10-10` added (Kenneth's option (a) on #161).
- **`verify` is replaced** now, because T1 removes the defect marker (`min_volume: 50\b`) while T2 and T3 are
  still to come, and `in_progress` with the marker gone is drift. New probe: `kind: absent`, path
  `frontend/lib/__tests__/executionParamDefaults.minVolume.test.ts` (T3, the last ticket), pattern
  `min_volume`. Absent today; present once T3 lands, when the status moves to `built`. PRESENCE ONLY: fix 1's
  backend default and fix 2 are pinned by §4's tests and mutations, not by the probe.
- **Rounds.** `audit_rounds` keeps the five historical plan rounds. The new plan stage numbers its rounds
  continuously: round 6 = new-stage plan round 1, cap 3 (rounds 6–8). The code stage that follows has its own
  cap of 3. `state.py` models one plan stage of at most three rounds (`plan_stage`) and cannot express a 5-round
  first stage plus a second stage, so while this phase is active and not clean its hard-cap line ("STOP
  AUDITING AND TELL KENNETH") stays on. That line is **retained and explained**, not silenced, exactly as for
  NO-LIVE-QUOTE's scoped caps: the stage was opened by Kenneth's own answer on #161. No `plan_stage` field is
  written (it would have to claim fewer rounds than were run).
- After a clean code round: `audit_clean: true`, status stays `built` until merged; `shipped` only on merge.

## 7. Out of scope (named, not done)

- DTE-scaled OI or preferred minimums (data does not support them; §2 point 4).
- Step 6 not listing the scan's own contract when `max_price` cuts it (MSFT 515C) — documented residual.
- IV rank 52 vs preferred max 55 scoring only 4–5/100 — separate task.
- The funnel's single "Score + contracts" row hiding `failed_score` vs `failed_contracts` — separate UI task.
- `frontend/e2e/fixtures/generate_contract_boundaries.json` keeps its captured `min_volume: 50.0`: it is a
  recorded wire of a scorer run, its spec asserts spread inequalities only, and regenerating it is a separate
  e2e task (#175 covers disabled e2e coverage).
- Re-measuring the liquidity-by-DTE sample after NO-LIVE-QUOTE (Kenneth's option (c), not chosen).
- Everything about quotes and spreads (NO-LIVE-QUOTE, shipped).

## 8. Expected effect (r5, unchanged)

On the §2 sample (optimistic, see caveats): names with a gradeable contract roughly Swing 9 → 28,
Position 19 → 35, Quarterly 28 → 48, Semi-annual 3 → 10 of 29. The sample was taken in session, so it
measures fixes 1 and 2 alone; the split-off fix 3 does not change these numbers. The scan's end count also depends on the
stock-score gates (`min_stock_score` 55 cut 97 of the 148 contract-stage names in the 2026-09-30 scan), which
this plan does not touch. Expect Semi-annual scans to stay small.


## 9. Questions for Kenneth (answered)

**ANSWERED 2026-09-30 (decision `CONTRACT-LIQUIDITY-DTE-ANSWERS-2026-09-30`): all four recommendations —
Q1 (b), Q2 yes, Q3 (a) in scan/auto-trade with a label-only treatment in Step 6/Watchlist, Q4 (a).**
Consequence of Q1 (b): a saved search profile that explicitly set `min_volume` keeps that value as its
hard floor; profiles are not rewritten.

- **Q1 — `min_volume` after fix 1.** (a) Remove it from Step 3, the presets and `CONTRACT_OVERRIDE_KEYS`;
  saved profiles that carry it are ignored with a one-line notice. (b) Keep it as an *optional* hard floor,
  default 0 (off), so a user can still demand volume. (c) Keep it, but only applied when the quote is live and
  DTE ≤ 60. Recommendation: **(b)** — the spec makes volume soft, and a default of 0 changes nothing for anyone
  who never set it, while keeping the knob honest.
- **Q2 — merged flag.** Accept fix 2 as designed (one flag, score unchanged)? Recommendation: yes.
- **Q3 — no live quote.** (a) Hard reject as `quote_stale` (FR-24; renamed `no_live_quote` in r2). (b) Grade without the spread rule and
  label the row "no live quote". Recommendation: **(a)** for the scan and auto-trade; (b) only as a label in
  Step 6/Watchlist. Note (a) means off-hours scans return far fewer candidates — which is correct, since
  nobody can know the spread then.
- **Q4 — Semi-annual.** The data says 6-month options on most S&P names are thin. Options: (a) leave it and
  let the funnel say so; (b) for Semi-annual/Annual, cap the DTE multiplier (e.g. 1.5× instead of 2×) so
  contracts land in the liquid ~100–150 day band and are rolled; (c) steer long horizons to Stocks mode.
  Recommendation: **(a) now**, (b) as a separate measured task if you want it.


## 10. Loop — first plan stage (r1–r5, history, unchanged)

- **Rounds so far:**
  - Round 1 (r1): 3 high, 7 medium, 6 low, all fixed in r2.
  - Round 2 (r2): 6 high, 6 medium, 8 low. Every high one was in fix 3; that led to the split (r3). Findings
    on fix 3 moved to NO-LIVE-QUOTE. Finding 16 (the preset test must cover every horizon key and be
    named) is fixed here. Finding 20 (reasons accumulate) is moot here, because fix 1 keeps today's
    exemption.
- **Next:** plan round 3 on r3 until clean → build with tests and mutations → code round until clean →
  merge.
- Round 3 (r3): 1 high, 5 medium, 5 low, all fixed in r4:
  - the `test_overrides.py` pins at :204, :300 and :311;
  - the fixture preconditions;
  - the after-close residual, recorded;
  - the seed profiles;
  - the probe wording;
  - the vacuous negatives;
  - the docstrings;
  - `llm-contexts/22`;
  - the scheduled-entry carrier;
  - the line refs.
- Round 4 (r4): 1 high, 4 medium, 7 low, all fixed in r5:
  - the `test_overrides.py` :160 / :171 / :185-191 negatives;
  - the status-vs-reasons assertion;
  - the seed xlsx and README cells;
  - the PROJECT_STATE mechanics;
  - reuse of `_contract_with_expiry`;
  - the docstrings;
  - `:138`;
  - the exact liquidity score;
  - the exemption OI mutant;
  - the session-to-date hint;
  - the `depends_on` contradiction;
  - the `llm-contexts` scope.
- Round 5 (r5, 2026-09-30): 1 gate-level finding, NOT fixed — **HARD CAP reached** (plan stage at 5
  rounds vs cap 3; decision AUDIT-CAP-PER-STAGE-2026-09-25). Auditing stopped; pending Kenneth.
  - **Gate-level (can reach a broker order):** the §3 accepted residual and §1 item 5 say the blast radius
    is the scan and Step 6 only, and that the scan is "not a gate" for auto-trade. False:
    `scan.py:2036` fires `maybe_fire_on_scan` only when some candidate is PASS; Step 7 cards (armable,
    `AutoTradeArm/index.tsx:519` does not gate on contract status) come from the scan pick, which a
    fabricated 0% spread favours (`scan.py:870-872`); `_market_is_open` (`auto_trader.py:418`) is a
    price probe, not an hours test. So after the close, fix 1 lets a vol 1–49 / fabricated-spread
    contract be armed and fired by a re-scan within `max_arm_age_minutes` (30), and sent directly from
    Step 7. Options: accept this broker-order exposure explicitly, or land NO-LIVE-QUOTE first.
  - Not gate-level, logged against main (not fixed in-branch per audit_rule): Step 3 `min_volume` may
    never reach `validate_contract` (open_questions, 2026-09-09, unproven); `audit_rounds`/`active_phase`
    not updated and "r5"/"round-4" subjects evade `state.py`'s `\bround\s+(\d+)`; the fix-1
    `already_shipped` entry needs `audit_clean` at close; probe `min_volume: 0\b` also matches `0.5`
    (use `0(?![.\d])`); pre-market/after-close Tradier volume stated as fact but unobserved; AAPL-shape
    test bid/ask unpinned (2.00/2.025 verified); `test_step6_contract_rules.py:24` comment; xlsx title
    date; §1 header commit id.
  - Mandatory checks passed: weighted-44 fixture recomputed (43.8 → 44), every line ref, state.py exit-0
    mechanics, all five mutations killed.
  - Brief defect: the r5 brief did not tell the reviewer to report gate-level findings only, as
    audit_rule clause (1) requires; future briefs must.
- **Plan stage CLOSED by Kenneth, 2026-09-30** (decision `CONTRACT-LIQUIDITY-DTE-MERGE-HOLD-2026-09-30`):
  build now; hold the merge until NO-LIVE-QUOTE lands. That removes round 5's only gate-level finding (the
  exposure exists only on main); §3's residual is rewritten to say so. Code stage starts at round 6
  (code round 1 of 3), brief restricted to gate-level findings.
- **PROJECT_STATE mechanics.** `scripts/state.py` counts it as drift when a phase's status disagrees with
  its probe (`state.py:717-728`).
  - Today: status `not_started`, with a defect marker on `min_volume: 50\b` in `contract_rules.yaml`.
  - The build commit that edits the YAML flips the status to `shipped_unaudited` in the **same** commit.
    `in_progress` with the marker gone also counts as drift.
  - A phase has one `verify`, and the build commit replaces it with a `present` probe on
    `"thin_liquidity"` in `contract_validator.py`, which pins fix 2.
  - Fix 1 is pinned by a new `already_shipped` entry, "min_volume default 0 (optional floor)", with its own
    `present` probe on `min_volume: 0\b` in `contract_rules.yaml` (`state.py:763-770`).
  - After a clean code round: `shipped`, with `audit_clean` true.

## 11. Loop — second plan stage (r6, opened by Kenneth on #161, 2026-10-10)

- Cap 3 plan rounds (rounds 6–8), then tickets T1–T3, then a code stage with its own cap of 3.
- Auditor brief restricted to gate-level findings (audit_rule clause 1), as r5's brief-defect note requires.
- §10's last line ("Code stage starts at round 6") is superseded: round 6 is this stage's first plan round, and
  §10's references to §1/§3 are to r5's text, not to this revision's.
