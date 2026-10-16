# Lane B audit evidence — issue #350

Source frozen at `880c8441841cc22d5090cdc5f984e4cf7e3d9a8d`.
**Numbers/persistence: defects found. Presentation/usability: defects found.**
Application correctness is not clean; no product fixes or calibration changes
are included. This branch publishes reproducible evidence and separately
claimable remediation issues. #350 remains open for remediation retests,
unverified boundaries and final Lane A reconciliation. This evidence publication
does not request application acceptance or closure of #350.

## Evidence and checks

| Evidence family | Observed result | Scope |
| --- | --- | --- |
| [Controls and profiles](controls/coverage.md) | 312 authoritative assertions: 297 pass, 15 overlapping failure checks | All 66 execution definitions mapped; 110 browser parameter checks pass. Complete lifecycle has 56 observations, including 18-pack apply, UI custom CRUD, restore/backup, reload, real browser-process restart and origin isolation. |
| [Settings](settings/coverage.md) | 61 assertions: 51 pass, 10 fail; 18 boundaries not run here, 3 N/A | All nine sections inventoried; selected UI save/failure/stale-load checks plus real minimal-router/temp-YAML saves, effective readback and process restart. Additional family UI subset is 16/16 pass, not 16 extra unique assertions. |
| [Regime](regime/coverage.md) | Independent OMM/HMM inference matches; VIX window fails; stale gate and mode differences reproduced | Synthetic boundaries and committed daily SPY bars; supplied-model and actual seed-42 fit inference independently derived. Nine browser state observations pass. No frozen real 15-minute provider fixture. |
| Existing frontend baseline | Typecheck and 268 suites / 5,477 tests pass | Unchanged application source. The 32 focused regime frontend tests are a subset, not additional unique tests. |
| Existing backend regime suites | Original isolated-copy run: 3 failed / 88 passed / 2 deselected; supplemental: 89 passed / 4 deselected | Original quote-guard and relocated-config failures retained; supplemental restores layout and excludes two quote-precondition cases and two app.main tests. No full-backend pass is claimed. |

Assertion counts are harness observations, not unique defects or a count of
completed inventory states. A stale-tab external-import overwrite is measured
but documented as an unsupported stale-writer scenario, not a new defect.
The original interrupted 44-observation controls run is retained separately;
the final full lifecycle completed. Separately seeded continuation observations
are not substituted for that lifecycle.

[Provenance](provenance.json), [baseline verification](verification.json),
[controls hashes](controls/summary.json), [regime hashes](regime/manifest.json),
and [Settings family provenance](settings/families-provenance.json) freeze
versions, inputs and commands. Python 3.11.16, Node 24.19.0, Chromium
151.0.7922.173 and Next 15.5.23 development server were used. This is not a
production-build or real-provider certification. The committed SPY fixture's
original provider/retrieval timestamp are unknown and explicitly recorded.

All browser business API traffic is intercepted in isolated storage; backend
harnesses call actual functions/minimal routers with frozen inputs and temporary
stores. No app.main lifespan, live broker orders, real notification sends or
shared/destructive jobs were executed. Config/profile input hashes stayed
unchanged. Read the per-family reports for exact commands and expected/actual
payloads rather than treating mock responses as backend execution.

## Persistence and snapshot boundaries

Search Profiles are browser localStorage only, scoped to origin. The committed
18-pack is Options-only; Stocks has its own custom saved profile, and the bar
is unsupported/hidden in Pre-Breakout. The import script merges stable IDs,
keeps custom profiles and saves the previous raw value under a backup key;
all open tabs must reload after external imports. Settings/profile snapshot
values and current controls are separate: applying an Options profile writes
its captured gates into current Settings. Current universe/override controls
are not generally persisted; saved profiles explicitly capture them.

Frozen profile versus live Settings request values were compared, and an
in-flight request was captured independently of later control edits. These
checks do not certify every result/card consumer's frozen settings; those
integration paths remain owned by C/D/E. Browser-process restart and isolated
backend config-process restart are distinct checks. Broker credential saves,
actual deliveries, job execution, concurrent writers and full DB recovery are
not passed here.

## Published defects

Each issue contains affected SHA, reproduction, expected/actual, owner,
regression/retest requirements and evidence pointers. All remain unfixed.
Shared-file remediation dependencies prevent overlapping fixes; the native
GitHub edges are authoritative. Existing [#343](https://github.com/Netke237/trading-assistant/issues/343)
is reused for stale/literal Custom Stocks universe, with captured payload added.
Calibration remains [#187](https://github.com/Netke237/trading-assistant/issues/187)
and [#188](https://github.com/Netke237/trading-assistant/issues/188).

| Issue | Defect | Ownership / classification |
| --- | --- | --- |
| [#368](https://github.com/Netke237/trading-assistant/issues/368) | Options millions market-cap filters are sent as dollars | B numeric/persistence; J labels only |
| [#369](https://github.com/Netke237/trading-assistant/issues/369) | 252-day VIX percentile uses 259 prior bars | B numeric; J presentation |
| [#370](https://github.com/Netke237/trading-assistant/issues/370) | Appearance row density resets when the Settings section remounts | B save boundary; J presentation/usability |
| [#371](https://github.com/Netke237/trading-assistant/issues/371) | Settings footer confirms Saved after a failed or unsubmitted backend save | B configuration saves; J presentation; F risk follow-up |
| [#372](https://github.com/Netke237/trading-assistant/issues/372) | Late Settings timezone response overwrites an operator edit | B numeric/persistence; scheduling consumers G/H/D |
| [#373](https://github.com/Netke237/trading-assistant/issues/373) | Strategy scan stores zero override that the backend rejects | B validation/persistence; D strategy scan |
| [#374](https://github.com/Netke237/trading-assistant/issues/374) | Failed schedule writes change API state while disk and scheduler retain old values | B persistence; H ingestion/EDGAR/SP500; D tuning |
| [#375](https://github.com/Netke237/trading-assistant/issues/375) | Notifications help text renders a literal Unicode escape | J presentation; B Settings surface |
| [#377](https://github.com/Netke237/trading-assistant/issues/377) | Tuning schedule says every day despite saved weekday selection | J presentation; D tuning; B Settings surface |
| [#380](https://github.com/Netke237/trading-assistant/issues/380) | Stocks manual and scheduled requests drop universe price/cap filters | B request plumbing; D Stocks |
| [#381](https://github.com/Netke237/trading-assistant/issues/381) | Malformed current-version profile crashes the Search Profile controls | B profiles; I recovery; J failure UI |
| [#382](https://github.com/Netke237/trading-assistant/issues/382) | Options score-weight percent overrides are applied as raw multipliers | B control units; C score arithmetic |
| [#383](https://github.com/Netke237/trading-assistant/issues/383) | Stocks requests ignore Step3 confidence threshold overrides | B request plumbing; D confidence gates |
| [#384](https://github.com/Netke237/trading-assistant/issues/384) | Entry Quality controls reach requests but do not affect the trade plan | B control plumbing; C entry-plan arithmetic |
| [#385](https://github.com/Netke237/trading-assistant/issues/385) | Stop percentages display fractions and clamp a typed 3 percent to 100 percent | B numeric control units; C stop consumers; J presentation |
| [#386](https://github.com/Netke237/trading-assistant/issues/386) | Old regime response overwrites the newer direction-aligned scan gate | B numeric/state; all modes |
| [#387](https://github.com/Netke237/trading-assistant/issues/387) | Shared Run Scan confirmation is bypassed in Stocks and Pre-Breakout | B workflow; D/E mode consumers; J presentation |
| [#388](https://github.com/Netke237/trading-assistant/issues/388) | Regime VIX percentile labels render incorrect ordinal suffixes | J presentation; B regime surface |

## Inventory and independent review

[Reconciliation](reconciliation.json) maps all 36 B-owned definitions from
Lane A's current increment to evidence families and explicit residuals. All
14 definition files are byte-identical between A baseline `27fe5182` and B's
baseline; IDs are compatible. This is increment reconciliation, not final
runtime-state closure. No central inventory or shared PROJECT_STATE.json was
edited concurrently. Lane state/review counters are in [state.json](state.json).

Plan stage: one fresh independent reviewer, `/root/settings_profiles_plan_r1`,
reviewed plan SHA256
`3350e499922759bbb4b6912c459addca5d65a8bc94119774a7282798a7b0f7c4`:
zero numeric/persistence and requested-coverage findings after scope recheck.
Artifact code/evidence stage: one fresh independent reviewer,
`/root/settings_profiles_artifact_r1`, reviewed the complete 74-file evidence
diff after merging main `00b4ab54`: zero gate findings and zero concealed
coverage/evidence-integrity findings. [Review record](review-code-r1.md) and
[exact scope/file hashes](review-code-r1.json) record independent replays and
limitations. No fixes were required. Application-code implementation is N/A
because this PR changes no application files.

[Post-merge verification](resume-verification.json): typecheck and all 268
frontend suites / 5,477 tests passed. The isolated supplemental backend subset
passed 89 tests with the same four exclusions; the original 3 failures / 88
passes remain recorded. All frozen input hashes match the frozen baseline.
Current main changed `universe_exclusions.yaml`; old captures remain frozen,
and the new verification is separately labelled. Lane A's remote inventory
remains at `6309c063`, with final runtime/state reconciliation unavailable.
Capture children #365, #366 and #367 are closed. Known product failures and
coverage obligations remain open in #350; a clean evidence review does not
establish a clean application gate.
