"""
Config Store — Persistent JSON-backed configuration for Coraxis.

Stores global settings, per-agent LLM config (built-in and custom agents),
teams, and workflows in `data/config.json` (git-ignored). Falls back to
environment variables for API keys when not set explicitly.

Thread-safe via an RLock; writes are atomic (tmp file + replace).
"""

import json
import os
import threading
import copy
from typing import Any, Dict, List, Optional

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(_PROJECT_ROOT, "data")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

BUILTIN_AGENTS = ["researcher", "web_searcher", "analyst", "summarizer"]

PROVIDERS = ["groq", "gemini", "openai", "ollama"]

DEFAULT_MODELS: Dict[str, str] = {
    "groq": "llama-3.1-8b-instant",
    "gemini": "gemini-1.5-flash",
    "openai": "gpt-4o-mini",
    "ollama": "llama3.1",
}

ENV_KEY_MAP: Dict[str, str] = {
    "groq": "GROQ_API_KEY",
    "gemini": "GOOGLE_API_KEY",
    "openai": "OPENAI_API_KEY",
}

TOOL_REGISTRY = [
    {"id": "duckduckgo_search", "label": "Web Search (DuckDuckGo)", "needs_tracker": False},
    {"id": "fetch_page", "label": "Page Fetch & Extract", "needs_tracker": False},
    {"id": "recall_memory", "label": "Semantic Memory Recall", "needs_tracker": False},
    {"id": "register_claim", "label": "Register Claim (Citations)", "needs_tracker": True},
    {"id": "aas_catalog", "label": "AAS Skill Catalog Discovery", "needs_tracker": False},
]

_lock = threading.RLock()
_cache: Optional[Dict[str, Any]] = None

DEFAULT_CONFIG: Dict[str, Any] = {
    "use_global_key": False,
    "global_provider": "groq",
    "global_key": "",
    "agents": {
        "researcher": {"provider": "groq", "model": "", "api_key": "", "temperature": 0.2, "max_tokens": 4096, "base_url": ""},
        "web_searcher": {"provider": "groq", "model": "", "api_key": "", "temperature": 0.2, "max_tokens": 4096, "base_url": ""},
        "analyst": {"provider": "groq", "model": "", "api_key": "", "temperature": 0.2, "max_tokens": 4096, "base_url": ""},
        "summarizer": {"provider": "groq", "model": "", "api_key": "", "temperature": 0.2, "max_tokens": 4096, "base_url": ""},
    },
    "custom_agents": [],
    "teams": [],
    "workflow_templates": [],
}


def _deep_merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge overrides into a copy of base."""
    merged = copy.deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load() -> Dict[str, Any]:
    """Load config from disk into cache (must hold lock)."""
    global _cache
    if _cache is not None:
        return _cache
    data: Dict[str, Any] = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    # Ensure all sections exist
    for section, default in DEFAULT_CONFIG.items():
        if section not in data:
            data[section] = copy.deepcopy(default)
    _cache = data
    return _cache


def _save() -> None:
    """Atomically persist the cached config to disk (must hold lock)."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp_path = CONFIG_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(_cache, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, CONFIG_PATH)


def get_config() -> Dict[str, Any]:
    """Return a deep copy of the full configuration."""
    with _lock:
        cfg = _load()
        return copy.deepcopy(cfg)


def get_section(name: str) -> Any:
    with _lock:
        cfg = _load()
        return copy.deepcopy(cfg.get(name))


def update_section(name: str, value: Any) -> None:
    with _lock:
        cfg = _load()
        cfg[name] = copy.deepcopy(value)
        _save()


def _normalize_agent_config(agent_cfg: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "provider": agent_cfg.get("provider", "groq"),
        "model": agent_cfg.get("model", ""),
        "api_key": agent_cfg.get("api_key", ""),
        "temperature": float(agent_cfg.get("temperature", 0.2)),
        "max_tokens": int(agent_cfg.get("max_tokens", 4096)),
        "base_url": agent_cfg.get("base_url", ""),
    }


def get_agent_config(agent_name: str) -> Optional[Dict[str, Any]]:
    """Get config for a built-in or custom agent by name."""
    with _lock:
        cfg = _load()
        if agent_name in cfg["agents"]:
            return _normalize_agent_config(cfg["agents"][agent_name])
        for ca in cfg["custom_agents"]:
            if ca.get("name") == agent_name:
                merged = dict(ca)
                merged.update(_normalize_agent_config(ca))
                return merged
        return None


def set_agent_config(agent_name: str, agent_cfg: Dict[str, Any]) -> None:
    """Set config for a built-in or custom agent."""
    with _lock:
        cfg = _load()
        norm = _normalize_agent_config(agent_cfg)
        if agent_name in BUILTIN_AGENTS or agent_name in cfg["agents"]:
            cfg["agents"][agent_name] = norm
        else:
            # Custom agent
            for ca in cfg["custom_agents"]:
                if ca.get("name") == agent_name:
                    ca.update(norm)
                    ca["role"] = agent_cfg.get("role", ca.get("role", ""))
                    ca["goal"] = agent_cfg.get("goal", ca.get("goal", ""))
                    ca["backstory"] = agent_cfg.get("backstory", ca.get("backstory", ""))
                    ca["tools"] = agent_cfg.get("tools", ca.get("tools", []))
                    _save()
                    return
            cfg["custom_agents"].append({
                "name": agent_name,
                "role": agent_cfg.get("role", ""),
                "goal": agent_cfg.get("goal", ""),
                "backstory": agent_cfg.get("backstory", ""),
                "tools": agent_cfg.get("tools", []),
                **norm,
            })
        _save()


def delete_custom_agent(agent_name: str) -> bool:
    """Delete a custom agent. Built-in agents cannot be deleted."""
    with _lock:
        cfg = _load()
        before = len(cfg["custom_agents"])
        cfg["custom_agents"] = [a for a in cfg["custom_agents"] if a.get("name") != agent_name]
        deleted = len(cfg["custom_agents"]) < before
        if deleted:
            # Remove from teams referencing it
            for team in cfg["teams"]:
                team["agent_names"] = [n for n in team.get("agent_names", []) if n != agent_name]
            _save()
        return deleted


def list_custom_agents() -> List[Dict[str, Any]]:
    with _lock:
        return copy.deepcopy(_load()["custom_agents"])


# ─── Teams ───

def _next_id(items: List[Dict[str, Any]]) -> int:
    return max((item.get("id", 0) for item in items), default=0) + 1


def list_teams() -> List[Dict[str, Any]]:
    with _lock:
        return copy.deepcopy(_load()["teams"])


def get_team(team_id: int) -> Optional[Dict[str, Any]]:
    with _lock:
        for t in _load()["teams"]:
            if t.get("id") == team_id:
                return copy.deepcopy(t)
    return None


def upsert_team(team: Dict[str, Any]) -> Dict[str, Any]:
    """Create or update a team. Returns the stored team."""
    with _lock:
        cfg = _load()
        teams: List[Dict[str, Any]] = cfg["teams"]
        tid = team.get("id")
        if tid:
            for i, t in enumerate(teams):
                if t.get("id") == tid:
                    team["id"] = tid
                    teams[i] = copy.deepcopy(team)
                    _save()
                    return copy.deepcopy(team)
        team["id"] = _next_id(teams)
        teams.append(copy.deepcopy(team))
        _save()
        return copy.deepcopy(team)


def delete_team(team_id: int) -> bool:
    with _lock:
        cfg = _load()
        before = len(cfg["teams"])
        cfg["teams"] = [t for t in cfg["teams"] if t.get("id") != team_id]
        deleted = len(cfg["teams"]) < before
        if deleted:
            _save()
        return deleted


# ─── Global settings ───

def get_global_settings() -> Dict[str, Any]:
    with _lock:
        cfg = _load()
        return {
            "use_global_key": cfg["use_global_key"],
            "global_provider": cfg["global_provider"],
            "global_key": cfg["global_key"],
        }


def set_global_settings(use_global_key: bool, global_provider: str, global_key: str = "") -> None:
    with _lock:
        cfg = _load()
        cfg["use_global_key"] = bool(use_global_key)
        cfg["global_provider"] = global_provider
        if global_key and global_key.strip():
            cfg["global_key"] = global_key.strip()
        _save()


# ─── API key resolution (env fallback) ───

def resolve_api_key(provider: str, explicit_key: str = "") -> str:
    """Resolve API key: explicit > stored global (if enabled) > env var."""
    if explicit_key and explicit_key.strip():
        return explicit_key.strip()
    with _lock:
        cfg = _load()
        if cfg.get("use_global_key") and cfg.get("global_key"):
            return cfg["global_key"].strip()
    env_var = ENV_KEY_MAP.get(provider, "")
    return os.getenv(env_var, "") if env_var else ""


def _get_env_fallback(provider: str) -> str:
    env_var = ENV_KEY_MAP.get(provider, "")
    return os.getenv(env_var, "") if env_var else ""


def reset_cache() -> None:
    """Drop the in-memory cache (used by tests)."""
    global _cache
    with _lock:
        _cache = None
