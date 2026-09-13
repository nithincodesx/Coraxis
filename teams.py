"""
Custom Teams — CRUD-backed custom agents/teams with a CrewAI runner.

Teams are persisted via utils.config_store. Runs go through an ad-hoc Crew
built from the team's agents; all inter-agent traffic flows through the
event bus / blackboard so the UI can watch agents collaborate live.
"""

import time
import uuid
from typing import Any, Dict, List, Optional

from crewai import Agent, Task, Process, Crew

from utils import config_store, comms
from utils.llm_factory import create_llm
from tools.comms_tools import make_comms_tools
from tools.crew_tools import (
    get_search_tool,
    get_fetch_tool,
    get_recall_tool,
    make_citation_aware_search_tool,
    make_citation_aware_fetch_tool,
    make_register_claim_tool,
)
from tools.aas_tools import get_aas_catalog_tool
from tools.citations import CitationTracker


TOOL_FACTORIES = {
    "duckduckgo_search": lambda tracker: (
        make_citation_aware_search_tool(tracker) if tracker else get_search_tool()
    ),
    "fetch_page": lambda tracker: (
        make_citation_aware_fetch_tool(tracker) if tracker else get_fetch_tool()
    ),
    "recall_memory": lambda tracker: get_recall_tool(),
    "register_claim": lambda tracker: (
        make_register_claim_tool(tracker) if tracker else None
    ),
    "aas_catalog": lambda tracker: get_aas_catalog_tool(),
}


def build_tools(tool_ids: List[str], tracker: Optional[CitationTracker] = None) -> List[Any]:
    tools: List[Any] = []
    for tid in tool_ids:
        factory = TOOL_FACTORIES.get(tid)
        if not factory:
            continue
        tool = factory(tracker)
        if tool is not None:
            tools.append(tool)
    return tools


def build_custom_agent(
    agent_def: Dict[str, Any],
    run_id: str = "",
    tracker: Optional[CitationTracker] = None,
) -> Agent:
    """Build a CrewAI Agent from a stored custom-agent definition."""
    name = agent_def["name"]
    llm = create_llm(name)
    tools = build_tools(agent_def.get("tools", []), tracker)
    tools.extend(make_comms_tools(name, run_id))
    return Agent(
        role=agent_def.get("role") or name,
        goal=agent_def.get("goal") or "Complete assigned tasks well.",
        backstory=agent_def.get("backstory") or f"You are {name}, a capable AI agent.",
        llm=llm,
        verbose=True,
        allow_delegation=False,
        max_iter=5,
        max_retry_limit=2,
        respect_context_window=True,
        tools=tools,
    )


def build_builtin_agent(name: str, run_id: str = "", tracker: Optional[CitationTracker] = None) -> Agent:
    """Rebuild a built-in agent but with comms tools added."""
    from agents import AGENT_CONFIGS

    config = AGENT_CONFIGS[name]
    llm = create_llm(name)
    tools = build_tools({
        "researcher": ["duckduckgo_search", "recall_memory", "aas_catalog"],
        "web_searcher": ["duckduckgo_search", "fetch_page"],
        "analyst": ["recall_memory", "register_claim"],
        "summarizer": [],
    }.get(name, []), tracker)
    tools.extend(make_comms_tools(name, run_id))
    return Agent(
        role=config["role"],
        goal=config["goal"],
        backstory=config["backstory"],
        llm=llm,
        verbose=True,
        allow_delegation=False,
        max_iter=5,
        max_retry_limit=2,
        respect_context_window=True,
        tools=tools,
    )


def resolve_agent(name: str, run_id: str = "", tracker: Optional[CitationTracker] = None) -> Agent:
    """Build an agent by name — built-in or custom."""
    if name in config_store.BUILTIN_AGENTS:
        return build_builtin_agent(name, run_id, tracker)
    agent_def = config_store.get_agent_config(name)
    if not agent_def:
        raise ValueError(f"Unknown agent: {name}")
    return build_custom_agent(agent_def, run_id, tracker)


def run_team(
    team: Dict[str, Any],
    query: str,
    tracker: Optional[CitationTracker] = None,
    callbacks: Optional[list] = None,
) -> Dict[str, Any]:
    """
    Run a team workflow. Returns a summary dict.

    Team shape: {id, name, agent_names: [...], coordinator: str|None,
                 workflow: [{description, agent_name}], coordinator_instructions: str}
    """
    run_id = f"team-{uuid.uuid4().hex[:8]}"
    start = time.time()

    comms.publish("run_started", "system", {"team": team.get("name"), "query": query}, run_id=run_id)

    agent_names: List[str] = team.get("agent_names", [])
    if not agent_names:
        raise ValueError("Team has no agents")

    crew_agents: List[Agent] = []
    for name in agent_names:
        crew_agents.append(resolve_agent(name, run_id, tracker))

    workflow: List[Dict[str, Any]] = team.get("workflow") or []
    tasks: List[Task] = []
    name_to_agent = {a.role: a for a in crew_agents}

    if workflow:
        for i, step in enumerate(workflow):
            agent_name = step.get("agent_name") or agent_names[min(i, len(agent_names) - 1)]
            agent = name_to_agent.get(agent_name)
            if agent is None and agent_name in config_store.BUILTIN_AGENTS:
                # Built-in agents use their canonical role string as key
                for a in crew_agents:
                    if agent_name in a.role.lower() or agent_name == a.role:
                        agent = a
                        break
            if agent is None:
                agent = crew_agents[min(i, len(crew_agents) - 1)]
            tasks.append(Task(
                description=(
                    f"{step.get('description', 'Do your part of the workflow.')}\n\n"
                    f"Overall team goal: {query}\n"
                    f"Coordinate with teammates using send_message / read_inbox, and share "
                    f"results via write_blackboard / read_blackboard."
                ),
                expected_output="A structured, complete output for this step.",
                agent=agent,
            ))
    else:
        # Simple sequential fan-out: each agent handles the query
        for agent in crew_agents:
            tasks.append(Task(
                description=(
                    f"Handle your portion of the team goal: {query}\n"
                    f"Coordinate with teammates using send_message / read_inbox, and share "
                    f"results via write_blackboard / read_blackboard."
                ),
                expected_output="A structured, complete output for your role.",
                agent=agent,
            ))

    coordinator = team.get("coordinator")
    coordinator_instructions = team.get("coordinator_instructions", "")
    if coordinator and coordinator in agent_names:
        # Coordinator gets a final wrap-up task
        coord_agent = next((a for a in crew_agents if coordinator in a.role.lower() or a.role == coordinator), crew_agents[0])
        tasks.append(Task(
            description=(
                f"You are the team coordinator. {coordinator_instructions}\n\n"
                "Review what every teammate produced (use read_inbox and read_blackboard), "
                "resolve conflicts, and produce the final consolidated result for: " + query
            ),
            expected_output="A consolidated final output integrating all teammates' work.",
            agent=coord_agent,
        ))

    crew = Crew(
        agents=crew_agents,
        tasks=tasks,
        process=Process.sequential,
        verbose=True,
        memory=False,
        max_rpm=10,
        callbacks=callbacks or [],
    )

    result = crew.kickoff(inputs={"query": query, "run_id": run_id})
    runtime = time.time() - start

    raw = result.raw if hasattr(result, "raw") else str(result)
    comms.publish("run_completed", "system", {"runtime_seconds": runtime}, run_id=run_id)

    return {
        "run_id": run_id,
        "raw_output": raw,
        "runtime_seconds": runtime,
        "agents_used": agent_names,
        "team_name": team.get("name", ""),
    }
