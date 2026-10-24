# APP-AUDIT-PRESENTATION-ATTRIBUTION — Tooling and Coverage Report

**Phase ID:** `APP-AUDIT-PRESENTATION-ATTRIBUTION`  
**Source Baseline:** `4a74d186468afe0a7fc4c53e785b24b5c1f72b42`  
**Purpose:** `tooling-self-test` (Zero whole-app usability/presentation coverage claimed)  
**Status:** Reconciled sample observations against frozen inventory with 13 fail-closed mutation checks passed.

## 1. Summary of Disposition Counts

| Disposition | Count | Meaning |
|---|---|---|
| `observed-verified` | 231 | Connected unique census tie or verified host marker |
| `observed-asserted` | 332 | Source-backed presence without unique census/host predicate |
| `observed-ambiguous` | 342 | Duplicate census names or route signature collisions |
| `rendered-untargeted` | 0 | Rendered without direct target or state trigger |
| `not-triggered` | 0 | Scenario executed but specific branch unreached |
| `not-run` | 51403 | Intentionally unexecuted in J1 tooling smoke |
| `na` | 0 | Source-backed not applicable |
| `blocked` | 0 | Blocked by missing dependency or precondition |

## 2. Counts by Requirement Level

| Level | Verified | Asserted | Ambiguous | Not Run | Total |
|---|---|---|---|---|---|
| `route-entry` | 3 | 0 | 0 | 42 | 45 |
| `definition` | 46 | 4 | 20 | 213 | 283 |
| `component-instance` | 91 | 8 | 36 | 2134 | 2269 |
| `component-state` | 91 | 8 | 36 | 20286 | 20421 |
| `native-instance` | 0 | 156 | 125 | 2619 | 2900 |
| `native-state` | 0 | 156 | 125 | 25819 | 26100 |
| `supplemental-capability` | 0 | 0 | 0 | 4 | 4 |
| `supplemental-state` | 0 | 0 | 0 | 77 | 77 |
| `supplemental-route-instance` | 0 | 0 | 0 | 11 | 11 |
| `supplemental-route-state` | 0 | 0 | 0 | 198 | 198 |

## 3. Tooling and Mutation Test Suite

All 13 required mutation checks pass cleanly in `harness/test/verify-coverage.test.cjs`:

1. `remove ID`: Rejects omission of any expanded inventory requirement row.
2. `duplicate ID`: Rejects duplicate rows for the same ID.
3. `add unknown ID`: Rejects rows outside expanded inventory requirements.
4. `forge route`: Rejects evidence citing an artifact from a different route.
5. `forge state`: Rejects state_key mismatches between row and evidence.
6. `forge hash`: Rejects tampered artifact SHA-256 hashes.
7. `forge source`: Rejects mismatched source baseline SHAs.
8. `reuse a node for two natives`: Rejects reusing a single connected DOM node across multiple natives.
9. `claim a colliding/children-slot native verified`: Enforces that children-slot or colliding natives cannot earn verified credit.
10. `forge server absence`: Rejects unproven server absence claims.
11. `assert unsupported verified state`: Rejects non-normal and supplemental states with `unsupported-state-predicate`.
12. `cite another scenario/slot`: Rejects parallel slot entries backed only by a standard page URL.
13. `corrupt artifact paths`: Rejects traversal `..`, absolute paths, and nonexistent artifact references.

## 4. Unsupported Cases and Limitations for J2

- **Predicates for non-normal states:** J1 only registers verified predicates for `normal` client definitions and unambiguous natives with connected DOM nodes. J2 must specify and independently review any predicate for `empty`, `loading`, `failed`, or supplemental states.
- **Server components:** Server-rendered components without a uniquely proven host marker adapter cannot be verified and remain asserted.
- **Prop and Children Flow:** Arbitrary React prop and children data flow are not reconstructed. Children-slot natives remain asserted or ambiguous.
- **Whole-App Usability:** This tooling report provides attribution validation for J1 tooling smoke only; J2 presentation execution remains required under its own approved plan.
