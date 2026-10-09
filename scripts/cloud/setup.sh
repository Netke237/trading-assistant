#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$repo_root"
if (( $# )); then
    printf '%s\n' 'This wrapper uses default paths. Run the installer/verifier separately for overrides.' >&2
    exit 1
fi

# Provision these runtimes in the cloud image; do not silently choose Python 3.12+.
python_bin="${CLOUD_PYTHON:-python3.11}"
"$python_bin" -c 'import sys; assert sys.version_info[:2] == (3, 11), "Python 3.11 required"'
node -e 'if (process.versions.node.split(".")[0] !== "22") { throw Error("Node 22 required (frontend/.nvmrc)"); }'
command -v git >/dev/null
command -v codex >/dev/null

# Existing proxy, credential injection and CA variables are inherited unchanged.
"$python_bin" scripts/cloud/install_shared_skills.py
"$python_bin" scripts/cloud/verify_shared_skills.py --workspace "$repo_root"

venv_path="$repo_root/.venv-cloud"
if [[ ! -e "$venv_path" && ! -L "$venv_path" ]]; then
    "$python_bin" -m venv "$venv_path"
fi
"$venv_path/bin/python" -c 'import sys; assert sys.version_info[:2] == (3, 11), "Existing venv must use Python 3.11"'
"$venv_path/bin/python" -m pip install -r backend/requirements.txt
npm --prefix frontend ci
"$venv_path/bin/python" scripts/state.py
printf '%s\n' 'Cloud setup complete. See docs/cloud-environment.md for startup commands.'
