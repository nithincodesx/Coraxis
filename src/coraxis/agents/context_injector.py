"""CONTEXT.md parser and session-state injector.

Reads the repository root's ``CONTEXT.md`` (if present) and extracts the
frontmatter block so it can be prepended to every agent's system prompt.
If the file is missing or empty, falls back to a short ``git log`` /
``git status`` summary so an agent never starts blind.

Usage::

    from coraxis.agents.context_injector import session_context
    injection = session_context()   # str, safe to prepend to a backstory
"""

from __future__ import annotations

import subprocess
from pathlib import Path

#: Repository root: this file lives at src/coraxis/agents/, three levels up.
REPO_ROOT = Path(__file__).resolve().parents[3]
CONTEXT_PATH = REPO_ROOT / "CONTEXT.md"

#: Frontmatter delimiters.
_FRONTMARK = "---\n"


def _read_context() -> str | None:
    """Return the raw frontmatter block, or None if unavailable."""
    try:
        text = CONTEXT_PATH.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.strip():
        return None
    if not text.startswith(_FRONTMARK):
        return None
    end = text.find(_FRONTMARK, len(_FRONTMARK))
    if end == -1:
        return None
    return text[len(_FRONTMARK) : end].strip()


def _git_summary() -> str:
    """Best-effort summary of the last three commits and dirty files."""
    lines: list[str] = []
    for args in (("git", "log", "-n", "3", "--oneline"), ("git", "status", "--porcelain")):
        try:
            result = subprocess.run(
                args,
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                label = args[1]
                lines.append(f"### {label}")
                lines.append(result.stdout.strip())
        except (OSError, subprocess.TimeoutExpired):
            pass
    if not lines:
        return "No git history available."
    return "\n".join(lines)


def session_context() -> str:
    """Build a context-injection string for the LLM system prompt.

    Prefers CONTEXT.md frontmatter; falls back to ``git log`` + ``git status``.
    Returns an empty string only when neither source yields anything.
    """
    frontmatter = _read_context()
    if frontmatter:
        return (
            "## Session context (CONTEXT.md)\n"
            f"{frontmatter}\n"
            "\n"
            "Read this block first and treat it as the authoritative state of "
            "the current work session before responding to any user prompt."
        )

    git = _git_summary()
    if git.strip():
        return (
            "## Session context (git fallback — CONTEXT.md missing)\n"
            f"{git}\n"
            "\n"
            "Use this recent history to reconstruct where work left off."
        )

    return ""
