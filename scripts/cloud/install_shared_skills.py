#!/usr/bin/env python3
"""Clone shared skills once and add non-destructive user-level directory links."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

REPOSITORY = "https://github.com/Netke237/claude-dotfiles.git"


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def checkout_skills(checkout: Path, update: bool) -> list[Path]:
    if not os.path.lexists(checkout):
        checkout.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--depth", "1", "--branch", "main",
                        REPOSITORY, str(checkout)], check=True)
    else:
        if not (checkout / ".git").exists():
            raise RuntimeError(f"Preserved existing non-checkout path: {checkout}")
        origin = git("-C", str(checkout), "remote", "get-url", "origin")
        if origin not in (REPOSITORY, REPOSITORY.removesuffix(".git"),
                          "git@github.com:Netke237/claude-dotfiles.git"):
            raise RuntimeError("Preserved checkout: origin is not the shared skills repository")
        if update:
            if git("-C", str(checkout), "status", "--porcelain"):
                raise RuntimeError("Preserved checkout: commit/stash changes before --update")
            if git("-C", str(checkout), "branch", "--show-current") != "main":
                raise RuntimeError("Preserved checkout: --update requires the main branch")
            subprocess.run(["git", "-C", str(checkout), "fetch", "origin", "main"], check=True)
            # A fast-forward alone can overwrite ignored local files. Protect them too.
            subprocess.run(["git", "-C", str(checkout), "merge", "--ff-only",
                            "--no-overwrite-ignore", "FETCH_HEAD"],
                           check=True)
    skills = sorted(path.parent for path in (checkout / "skills").glob("*/SKILL.md"))
    if not skills:
        raise RuntimeError("No skills/*/SKILL.md found; no links installed")
    print(f"Shared checkout revision: {git('-C', str(checkout), 'rev-parse', 'HEAD')}")
    return skills


def link_shared_root(source: Path, destinations: list[Path]) -> list[str]:
    conflicts = []
    source = source.resolve(strict=True)
    for destination in dict.fromkeys(destinations):
        destination.mkdir(parents=True, exist_ok=True)
        target = destination / "claude-dotfiles"
        if os.path.lexists(target):
            if target.is_symlink() and target.resolve() == source:
                print(f"Already linked: {target}")
                continue
            conflicts.append(str(target))
            print(f"Preserved conflict: {target}", file=sys.stderr)
            continue
        # Link the whole source tree: new skills need no additional links.
        # No force, removal, replacement, or skill-content copying.
        target.symlink_to(source, target_is_directory=True)
        print(f"Linked: {target} -> {source}")
    return conflicts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path,
                        default=Path.home() / ".local/share/codex/claude-dotfiles")
    parser.add_argument("--codex-home", type=Path,
                        default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")))
    parser.add_argument("--user-skills", type=Path, default=Path.home() / ".agents/skills")
    parser.add_argument("--update", action="store_true", help="Explicit clean main fast-forward")
    args = parser.parse_args()
    skills = checkout_skills(args.checkout.expanduser().absolute(), args.update)
    conflicts = link_shared_root(skills[0].parent,
                                [(args.codex_home.expanduser() / "skills").absolute(),
                                 args.user_skills.expanduser().absolute()])
    print(f"Shared skills: {len(skills)}; preserved conflicts: {len(conflicts)}")
    return 2 if conflicts else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Installation incomplete: {error}", file=sys.stderr)
        sys.exit(1)
