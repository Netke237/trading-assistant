#!/bin/bash
# SessionStart hook — Bamendjou.
#
# Two jobs, both learned the hard way:
#   1. Install dependencies. `backend/.venv` and `frontend/node_modules` are
#      gitignored, so a fresh remote container has neither and a session burns
#      its first minutes rebuilding them before it can run a single test.
#   2. Print the project state and FAIL LOUDLY on drift. Kenneth works across
#      two Claude accounts and many sessions; without one authoritative,
#      code-verified state file, each session re-derives the big picture and
#      gets it subtly wrong. `scripts/state.py` is that file's enforcer.
set -uo pipefail

cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}" || exit 0

# Dependency install is remote-only: on Kenneth's own machine these already
# exist and a reinstall would be pure latency.
if [ "${CLAUDE_CODE_REMOTE:-}" = "true" ]; then
  if [ ! -x backend/.venv/bin/python ]; then
    echo "[session-start] creating backend venv…"
    python3 -m venv backend/.venv >/dev/null 2>&1
    backend/.venv/bin/pip install -q --disable-pip-version-check \
      -r backend/requirements.txt >/dev/null 2>&1 \
      && echo "[session-start] backend deps installed" \
      || echo "[session-start] WARNING: backend pip install failed — run it by hand"
  fi
  if [ ! -d frontend/node_modules ]; then
    echo "[session-start] installing frontend deps…"
    (cd frontend && npm install --no-audit --no-fund >/dev/null 2>&1) \
      && echo "[session-start] frontend deps installed" \
      || echo "[session-start] WARNING: npm install failed — run it by hand"
  fi
fi

# Who is working on what right now. Printed BEFORE the (long) state table so
# it lands in the visible preview. Never fails the hook.
if [ -f scripts/claim.py ]; then
  python3 scripts/claim.py list --quiet
fi

# Always print the state, local or remote. Non-zero exit means a declared
# status disagrees with the code — surfaced, never swallowed.
if [ -f scripts/state.py ]; then
  python3 scripts/state.py || {
    echo ""
    echo "[session-start] ^^ STATE DRIFT. Reconcile docs/superpowers/PROJECT_STATE.json"
    echo "[session-start]    with the code before trusting any status claim in it."
  }
fi

exit 0
