#!/usr/bin/env python3
"""Ask Codex app-server to discover every shared skill; never start a model turn."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import shutil
import sys


async def discover(workspace: Path) -> dict:
    executable = shutil.which("codex")
    if not executable:
        raise RuntimeError("Codex CLI is required for real discovery verification")
    process = await asyncio.create_subprocess_exec(
        executable, "app-server", "--listen", "stdio://",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, cwd=workspace,
    )

    async def send(message: dict) -> None:
        process.stdin.write((json.dumps(message) + "\n").encode())
        await process.stdin.drain()

    async def response(request_id: int) -> dict:
        while line := await process.stdout.readline():
            message = json.loads(line)
            if message.get("id") == request_id:
                if "error" in message:
                    raise RuntimeError(f"Codex discovery RPC failed: {message['error']}")
                return message["result"]
        raise RuntimeError("Codex app-server exited before replying")

    async def query() -> dict:
        await send({"id": 1, "method": "initialize", "params": {
            "clientInfo": {"name": "shared_skills_check", "version": "1.0"},
        }})
        await response(1)
        await send({"method": "initialized", "params": {}})
        await send({"id": 2, "method": "skills/list", "params": {
            "cwds": [str(workspace)], "forceReload": True,
        }})
        return await response(2)

    try:
        return await asyncio.wait_for(query(), timeout=45)
    finally:
        # EOF lets the app-server (and a CLI launcher parent) shut down together.
        process.stdin.close()
        try:
            await asyncio.wait_for(process.communicate(), timeout=5)
        except asyncio.TimeoutError:
            if process.returncode is None:
                process.kill()
            await process.communicate()


def check(result: dict, checkout: Path) -> dict:
    expected = {path.resolve() for path in (checkout / "skills").glob("*/SKILL.md")}
    if not expected:
        raise RuntimeError("No expected shared skills found")
    skills = [skill for entry in result["data"] for skill in entry["skills"]]
    found = {Path(skill["path"]).resolve() for skill in skills
             if skill["enabled"] and skill["scope"] == "user"}
    missing = sorted(str(path) for path in expected - found)
    summary = {"expected": len(expected), "discovered": len(expected & found),
               "missing_or_disabled": missing,
               "errors": [error for entry in result["data"] for error in entry["errors"]]}
    print(json.dumps(summary, indent=2))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--checkout", type=Path,
                        default=Path.home() / ".local/share/codex/claude-dotfiles")
    args = parser.parse_args()
    result = asyncio.run(discover(args.workspace.expanduser().resolve(strict=True)))
    summary = check(result, args.checkout.expanduser().resolve(strict=True))
    return 1 if summary["missing_or_disabled"] else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, asyncio.TimeoutError, KeyError, ValueError) as error:
        print(f"Discovery unverified: {error}", file=sys.stderr)
        sys.exit(1)
