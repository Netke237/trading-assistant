#!/usr/bin/env bash
# Source this file in each fresh shell to retain the activated Python environment.
cloud_repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    printf '%s\n' 'Use: source scripts/cloud/startup.sh' >&2
    exit 1
fi
if [[ ! -f "$cloud_repo_root/.venv-cloud/bin/activate" ]]; then
    printf '%s\n' 'Run bash scripts/cloud/setup.sh first.' >&2
    return 1
fi
source "$cloud_repo_root/.venv-cloud/bin/activate"
python -c 'import sys; assert sys.version_info[:2] == (3, 11), "Python 3.11 required"' || return 1
cd "$cloud_repo_root" || return 1
python scripts/cloud/verify_shared_skills.py --workspace "$cloud_repo_root" || return 1
if [[ -f .k-session/K-SESSION.md ]]; then
    python .k-session/k_session.py resume || return 1
    printf '%s\n' 'Read .k-session/K-SESSION.md and obtain handoff confirmation before task work.'
fi
python scripts/state.py
