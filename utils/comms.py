"""
Agent Communication Layer — Event Bus + Shared Blackboard.

EventBus: in-process pub/sub with a persistent ring buffer of events.
Blackboard: thread-safe shared key-value store agents read/write during runs.

Every inter-agent message, claim, and lifecycle event flows through here so
the UI can visualize agents talking to each other in real time.
"""

import copy
import json
import os
import threading
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
BLACKBOARD_PATH = os.path.join(DATA_DIR, "blackboard.json")
EVENTS_PATH = os.path.join(DATA_DIR, "events.json")

MAX_EVENTS = 2000
MAX_BLACKBOARD_ENTRIES = 500

_lock = threading.RLock()
_subscribers: List[Callable[[Dict[str, Any]], None]] = []
_events: Deque[Dict[str, Any]] = deque(maxlen=MAX_EVENTS)
_blackboard: Dict[str, Dict[str, Any]] = {}
_loaded = False

# ─── Persistence ───

def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    for path, store in ((EVENTS_PATH, None), (BLACKBOARD_PATH, None)):
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        if path == EVENTS_PATH and isinstance(data, list):
            for ev in data[-MAX_EVENTS:]:
                _events.append(ev)
        elif path == BLACKBOARD_PATH and isinstance(data, dict):
            _blackboard.update(data)


def _persist() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        with open(EVENTS_PATH + ".tmp", "w", encoding="utf-8") as f:
            json.dump(list(_events), f, ensure_ascii=False)
        os.replace(EVENTS_PATH + ".tmp", EVENTS_PATH)
    except Exception:
        pass
    try:
        with open(BLACKBOARD_PATH + ".tmp", "w", encoding="utf-8") as f:
            json.dump(_blackboard, f, ensure_ascii=False)
        os.replace(BLACKBOARD_PATH + ".tmp", BLACKBOARD_PATH)
    except Exception:
        pass


def reset_state() -> None:
    """Clear in-memory comms state (used by tests)."""
    global _loaded
    with _lock:
        _events.clear()
        _blackboard.clear()
        _loaded = True


# ─── Event Bus ───

def subscribe(callback: Callable[[Dict[str, Any]], None]) -> None:
    with _lock:
        if callback not in _subscribers:
            _subscribers.append(callback)


def unsubscribe(callback: Callable[[Dict[str, Any]], None]) -> None:
    with _lock:
        if callback in _subscribers:
            _subscribers.remove(callback)


def publish(
    event_type: str,
    from_agent: str,
    payload: Dict[str, Any],
    to_agent: str = "all",
    run_id: str = "",
) -> Dict[str, Any]:
    """Publish an event to all subscribers and the history buffer."""
    event = {
        "id": f"{time.time_ns()}",
        "type": event_type,
        "run_id": run_id,
        "from_agent": from_agent,
        "to_agent": to_agent,
        "payload": payload,
        "ts": time.time(),
        "time_str": time.strftime("%H:%M:%S"),
    }
    with _lock:
        _ensure_loaded()
        _events.append(event)
        _persist()
        subscribers = list(_subscribers)
    for cb in subscribers:
        try:
            cb(event)
        except Exception:
            pass
    return event


def get_events(limit: int = 100, run_id: str = "", since_ts: float = 0.0) -> List[Dict[str, Any]]:
    """Return recent events, newest last, optionally filtered."""
    with _lock:
        _ensure_loaded()
        events = list(_events)
    if run_id:
        events = [e for e in events if e.get("run_id") == run_id]
    if since_ts:
        events = [e for e in events if e.get("ts", 0) > since_ts]
    return events[-limit:]


def get_message_log(run_id: str = "", limit: int = 100) -> List[Dict[str, Any]]:
    """Return only inter-agent messages (agent-to-agent traffic)."""
    with _lock:
        _ensure_loaded()
        events = list(_events)
    messages = [e for e in events if e.get("type") == "agent_message"]
    if run_id:
        messages = [e for e in messages if e.get("run_id") == run_id]
    return messages[-limit:]


# ─── Blackboard ───

def bb_write(key: str, value: Any, agent: str, run_id: str = "") -> None:
    """Write a value to the shared blackboard."""
    with _lock:
        _ensure_loaded()
        _blackboard[key] = {
            "value": value,
            "agent": agent,
            "run_id": run_id,
            "ts": time.time(),
        }
        # Trim oldest entries if over limit
        if len(_blackboard) > MAX_BLACKBOARD_ENTRIES:
            oldest = sorted(_blackboard.items(), key=lambda kv: kv[1]["ts"])[: len(_blackboard) - MAX_BLACKBOARD_ENTRIES]
            for k, _ in oldest:
                _blackboard.pop(k, None)
        _persist()
    publish("blackboard_write", agent, {"key": key, "value": value}, run_id=run_id)


def bb_read(key: str) -> Optional[Dict[str, Any]]:
    with _lock:
        _ensure_loaded()
        entry = _blackboard.get(key)
        return copy.deepcopy(entry) if entry else None


def bb_list(prefix: str = "", run_id: str = "") -> List[Dict[str, Any]]:
    """List blackboard entries with metadata (not full values)."""
    with _lock:
        _ensure_loaded()
        entries = []
        for key, entry in _blackboard.items():
            if prefix and not key.startswith(prefix):
                continue
            if run_id and entry.get("run_id") != run_id:
                continue
            entries.append({
                "key": key,
                "agent": entry.get("agent"),
                "run_id": entry.get("run_id"),
                "ts": entry.get("ts"),
                "value_preview": str(entry.get("value"))[:200],
            })
        entries.sort(key=lambda e: e["ts"])
        return entries


# ─── Agent messaging (convenience wrappers) ───

def send_agent_message(from_agent: str, to_agent: str, message: str, run_id: str = "") -> Dict[str, Any]:
    """Send a message from one agent to another (or 'all')."""
    return publish(
        "agent_message",
        from_agent=from_agent,
        to_agent=to_agent,
        payload={"message": message},
        run_id=run_id,
    )


def read_inbox(agent_name: str, run_id: str = "", limit: int = 10) -> List[Dict[str, Any]]:
    """Get recent messages addressed to an agent."""
    with _lock:
        _ensure_loaded()
        events = list(_events)
    inbox = [
        e for e in events
        if e.get("type") == "agent_message" and e.get("to_agent") in (agent_name, "all")
        and e.get("from_agent") != agent_name
        and (not run_id or e.get("run_id") == run_id)
    ]
    return inbox[-limit:]
