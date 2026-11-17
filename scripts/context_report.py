"""Print a short session-context report from git history.

Fallback used when CONTEXT.md is missing or stale. Runs ``git log -n 3
--oneline`` and ``git status --porcelain`` so an agent (or a human) can
reconstruct where work left off.

Usage::

    python scripts/context_report.py
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run(args: list[str]) -> str:
    result = subprocess.run(args, cwd=REPO_ROOT, capture_output=True, text=True)
    return result.stdout.strip()


def main() -> int:
    print("## Recent commits")
    print(_run(["git", "log", "-n", "3", "--oneline"]) or "(no commits)")

    print("\n## Modified / untracked files")
    print(_run(["git", "status", "--porcelain"]) or "(working tree clean)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
