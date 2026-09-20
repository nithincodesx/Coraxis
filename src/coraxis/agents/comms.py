"""Inter-agent messaging and shared scratch space, scoped to one run.

The previous implementation kept both in module-level globals and rewrote two
JSON files to disk on *every* event, which is a full serialisation of the ring
buffer per message. This version keeps a run's traffic in memory and reports it
through the event sink, so the UI still sees agents collaborating live while
the database handles durability.

Both structures are bounded, and both are keyed by run, so concurrent runs
cannot see each other's messages.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

MAX_MESSAGES = 500
MAX_BLACKBOARD_ENTRIES = 200


@dataclass(slots=True)
class AgentMessage:
    """A message from one agent to another (or to ``all``)."""

    from_agent: str
    to_agent: str
    content: str
    ts: float = field(default_factory=time.time)

    @property
    def time_str(self) -> str:
        return time.strftime("%H:%M:%S", time.localtime(self.ts))

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "message": self.content,
            "ts": self.ts,
            "time_str": self.time_str,
        }


class AgentChannel:
    """Bounded, thread-safe message log and blackboard for a single run."""

    def __init__(
        self,
        *,
        max_messages: int = MAX_MESSAGES,
        max_entries: int = MAX_BLACKBOARD_ENTRIES,
    ) -> None:
        self._lock = threading.RLock()
        self._messages: deque[AgentMessage] = deque(maxlen=max_messages)
        self._blackboard: dict[str, dict[str, Any]] = {}
        self._max_entries = max_entries

    # ── Messaging ────────────────────────────────────────────────────

    def send(self, from_agent: str, to_agent: str, content: str) -> AgentMessage:
        """Post a message. The ring buffer drops the oldest when full."""
        message = AgentMessage(
            from_agent=from_agent or "unknown",
            to_agent=to_agent or "all",
            content=(content or "").strip()[:4000],
        )
        with self._lock:
            self._messages.append(message)
        return message

    def inbox(self, agent: str, limit: int = 10) -> list[AgentMessage]:
        """Recent messages addressed to an agent, excluding its own."""
        with self._lock:
            messages = list(self._messages)
        relevant = [
            message
            for message in messages
            if message.to_agent in (agent, "all") and message.from_agent != agent
        ]
        return relevant[-limit:]

    def transcript(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            messages = list(self._messages)
        return [message.to_dict() for message in messages[-limit:]]

    # ── Blackboard ───────────────────────────────────────────────────

    def post(self, key: str, value: Any, agent: str) -> None:
        """Publish a value other agents can read."""
        key = (key or "").strip()
        if not key:
            return
        with self._lock:
            if key not in self._blackboard and len(self._blackboard) >= self._max_entries:
                # Evict the least recently written entry rather than sorting the
                # whole map on every write.
                oldest = min(self._blackboard.items(), key=lambda item: item[1]["ts"])
                self._blackboard.pop(oldest[0], None)
            self._blackboard[key] = {
                "value": value,
                "agent": agent,
                "ts": time.time(),
            }

    def read(self, key: str) -> Any:
        with self._lock:
            entry = self._blackboard.get(key)
            return entry["value"] if entry else None

    def entries(self, prefix: str = "") -> list[dict[str, Any]]:
        with self._lock:
            snapshot = list(self._blackboard.items())
        return [
            {
                "key": key,
                "agent": entry["agent"],
                "ts": entry["ts"],
                "value_preview": str(entry["value"])[:200],
            }
            for key, entry in sorted(snapshot, key=lambda item: item[1]["ts"])
            if not prefix or key.startswith(prefix)
        ]

    def clear(self) -> None:
        with self._lock:
            self._messages.clear()
            self._blackboard.clear()
