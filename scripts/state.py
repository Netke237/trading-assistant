#!/usr/bin/env python3
"""Render and VERIFY docs/superpowers/PROJECT_STATE.json.

The point of this script is drift. A status document that is only prose starts
lying the moment someone builds something and forgets to update it -- which is
exactly how a previous session came to believe pieces were unbuilt that were,
and built that were not.

So every phase in PROJECT_STATE.json carries a `verify` probe: a pattern whose
presence or absence in the real code proves the declared status. This script
runs all of them and exits non-zero when a claim and the codebase disagree.

Usage:
    python3 scripts/state.py           # render + verify (exit 1 on drift)
    python3 scripts/state.py --quiet   # verify only, print nothing when clean

Stdlib only, so it runs before any venv exists.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "docs" / "superpowers" / "PROJECT_STATE.json"

# Statuses that mean "the code for this exists".
SHIPPED = {"shipped", "shipped_unaudited"}

BOLD, DIM, RED, GREEN, YELLOW, RESET = (
    "\033[1m", "\033[2m", "\033[31m", "\033[32m", "\033[33m", "\033[0m"
)

STATUS_STYLE = {
    "shipped":            (GREEN,  "SHIPPED"),
    "shipped_unaudited":  (YELLOW, "SHIPPED*"),
    "not_started":        (DIM,    "not started"),
    "needs_spec":         (DIM,    "needs spec"),
    "in_progress":        (YELLOW, "in progress"),
}


def probe(v: dict) -> tuple[bool, str]:
    """Run one verify probe. Returns (code_says_shipped, detail)."""
    path = ROOT / v["path"]
    if not path.exists():
        return False, f"{v['path']} does not exist"
    text = path.read_text(encoding="utf-8", errors="ignore")
    found = re.search(v["pattern"], text, re.M) is not None
    where = f"{v['pattern']!r} in {v['path']}"
    if v["kind"] == "present":
        return found, ("found " if found else "MISSING ") + where
    if v["kind"] == "defect_marker":
        # The pattern IS the unfixed defect. Finding it proves the work is
        # still outstanding -- the inverse of the other two kinds. Phase F is
        # the case that forced this: `v0_grid` merely EXISTING says nothing
        # about whether the calibration was fixed; the hardcoded `[0.04]`
        # literal is what says it was not.
        return (not found), ("defect still present: " if found else "defect gone: ") + where
    # kind == "absent": the pattern appearing means the thing got built.
    return found, ("found " if found else "absent ") + where


def main() -> int:
    quiet = "--quiet" in sys.argv
    state = json.loads(STATE.read_text(encoding="utf-8"))
    drift: list[str] = []
    unaudited: list[str] = []

    if not quiet:
        print(f"\n{BOLD}Bamendjou — stop-model state{RESET}  "
              f"{DIM}(source: docs/superpowers/PROJECT_STATE.json, updated {state['updated']}){RESET}")
        print(f"{DIM}main {state['main']} · branch {state['working_branch']}{RESET}\n")
        print(f"  {BOLD}{'':<2} {'PHASE':<42} {'STATUS':<13} {'AUDIT':<22}{RESET}")

    for ph in state["phases"]:
        declared_shipped = ph["status"] in SHIPPED
        code_shipped, detail = probe(ph["verify"])

        if ph["verify"]["kind"] == "absent" and ph["verify"].get("means_shipped_if_present"):
            actual_shipped = code_shipped
        else:
            actual_shipped = code_shipped

        if declared_shipped != actual_shipped:
            drift.append(
                f"Phase {ph['id']} ({ph['name']}): declared '{ph['status']}' but the code says "
                f"{'BUILT' if actual_shipped else 'NOT BUILT'} — {detail}"
            )

        rounds, clean = ph["audit_rounds"], ph["audit_clean"]
        if declared_shipped and not clean:
            unaudited.append(f"Phase {ph['id']} ({ph['name']}) — {rounds} round(s) run, none clean")

        if not quiet:
            colour, label = STATUS_STYLE.get(ph["status"], ("", ph["status"]))
            if clean:
                audit = f"{GREEN}clean after {rounds}{RESET}"
            elif rounds:
                audit = f"{RED}{rounds} run, NOT clean{RESET}"
            elif declared_shipped:
                audit = f"{RED}NEVER AUDITED{RESET}"
            else:
                audit = f"{DIM}—{RESET}"
            dep = ph.get("depends_on")
            gate = f" {DIM}(needs {'+'.join(dep)}){RESET}" if dep else ""
            print(f"  {BOLD}{ph['id']:<2}{RESET} {ph['name'][:42]:<42} "
                  f"{colour}{label:<13}{RESET} {audit}{gate}")

    # already_shipped is not a second-class list. It holds work that is finished
    # as CODE, which says nothing about whether it is finished as WORK -- the
    # audit rule applies to every line of it exactly as it applies to a phase.
    # Walking only `phases` is how the stop-cost notation rework came to sit
    # here with audit_clean=false and never once appear in a session's target
    # list: the render showed it as shipped, the UNAUDITED block never named it,
    # and the next session planned an audit around a list that was missing it.
    shipped_items = state.get("already_shipped", [])
    for item in shipped_items:
        if not item.get("audit_clean"):
            rounds = item.get("audit_rounds", 0)
            unaudited.append(
                f"Shipped: {item['name']} — {rounds} round(s) run, none clean"
            )
        # A verify probe is OPTIONAL here (several of these predate the state
        # file and have no single load-bearing marker), but where one is given
        # it is checked exactly as a phase's is. Declaring something shipped is
        # a claim about the code, wherever in the file the claim is written.
        v = item.get("verify")
        if v:
            code_shipped, detail = probe(v)
            if not code_shipped:
                drift.append(
                    f"Shipped item '{item['name']}': declared shipped but the code "
                    f"says NOT BUILT — {detail}"
                )

    if not quiet:
        print(f"\n  {DIM}SHIPPED* = code exists but has never survived an adversarial round.{RESET}")
        if shipped_items:
            print(f"\n  {BOLD}{'':<2} {'ALREADY SHIPPED':<42} {'STATUS':<13} {'AUDIT':<22}{RESET}")
            for item in shipped_items:
                clean = item.get("audit_clean")
                rounds = item.get("audit_rounds", 0)
                if clean:
                    audit = f"{GREEN}clean{RESET}"
                elif rounds:
                    audit = f"{RED}{rounds} run, NOT clean{RESET}"
                else:
                    audit = f"{RED}NEVER AUDITED{RESET}"
                colour = GREEN if clean else YELLOW
                label = "shipped" if clean else "SHIPPED*"
                print(f"  {BOLD}{'·':<2}{RESET} {item['name'][:42]:<42} "
                      f"{colour}{label:<13}{RESET} {audit}")
        if state.get("pending_kenneth"):
            print(f"\n  {BOLD}Waiting on Kenneth:{RESET}")
            for item in state["pending_kenneth"]:
                print(f"    · {item[:110]}")
        if state.get("open_questions"):
            print(f"\n  {BOLD}Open questions:{RESET}")
            for q in state["open_questions"]:
                print(f"    · {q[:110]}")
        print(f"\n  {BOLD}Read first:{RESET}")
        for d in state["authoritative_documents"][:4]:
            print(f"    · {d['path']}")
        print()

    if unaudited:
        print(f"{YELLOW}{BOLD}UNAUDITED WORK — the rule is nothing is done until a round comes back clean:{RESET}")
        for u in unaudited:
            print(f"  {YELLOW}!{RESET} {u}")
        print()

    if drift:
        print(f"{RED}{BOLD}STATE DRIFT — PROJECT_STATE.json disagrees with the code:{RESET}")
        for d in drift:
            print(f"  {RED}x{RESET} {d}")
        print(f"\n  {DIM}Fix the JSON (or the code) before trusting anything else in it.{RESET}\n")
        return 1

    if not quiet:
        print(f"  {GREEN}No drift: every declared status matches the code.{RESET}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
