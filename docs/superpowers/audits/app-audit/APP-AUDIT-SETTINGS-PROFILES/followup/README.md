# Follow-up evidence for #350

This supplements the original approved plan Tasks1–3 on source
`4b1f6b86e8137f499da0c4c430f23b9c250fd8de`. It preserves every original
controls/settings/regime artifact. Old “not run here” entries are historical;
[18 explicit dispositions](coverage-dispositions.json) describe new observations
and remaining limits without marking all boundaries complete.

| Family | Assertions | Scope |
| --- | --- | --- |
| [Storage](storage/coverage.md), #393 | 88:65 pass,23 fail | Targeted QuotaExceededError/SecurityError, profile CRUD memory/readback, importer preservation, future version, actual process restart and ordinary two-tab edits. Real quota exhaustion/read failures unrun. |
| [Settings states](settings-states/coverage.md), #394 | Browser42:33 pass,9 fail; actual schema15 pass; real temp YAML12:9 pass,3 fail | Mock fixed/loop schedule CRUD, orphan/legacy profiles, initial timezone failure, IV Reset/loading/failure, health disclosures; real schema bounds and isolated YAML recovery. No real scheduler or DB claim. |
| [Real intraday](intraday/README.md), #396 | 30/30 pass | 2,480 provider15min bars with receipt/hash; actual adapter and fit, independent conditional HMM inference and scalar OMM; completed-bar and insufficient-data boundaries. No predictive/model calibration certification. |

Counts overlap across mechanisms; they are not unique defects or completed
inventory definitions. New profile write failure, theme sync, normal two-tab
lost update, invalid schedule recovery loss, silent schedule feedback,
orphaned profile display and timezone initial-load feedback have distinct
remediation issues in [defects.json](defects.json). Existing #371 is extended
with local failed writes; #381 with synthetic newer-version downgrade; #373
with MA0 and breakout1 rejected by the real schema. Breakout4 is accepted by
the schema and retained only as a UI range observation. All product defects
remain unfixed; application acceptance stays open.

All browser business HTTP is mocked and WebSockets closed. Backend store/schema
checks use temporary storage and no app.main/scheduler. The sole provider request
was a configured read-only Tradier timesales GET, captured at2026-10-16
20:29:54.556538UTC (22:29:54.556538 Europe/Berlin). No account/order/notification
operation occurred. Its sanitized JSON preserves bar fields/values; the hash
is not a hash of original HTTP transport bytes. The44-day all-session fixture
is sufficient for the800-bar fit cap but does not fill the55-day request range.

[Runtime reconciliation](reconciliation/runtime-links.json) pins A's increment
`e72b15a58b69267150143c0922d37ca92272c844`: unchanged36 B definition IDs,
12 explicit observation links spanning4 definitions. Other definitions retain
B evidence and explicit residuals. A's final independent reconciliation is still
pending; this is an increment, not final runtime/state closure. No shared
inventory or PROJECT_STATE.json was edited concurrently.

The original clean plan round1 and artifact round1 remain counted. This new
delta requires fresh independent code/artifact round2 of the existing3-round
cap. Its report is recorded separately; a clean evidence review cannot clear
known application failures, final A reconciliation or C–J integration work.
