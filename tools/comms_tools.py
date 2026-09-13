"""
Comms Tools — CrewAI tools that let agents talk to each other and the blackboard.

Injected into built-in and custom agents:
  - send_message: agent-to-agent messaging via the event bus
  - read_inbox:   read messages addressed to this agent
  - write_blackboard / read_blackboard: shared memory store
"""

from typing import Optional, Type
from pydantic import BaseModel, Field
from crewai.tools import BaseTool

from utils import comms


class SendMessageInput(BaseModel):
    to_agent: str = Field(..., description="Name of the agent to message, or 'all' to broadcast")
    message: str = Field(..., description="The message content")


class ReadInboxInput(BaseModel):
    limit: int = Field(default=10, description="Max messages to read")


class BlackboardWriteInput(BaseModel):
    key: str = Field(..., description="Key to store under, e.g. 'findings.subq1'")
    value: str = Field(..., description="Value to store (text)")
    run_id: str = Field(default="", description="Optional run identifier")


class BlackboardReadInput(BaseModel):
    key: str = Field(..., description="Key to read")
    run_id: str = Field(default="", description="Optional run identifier")


class SendMessageTool(BaseTool):
    name: str = "send_message"
    description: str = (
        "Send a message to another agent (or broadcast to 'all'). "
        "Use this to hand off findings, ask questions, or coordinate with teammates."
    )
    args_schema: Type[BaseModel] = SendMessageInput

    def __init__(self, agent_name: str, run_id: str = ""):
        super().__init__()
        self._agent_name = agent_name
        self._run_id = run_id

    def _run(self, to_agent: str, message: str) -> str:
        ev = comms.send_agent_message(self._agent_name, to_agent, message, run_id=self._run_id)
        return f"Message delivered to '{to_agent}' (event {ev['id']})."

    async def _arun(self, to_agent: str, message: str) -> str:
        return self._run(to_agent, message)


class ReadInboxTool(BaseTool):
    name: str = "read_inbox"
    description: str = (
        "Read recent messages sent to you by other agents. "
        "Check this before starting work to see coordination context."
    )
    args_schema: Type[BaseModel] = ReadInboxInput

    def __init__(self, agent_name: str, run_id: str = ""):
        super().__init__()
        self._agent_name = agent_name
        self._run_id = run_id

    def _run(self, limit: int = 10) -> str:
        import json
        inbox = comms.read_inbox(self._agent_name, run_id=self._run_id, limit=limit)
        return json.dumps([
            {"from": e["from_agent"], "message": e["payload"].get("message", "")}
            for e in inbox
        ], ensure_ascii=False)

    async def _arun(self, limit: int = 10) -> str:
        return self._run(limit)


class BlackboardWriteTool(BaseTool):
    name: str = "write_blackboard"
    description: str = (
        "Write a finding, note, or artifact to the shared team blackboard. "
        "Other agents can read it. Use structured keys like 'findings.<topic>'."
    )
    args_schema: Type[BaseModel] = BlackboardWriteInput

    def __init__(self, agent_name: str, run_id: str = ""):
        super().__init__()
        self._agent_name = agent_name
        self._run_id = run_id

    def _run(self, key: str, value: str, run_id: str = "") -> str:
        comms.bb_write(key, value, agent=self._agent_name, run_id=run_id or self._run_id)
        return f"Written to blackboard under '{key}'."

    async def _arun(self, key: str, value: str, run_id: str = "") -> str:
        return self._run(key, value, run_id)


class BlackboardReadTool(BaseTool):
    name: str = "read_blackboard"
    description: str = "Read a value from the shared team blackboard by key."
    args_schema: Type[BaseModel] = BlackboardReadInput

    def __init__(self, agent_name: str, run_id: str = ""):
        super().__init__()
        self._agent_name = agent_name
        self._run_id = run_id

    def _run(self, key: str, run_id: str = "") -> str:
        import json
        entry = comms.bb_read(key)
        if not entry:
            return f"No blackboard entry for '{key}'."
        return json.dumps({"key": key, "agent": entry.get("agent"), "value": entry.get("value")}, ensure_ascii=False)

    async def _arun(self, key: str, run_id: str = "") -> str:
        return self._run(key, run_id)


def make_comms_tools(agent_name: str, run_id: str = "") -> list[BaseTool]:
    """Create the full comms toolset for an agent."""
    return [
        SendMessageTool(agent_name, run_id),
        ReadInboxTool(agent_name, run_id),
        BlackboardWriteTool(agent_name, run_id),
        BlackboardReadTool(agent_name, run_id),
    ]
