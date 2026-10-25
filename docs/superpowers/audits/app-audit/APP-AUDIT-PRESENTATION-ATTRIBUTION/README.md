# APP-AUDIT-PRESENTATION-ATTRIBUTION — J1 Tooling & Verification Guide

This directory contains the conservative presentation attribution tooling, candidate source/target maps, fiber census, production smoke harness, and fail-closed coverage verifier for Phase J1 of the application presentation audit (`#529`).

> **Tooling Notice:** All artifacts generated in J1 carry `purpose: tooling-self-test`. They prove the correctness and conservative fail-closed enforcement of attribution algorithms on sample routes (`/dashboard`, `/settings`, and a dialog lifecycle on `/screener/step-3-direction`). They certify zero whole-app presentation usability, keyboard accessibility, or state coverage. Full presentation audit execution belongs to J2.

---

## 1. Architecture & Pipeline

The attribution harness consists of six focused CommonJS modules and a dedicated test suite in `harness/`:

```
docs/superpowers/audits/app-audit/APP-AUDIT-PRESENTATION-ATTRIBUTION/
├── fixtures/
│   ├── api/                     # Synthetic JSON API fixture responses (regime, watchlist, portfolio, etc.)
│   ├── seeds/                   # Synthetic isolated localStorage/sessionStorage seeds
│   └── source/                  # Synthetic test cases for source maps
├── harness/
│   ├── census.cjs               # React 19 Fiber tree crawler and host DOM mapper
│   ├── map-common.cjs           # In-memory TypeScript compiler environment & frozen git-show loader
│   ├── smoke.cjs                # Production Next.js build (--no-mangling) & network-isolated smoke runner
│   ├── source-map.cjs           # AST static analysis: client/server boundaries, JSX ownership, collisions
│   ├── target-map.cjs           # AST target analysis: direct api.* HTTP methods/paths and store reads
│   ├── verify-coverage.cjs      # Pure expansion, fail-closed verifier, and report generator
│   └── test/
│       ├── census.test.cjs      # Fiber unwrapping, alternate rejection, disconnected DOM rejection
│       ├── frozen-maps.test.cjs # Baseline byte reproducibility & historical ID preservation
│       ├── maps.test.cjs        # AST edge cases, ContextRail callsites, syntax collisions
│       ├── smoke.test.cjs       # Shadow-module exclusion, lockfile/manifest integrity, seed-once guard
│       └── verify-coverage.test.cjs # Recomputation, join validation, and 13 fail-closed mutation tests
├── samples/                     # Smoke observation captures (tooling-self-test only)
├── provenance.json              # Exact build flags, Node, Chromium, Next, and input hashes
├── source-map.json              # Candidate source declaration & JSX ownership map
├── target-map.json              # Candidate direct API and store-read target map
├── tooling-report.json          # Machine-readable reconciliation summary across all 10 requirement levels
├── tooling-report.md            # Human-readable attribution tooling report
└── README.md                    # This document
```

---

## 2. Deterministic Baseline Inputs

All source analysis operates strictly against frozen git baseline `4a74d186468afe0a7fc4c53e785b24b5c1f72b42` via `git show` into an in-memory virtual TypeScript environment (`map-common.cjs`), completely isolated from any uncommitted changes in the working directory.

- Inventory source: `docs/superpowers/audits/app-audit/APP-AUDIT-INVENTORY/inventory.json`
- Supplemental contracts: `docs/superpowers/audits/app-audit/APP-AUDIT-INVENTORY/supplemental-capability-contracts.json`
- Target sources: `frontend/tsconfig.json`, `frontend/lib/api.ts`, and frontend TypeScript/TSX sources.

---

## 3. CLI Commands

### Running Harness Tests
Run the entire Node test suite:
```bash
node --test docs/superpowers/audits/app-audit/APP-AUDIT-PRESENTATION-ATTRIBUTION/harness/test/*.test.cjs
```

Or run individual test modules:
```bash
node --test docs/superpowers/audits/app-audit/APP-AUDIT-PRESENTATION-ATTRIBUTION/harness/test/verify-coverage.test.cjs
node --test docs/superpowers/audits/app-audit/APP-AUDIT-PRESENTATION-ATTRIBUTION/harness/test/census.test.cjs
node --test docs/superpowers/audits/app-audit/APP-AUDIT-PRESENTATION-ATTRIBUTION/harness/test/smoke.test.cjs
node --test docs/superpowers/audits/app-audit/APP-AUDIT-PRESENTATION-ATTRIBUTION/harness/test/maps.test.cjs
```

### Generating Candidate Maps
Generate `source-map.json`:
```bash
node docs/superpowers/audits/app-audit/APP-AUDIT-PRESENTATION-ATTRIBUTION/harness/source-map.cjs --out docs/superpowers/audits/app-audit/APP-AUDIT-PRESENTATION-ATTRIBUTION/source-map.json
```

Generate `target-map.json`:
```bash
node docs/superpowers/audits/app-audit/APP-AUDIT-PRESENTATION-ATTRIBUTION/harness/target-map.cjs --out docs/superpowers/audits/app-audit/APP-AUDIT-PRESENTATION-ATTRIBUTION/target-map.json
```

### Running Coverage Verifier & Generating Tooling Reports
Reconcile smoke samples against inventory and regenerate `tooling-report.json` and `tooling-report.md`:
```bash
node docs/superpowers/audits/app-audit/APP-AUDIT-PRESENTATION-ATTRIBUTION/harness/verify-coverage.cjs
```

---

## 4. Fail-Closed Coverage Verifier (`verify-coverage.cjs`)

The verifier recomputes all requirement IDs from inventory joins and the 9-state template (`conservative-nine-state-v1`):
1. `route-entry` (45 entries)
2. `definition` (283 definitions)
3. `component-instance` (2,269 instances)
4. `component-state` (20,421 states)
5. `native-instance` (2,900 instances)
6. `native-state` (26,100 states)
7. `supplemental-capability` (4 capabilities)
8. `supplemental-state` (77 states)
9. `supplemental-route-instance` (11 instances)
10. `supplemental-route-state` (198 states)

Total requirement rows: **52,308 rows**.

Every row is verified for exactly one base disposition:
- `observed-verified`: Proved by registered predicate (unique census mounted tie or proven host marker).
- `observed-asserted`: Documented with actual evidence and non-empty explanation (unproven server components, children-slot natives).
- `observed-ambiguous`: Duplicate census component names or route signature collisions.
- `rendered-untargeted`: Rendered without direct target binding.
- `not-triggered`: Scenario executed but conditional branch unreached.
- `not-run`: Unexecuted in current tooling smoke.
- `na`: Source-backed non-applicability.
- `blocked`: Precondition blocked.

### Mutation Test Suite
The 13 mutations tested and verified in `verify-coverage.test.cjs`:
1. `remove ID`: Rejects omission of any expanded inventory requirement row.
2. `duplicate ID`: Rejects duplicate rows for the same requirement ID.
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

---

## 5. Unsupported Cases & Critical Limitations for J2

Phase J2 implementers and auditors must observe the following conservative limitations established in J1:

1. **State Predicates for Non-Normal States:**
   J1 only registers verified predicates for `normal` client definition mounting and connected DOM host nodes. Any attempt to mark `empty`, `loading`, `failed`, `legacy`, `zero`, `stale`, `reload`, or supplemental states as `observed-verified` fails closed with `unsupported-state-predicate`. J2 must specify and independently review any predicate before claiming verified credit on non-normal states.
2. **Server-Rendered Components:**
   Server components (e.g., `ContextRail`) do not have client fibers in the census. Generic host elements (e.g. `<aside>`, `<section>`) do not prove identity. Unproven server components must downgrade to `observed-asserted`, never claimed absent or verified without a reviewed marker adapter.
3. **Children-Slot Attribution:**
   Natives passed through children slots (`TableRow`, `SectionCard`, `RailSection`) cannot be verified merely because a matching node is inside an ancestor fiber. They remain `observed-asserted` with DOM evidence.
4. **Signature Collisions:**
   Identical native signatures within a route remain `observed-ambiguous`, even when multiple matching DOM nodes render. DOM order or node count cannot be used to disambiguate.
5. **DOM Node Single-Credit Rule:**
   Each connected host DOM node in an observation can credit at most one native instance.
6. **Parallel Slots and Route Boundaries:**
   A page URL alone cannot identify a parallel slot (e.g. `@contextRail`) or boundary (`error.tsx`, `loading.tsx`). Explicit slot evidence is required.
