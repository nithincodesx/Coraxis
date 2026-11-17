---
active_agent_target: "CrewAI Research Pipeline"
last_completed_milestone: "Context-injection system installed (CONTEXT.md + parser + fallback)"
current_blocker: "None — workspace freshly oriented"
next_immediate_task: "Resume the Coraxis 2.0 feature you were working on"
last_git_check: null
---

# Detailed Session Log

This file is the authoritative session state for the Coraxis 2.0 codebase.
It is read automatically at the start of every agent session before any
user prompt is answered. Keep it updated as work progresses.

The four built-in agents (researcher, web_searcher, analyst, summarizer)
live in src/coraxis/agents/definitions.py and are assembled by
src/coraxis/agents/crew.py. The CLI entry point is src/coraxis/cli/main.py.
