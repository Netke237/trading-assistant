#!/usr/bin/env python3
"""Export an isolated production benchmark tree; never edit the checkout."""
import argparse
import io
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile

parser = argparse.ArgumentParser()
parser.add_argument('--repo-root', type=Path, default=Path(__file__).resolve().parents[4])
parser.add_argument('--destination', type=Path, required=True)
parser.add_argument('--commit', required=True)
parser.add_argument('--build', action='store_true')
parser.add_argument('--start', type=int, metavar='PORT')
args = parser.parse_args()
assert sys.version_info[:2] == (3, 11), 'Activate the pinned Python 3.11 environment'
repo = args.repo_root.resolve()
destination = args.destination.resolve()
assert not destination.exists(), 'Use a fresh destination to preserve previous measurements'
modules = repo / 'frontend/node_modules'
assert modules.is_dir(), 'Install the locked frontend dependencies first'
archive = subprocess.check_output(['git', 'archive', args.commit, 'frontend', 'backend/tests/fixtures'], cwd=repo)
destination.mkdir(parents=True)
with tarfile.open(fileobj=io.BytesIO(archive)) as source:
    source.extractall(destination, filter='data')
frontend = destination / 'frontend'
(frontend / 'node_modules').symlink_to(modules, target_is_directory=True)
page = frontend / 'app/(frame)/screener/step-6-contracts/page.tsx'
content, count = re.subn(r'const isOpen\s*=\s*expanded === candidate\.symbol;', 'const isOpen = true; // Temporary all-groups benchmark harness', page.read_text())
assert count == 1, 'Benchmark patch no longer matches the source; inspect before adapting'
page.write_text(content)
(destination / 'BENCHMARK_SOURCE.txt').write_text(f'{args.commit}\nPatch: one-open-symbol expression to true in this isolated copy only.\n')
environment = dict(os.environ, NEXT_TELEMETRY_DISABLED='1')
if args.build or args.start:
    assert subprocess.check_output(['node', '--version'], text=True).startswith('v22.'), 'Activate Node 22'
if args.build:
    subprocess.run(['npm', 'run', 'build'], cwd=frontend, env=environment, check=True)
if args.start:
    subprocess.run(['npm', 'run', 'start', '--', '--port', str(args.start)], cwd=frontend, env=environment, check=True)
print(f'Prepared isolated benchmark source: {destination}')
