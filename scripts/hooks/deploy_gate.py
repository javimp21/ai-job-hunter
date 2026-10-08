"""Claude Code hook: no deploy unless the code being deployed is pushed and its tests pass.

Reads the tool call as JSON on stdin. Only commands that run deploy/linux/deploy.sh are checked; anything else passes.
Exit code 2 blocks the command and shows the reason to the agent. A pass is remembered per commit, so a second deploy
of the same commit does not run the suite again.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MARKER = ROOT / ".claude" / "deploy-gate.ok"


def git(*args: str) -> str:
    done = subprocess.run(["git", "-c", f"safe.directory={ROOT.as_posix()}", *args], cwd=ROOT, capture_output=True, text=True)
    return done.stdout.strip()


def block(reason: str) -> int:
    print(f"Deploy blocked: {reason}", file=sys.stderr)
    return 2


def main() -> int:
    try:
        command = str(json.load(sys.stdin).get("tool_input", {}).get("command", ""))
    except (ValueError, AttributeError):
        return 0
    if "deploy/linux/deploy.sh" not in command:
        return 0
    if git("status", "--porcelain", "--untracked-files=no"):
        return block("there are uncommitted changes; commit and push them first (the server deploys origin/main).")
    head = git("rev-parse", "HEAD")
    remote = git("ls-remote", "origin", "refs/heads/main").split("\t")[0]
    if not remote or head != remote:
        return block("HEAD is not what origin/main has; push first (the server deploys origin/main, not this folder).")
    if MARKER.exists() and MARKER.read_text(encoding="utf-8").strip() == head:
        return 0
    tests = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider"], cwd=ROOT, capture_output=True, text=True)
    if tests.returncode != 0:
        tail = "\n".join((tests.stdout + tests.stderr).strip().splitlines()[-25:])
        return block(f"the test suite fails on {head[:9]}.\n{tail}")
    MARKER.write_text(head, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
