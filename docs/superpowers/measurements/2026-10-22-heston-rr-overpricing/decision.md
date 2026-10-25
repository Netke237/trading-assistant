# HESTON-RR-OVERPRICING — recorded decision

Board item: [#335](https://github.com/Netke237/trading-assistant/issues/335).

The recommendation was **option D: retain the current Heston pricing and calibration**, and close the evidence item after recording the answer. Kenneth accepted the recommendation on [23 October 2026](https://github.com/Netke237/trading-assistant/issues/335#issuecomment-6364998442) and confirmed agreement with all recommendations on [25 October 2026](https://github.com/Netke237/trading-assistant/issues/335#issuecomment-6393368110). Both untagged answers follow the numbered decision questions; `needs-kenneth` is cleared.

The evidence was merged in [PR #527](https://github.com/Netke237/trading-assistant/pull/527), at `8e1e3b0a80f4dd1f2dcbd26725adf6c40329844c`. The existing plan stage closed clean in three rounds and the existing code stage in one round. The independently recomputed measurements remain in [report.md](report.md) and [recompute.md](recompute.md).

This records the decision to close the evidence item. The measurement limits still apply: the mini-PC live per-scan summary evidence remains pending; the stored scans and captured chains establish the bounded historical results described in the report. Ongoing monitoring uses the per-scan summary introduced by #174. A future pricing change requires its own approved scope and independent reviews.
