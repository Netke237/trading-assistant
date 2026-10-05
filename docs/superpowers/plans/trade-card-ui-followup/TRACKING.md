# TRADE-CARD-UI-FOLLOWUP — local tracking document

Date: 2026-10-05. Status: tickets prepared; implementation not started.

Specification: [Reviewed plan](PLAN.md). Review evidence: [Plan audit](PLAN-AUDIT.md).

The user approved local Markdown ticketing during the completed grilling session. This is an explicit exception to the usual GitHub-only tracker. The k-ticket-coordinator skill was unavailable; repository orchestration rules were used directly. GitHub API read returned Forbidden; no GitHub issues exist for these tickets yet. Files remain local and uncommitted.

## Tickets

| Ticket | Change | Blocked by | Status |
| --- | --- | --- | --- |
| [TC-UI-01](TC-UI-01-align-order-exit-values.md) | Align Order Entry and Exit Plan values | None | Ready |
| [TC-UI-02](TC-UI-02-selected-method-recommendation.md) | Unify recommendation and exit-method presentation | None | Ready |
| [TC-UI-03](TC-UI-03-loss-budget-action-label.md) | Rename loss-budget action | None | Ready |
| [TC-UI-04](TC-UI-04-alternative-contract-spacing.md) | Space alternative contracts | None | Ready |
| [TC-UI-05](TC-UI-05-collapse-scoring-evidence.md) | Collapse captured scoring evidence | TC-UI-06 | Blocked |
| [TC-UI-06](TC-UI-06-move-score-cards.md) | Move horizontal-bar score cards upward in both Stocks and Options | None | Ready |
| [TC-UI-07](TC-UI-07-stocks-step-4-scan-only.md) | Stocks scans start at Step 4 | None | Ready |

## Execution gates

- Claim TRADE-CARD-UI-FOLLOWUP through scripts/claim.py before application implementation; ownership is currently unclaimed.
- Establish a working branch and valid main/origin/main baseline; current state check could not resolve those refs.
- Keep related edits serial when touching the same components. TC-UI-06 precedes TC-UI-05.
- One integrated code review target after build tickets, with fresh independent reviewers and at most three rounds per stage. Plan clearance is not code clearance.
- No merge, deployment or broker action is authorized by these tickets.

## GitHub publication

When API access is restored, check for existing matching phase/ticket IDs to avoid duplicates. Publish this tracker and the seven child issues with gh --body-file. Map local IDs to GitHub issue URLs here, link children to the parent and TC-UI-05 to TC-UI-06 using native dependencies where available; otherwise use explicit parent/blocker links in issue bodies. Retain these specifications and review evidence.

## Needs user

No product decision remains open. GitHub publication requires working API access.
