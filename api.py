"""
Kimi — FastAPI Backend Server.
Decoupled backend API wrapping the CrewAI multi-agent research pipeline.
Exposes endpoints for the Next.js frontend and implements custom mocks to capture progress updates.
"""

import sys
import os

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import time
import threading
import uuid
from datetime import datetime
from types import ModuleType
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

# ─── Mock Streamlit for CrewAI & Langchain Imports ───
mock_st = ModuleType("streamlit")
mock_st.set_page_config = lambda *args, **kwargs: None
mock_st.markdown = lambda *args, **kwargs: None
mock_st.sidebar = mock_st
mock_st.columns = lambda *args, **kwargs: [mock_st] * 10
mock_st.divider = lambda *args, **kwargs: None
mock_st.caption = lambda *args, **kwargs: None
mock_st.radio = lambda *args, **kwargs: None
mock_st.text_area = lambda *args, **kwargs: ""
mock_st.text_input = lambda *args, **kwargs: ""
mock_st.button = lambda *args, **kwargs: False
mock_st.checkbox = lambda *args, **kwargs: False
mock_st.slider = lambda *args, **kwargs: 0
mock_st.expander = lambda *args, **kwargs: mock_st
mock_st.progress = lambda *args, **kwargs: None
mock_st.metric = lambda *args, **kwargs: None
mock_st.dataframe = lambda *args, **kwargs: None
mock_st.download_button = lambda *args, **kwargs: None
mock_st.success = lambda *args, **kwargs: None
mock_st.error = lambda *args, **kwargs: None
mock_st.warning = lambda *args, **kwargs: None
mock_st.info = lambda *args, **kwargs: None
mock_st.rerun = lambda *args, **kwargs: None
mock_st.session_state = {}

class StubContext:
    def __enter__(self): return self
    def __exit__(self, exc_type, exc_val, exc_tb): pass
    def update(self, *args, **kwargs): None

mock_st.status = lambda *args, **kwargs: StubContext()
mock_st.spinner = lambda *args, **kwargs: StubContext()
mock_st.container = lambda *args, **kwargs: StubContext()

# Initialize stub configurations
from utils import config_store
from utils.llm_factory import AgentLLMConfig

cs = config_store.get_config()

def _rebuild_session():
    """Rebuild the mock session_state dict from the persistent config store."""
    global cs
    cs = config_store.get_config()
    mock_st.session_state.clear()
    mock_st.session_state.update({
        "llm_config": {
            name: AgentLLMConfig(**cfg) for name, cfg in cs["agents"].items()
        },
        "use_global_key": cs["use_global_key"],
        "global_key": cs["global_key"],
        "global_provider": cs["global_provider"],
        "research_history": mock_st.session_state.get("research_history", []),
    })

_rebuild_session()

sys.modules["streamlit"] = mock_st


# ─── Mock timeline & activity feed components to capture updates ───
class GlobalState:
    def __init__(self):
        self.is_running = False
        self.run_query = ""
        self.run_timestamp = ""
        self.run_id = ""
        self.final_report = ""
        self.report_stats = {}
        self.citation_tracker = None
        self.activity_feed = []
        
        self.agent_states = {
            "researcher": {"status": "pending", "progress": 0, "start_time": 0.0, "end_time": 0.0, "error_msg": ""},
            "web_searcher": {"status": "pending", "progress": 0, "start_time": 0.0, "end_time": 0.0, "error_msg": ""},
            "analyst": {"status": "pending", "progress": 0, "start_time": 0.0, "end_time": 0.0, "error_msg": ""},
            "summarizer": {"status": "pending", "progress": 0, "start_time": 0.0, "end_time": 0.0, "error_msg": ""},
        }

state = GlobalState()


def _current_run_id() -> str:
    return getattr(state, "run_id", "")

# Mocking modules in sys.modules before imports occur
mock_timeline = ModuleType("components.timeline")
mock_activity = ModuleType("components.activity_feed")

# Import comms AFTER app-path is set up but before mocks are used
from utils import comms

def mock_start_agent(agent_key: str):
    state.agent_states[agent_key]["status"] = "running"
    state.agent_states[agent_key]["progress"] = 0
    state.agent_states[agent_key]["start_time"] = time.time()
    state.agent_states[agent_key]["end_time"] = 0.0
    state.agent_states[agent_key]["error_msg"] = ""
    comms.publish("agent_started", agent_key, {"agent": agent_key}, run_id=_current_run_id())

def mock_update_agent_progress(agent_key: str, progress: int):
    state.agent_states[agent_key]["progress"] = max(0, min(100, progress))

def mock_complete_agent(agent_key: str, success: bool = True, error: str = ""):
    state.agent_states[agent_key]["status"] = "done" if success else "error"
    state.agent_states[agent_key]["progress"] = 100 if success else state.agent_states[agent_key]["progress"]
    state.agent_states[agent_key]["end_time"] = time.time()
    state.agent_states[agent_key]["error_msg"] = error
    comms.publish(
        "agent_completed" if success else "agent_failed",
        agent_key,
        {"agent": agent_key, "error": error},
        run_id=_current_run_id(),
    )

class MockAgentState:
    def __init__(self, key):
        self.key = key
    @property
    def status(self): return state.agent_states[self.key]["status"]
    @property
    def progress(self): return state.agent_states[self.key]["progress"]
    @property
    def start_time(self): return state.agent_states[self.key]["start_time"]
    @property
    def end_time(self): return state.agent_states[self.key]["end_time"]
    @property
    def error_msg(self): return state.agent_states[self.key]["error_msg"]
    @property
    def elapsed(self):
        if self.start_time == 0: return 0.0
        end = self.end_time or time.time()
        return end - self.start_time
    @property
    def elapsed_str(self):
        e = self.elapsed
        if e < 60: return f"{e:.1f}s"
        return f"{int(e//60)}m {int(e%60)}s"

def mock_reset_timeline():
    for k in state.agent_states:
        state.agent_states[k] = {"status": "pending", "progress": 0, "start_time": 0.0, "end_time": 0.0, "error_msg": ""}

mock_timeline.start_agent = mock_start_agent
mock_timeline.update_agent_progress = mock_update_agent_progress
mock_timeline.complete_agent = mock_complete_agent
mock_timeline.get_agent_state = lambda key: MockAgentState(key)
mock_timeline.reset_timeline = mock_reset_timeline
mock_timeline.AGENT_ORDER = [
    ("researcher", "🔬", "Researcher"),
    ("web_searcher", "🔍", "Web Searcher"),
    ("analyst", "📊", "Analyst"),
    ("summarizer", "📝", "Summarizer"),
]

def mock_add_activity(agent: str, message: str, level: str = "info"):
    state.activity_feed.append({
        "timestamp": time.time(),
        "time_str": datetime.now().strftime("%H:%M:%S"),
        "agent": agent,
        "message": message,
        "level": level
    })
    if len(state.activity_feed) > 100:
        state.activity_feed = state.activity_feed[-100:]
    # Mirror activity into the comms bus so the UI feed sees pipeline events
    comms.publish(
        "activity",
        agent,
        {"message": message, "level": level},
        run_id=_current_run_id(),
    )

mock_activity.add_activity = mock_add_activity
mock_activity.clear_activity_feed = lambda: state.activity_feed.clear()
mock_activity.init_activity_feed = lambda: None
mock_activity.log_agent_start = lambda agent_key, detail="": mock_add_activity(agent_key, f"{detail}", "info")
mock_activity.log_agent_progress = lambda agent_key, detail: mock_add_activity(agent_key, detail, "info")
mock_activity.log_agent_complete = lambda agent_key, detail="": mock_add_activity(agent_key, f"Completed — {detail}" if detail else "Completed", "success")
mock_activity.log_agent_error = lambda agent_key, error: mock_add_activity(agent_key, f"Error: {error}", "error")

sys.modules["components.timeline"] = mock_timeline
sys.modules["components.activity_feed"] = mock_activity


# ─── FastAPI Application Setup ───
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from utils.streaming import reset_streaming_handler, get_streaming_handler
from tasks import create_crew
from tasks import FinalReport
from tools.citations import CitationTracker
import asyncio
import json as _json
from fastapi.responses import StreamingResponse
from teams import resolve_agent, run_team as teams_run_team

app = FastAPI(title="Kimi Multi-Agent Research API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Pydantic Request Models ───
class AgentConfigDTO(BaseModel):
    provider: str
    model: str
    api_key: str = ""

class ConfigDTO(BaseModel):
    use_global_key: bool
    global_provider: str
    global_key: str = ""
    agents: Dict[str, AgentConfigDTO]

class AgentDefDTO(BaseModel):
    name: str
    role: str = ""
    goal: str = ""
    backstory: str = ""
    provider: str = "groq"
    model: str = ""
    api_key: str = ""
    temperature: float = 0.2
    max_tokens: int = 4096
    base_url: str = ""
    tools: List[str] = Field(default_factory=list)

class TeamDTO(BaseModel):
    id: Optional[int] = None
    name: str
    agent_names: List[str] = Field(default_factory=list)
    coordinator: Optional[str] = None
    coordinator_instructions: str = ""
    workflow: List[Dict[str, Any]] = Field(default_factory=list)

class TeamRunDTO(BaseModel):
    query: str

class KeyTestDTO(BaseModel):
    provider: str
    api_key: str = ""
    model: str = ""

class ResearchDTO(BaseModel):
    query: str
    max_sources: int = 5
    min_confidence: float = 0.3
    include_memory: bool = True


# ─── Endpoint Handlers ───

@app.get("/api/health")
def health_check():
    """System health & readiness check endpoint."""
    session = mock_st.session_state
    providers_status = {}
    from utils.llm_factory import _get_env_fallback
    for prov in ["groq", "gemini", "openai", "ollama"]:
        key = _get_env_fallback(prov)
        providers_status[prov] = {
            "available": True,
            "has_key": bool(key or session.get("global_key") if session.get("use_global_key") else False)
        }
    return {
        "status": "healthy",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "is_running": state.is_running,
        "providers": providers_status,
        "history_count": len(session.get("research_history", []))
    }


@app.get("/api/metrics")
def get_metrics():
    """Get system execution metrics and pipeline statistics."""
    session = mock_st.session_state
    history = session.get("research_history", [])
    total_sources = sum(item.get("report_stats", {}).get("total_sources", 0) for item in history)
    total_claims = sum(item.get("report_stats", {}).get("total_claims", 0) for item in history)
    return {
        "total_runs": len(history),
        "total_sources_analyzed": total_sources,
        "total_claims_synthesized": total_claims,
        "is_pipeline_active": state.is_running,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }


@app.get("/api/config")
def get_config():
    """Get the current model and provider configuration."""
    session = mock_st.session_state
    agents = {}
    for k, v in session["llm_config"].items():
        agents[k] = {
            "provider": v.provider,
            "model": v.model,
            "key_set": bool(v.api_key)
        }
    return {
        "use_global_key": session["use_global_key"],
        "global_provider": session["global_provider"],
        "global_key_set": bool(session["global_key"]),
        "agents": agents
    }

@app.post("/api/config")
def save_config(dto: ConfigDTO):
    """Save the credentials and configurations persistently."""
    config_store.set_global_settings(dto.use_global_key, dto.global_provider, dto.global_key)
    for k, v in dto.agents.items():
        existing = config_store.get_agent_config(k)
        if existing is None:
            continue
        patch = dict(existing)
        if dto.use_global_key:
            patch["provider"] = dto.global_provider
        else:
            patch["provider"] = v.provider
        if v.model:
            patch["model"] = v.model
        if v.api_key and v.api_key.strip():
            patch["api_key"] = v.api_key.strip()
        config_store.set_agent_config(k, patch)
    _rebuild_session()
    return {"status": "success", "message": "Configuration saved"}


@app.post("/api/config/test")
def test_api_key(dto: KeyTestDTO):
    """Lightweight validation ping for an API key + model combination."""
    from utils.llm_factory import validate_key
    ok, err = validate_key(dto.provider, dto.api_key, dto.model)
    return {"valid": ok, "error": err}


@app.get("/api/history")
def get_history():
    """Get past runs."""
    return mock_st.session_state["research_history"]


@app.post("/api/history/select")
def select_history(dto: Dict[str, int]):
    """Load a past run into active view."""
    index = dto.get("index", -1)
    history = mock_st.session_state["research_history"]
    if index < 0 or index >= len(history):
        raise HTTPException(status_code=400, detail="Invalid index")
    
    run = history[index]
    state.run_query = run["query"]
    state.run_timestamp = run.get("timestamp", "")
    state.final_report = run.get("final_report", "")
    state.report_stats = run.get("report_stats", {})
    
    # Rebuild a dummy tracker structure for API responses
    state.citation_tracker = CitationTracker()
    for cid, info in run.get("citations", {}).items():
        from tools.citations import CitationEntry
        entry = CitationEntry(
            title=info.get("title", ""),
            url=info.get("url", ""),
            relevance=info.get("relevance", 0.0),
            relevance_pct=info.get("relevance_pct", 0),
            claim_ids=info.get("claim_ids", [])
        )
        state.citation_tracker.citations[cid] = entry
        
    return {"status": "success", "message": "Loaded past project results"}


@app.get("/api/status")
def get_status():
    """Get the active research status."""
    sources = []
    if state.citation_tracker:
        for i, (cid, entry) in enumerate(state.citation_tracker.citations.items(), 1):
            sources.append({
                "id": i,
                "title": entry.title,
                "url": entry.url,
                "relevance": entry.relevance,
                "relevance_pct": entry.relevance_pct,
                "claims": len(entry.claim_ids)
            })

    # Return serialized MockAgentState values
    agent_states_res = {}
    for k in state.agent_states:
        mock_state = MockAgentState(k)
        agent_states_res[k] = {
            "status": mock_state.status,
            "progress": mock_state.progress,
            "elapsed": mock_state.elapsed,
            "elapsed_str": mock_state.elapsed_str,
            "error_msg": mock_state.error_msg
        }

    return {
        "is_running": state.is_running,
        "query": state.run_query,
        "timestamp": state.run_timestamp,
        "agent_states": agent_states_res,
        "final_report": state.final_report,
        "report_stats": state.report_stats,
        "sources": sources
    }

@app.get("/api/logs")
def get_logs():
    """Get active logging feed."""
    return state.activity_feed


def _save_to_memory_api(query: str, report, tracker):
    try:
        from memory.chroma_client import get_memory, make_memory_entry
        memory = get_memory()
        entries = []
        if tracker.claims:
            for claim in tracker.claims:
                entry = make_memory_entry(
                    topic=query,
                    claim=claim.text,
                    sources=[tracker.citations[cid].url for cid in claim.citation_ids if cid in tracker.citations],
                    confidence=claim.confidence,
                    relevance=sum(tracker.citations[cid].relevance for cid in claim.citation_ids if cid in tracker.citations) / len(claim.citation_ids) if claim.citation_ids else 0.0,
                    agent=claim.agent or "analyst",
                )
                entries.append(entry)
        elif hasattr(report.stats, 'total_claims') and report.stats.total_claims > 0:
            entry = make_memory_entry(
                topic=query,
                claim=report.executive_summary[:500],
                sources=[c.url for c in tracker.citations.values()],
                confidence=report.stats.avg_confidence,
                relevance=report.stats.avg_relevance,
                agent="summarizer",
            )
            entries.append(entry)
        if entries:
            memory.upsert_findings(query, entries)
    except Exception:
        pass


def _add_to_history_api(query: str, stats: dict):
    # Save a complete summary including raw report for local fast loads
    history_entry = {
        "query": query,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "stats": stats,
        "final_report": state.final_report,
        "report_stats": state.report_stats,
        "citations": {cid: {
            "title": c.title,
            "url": c.url,
            "relevance": c.relevance,
            "relevance_pct": c.relevance_pct,
            "claim_ids": c.claim_ids
        } for cid, c in state.citation_tracker.citations.items()} if state.citation_tracker else {}
    }
    mock_st.session_state["research_history"].append(history_entry)


def run_research_in_background(dto: ResearchDTO):
    """Execution wrapper running CrewAI sequences in a separate worker thread."""
    try:
        run_id = f"research-{uuid.uuid4().hex[:8]}"
        state.run_id = run_id
        mock_reset_timeline()
        state.activity_feed.clear()
        
        reset_streaming_handler()
        handler = get_streaming_handler()
        
        tracker = CitationTracker()
        state.citation_tracker = tracker
        
        state.run_query = dto.query
        state.run_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        state.is_running = True
        state.final_report = ""
        state.report_stats = {}
        
        mock_add_activity("system", f"Research pipeline started: '{dto.query}'", "info")
        
        # Build the Crew chain (llm_factory reads the persistent config store)
        crew = create_crew(
            use_global_key=config_store.get_global_settings()["use_global_key"],
            global_key=config_store.get_global_settings()["global_key"],
            tracker=tracker,
            callbacks=[handler],
            run_id=run_id,
        )
        
        result = crew.kickoff(inputs={"query": dto.query})
        
        # Parse final Pydantic model
        from tasks import FinalReport
        if isinstance(result, FinalReport):
            report = result
        else:
            try:
                raw = result.raw if hasattr(result, 'raw') else str(result)
                report = FinalReport.model_validate_json(raw)
            except Exception:
                report = FinalReport(
                    markdown=str(result),
                    executive_summary="Report completed.",
                    key_findings=[],
                    citations_markdown="",
                )
                
        state.final_report = report.markdown
        state.report_stats = {
            "total_sources": report.stats.total_sources,
            "total_claims": report.stats.total_claims,
            "avg_confidence": report.stats.avg_confidence,
            "avg_relevance": report.stats.avg_relevance,
            "runtime_seconds": report.stats.runtime_seconds,
        }
        
        # Save cache state
        if dto.include_memory:
            _save_to_memory_api(dto.query, report, tracker)
            
        _add_to_history_api(dto.query, report.stats.model_dump())
        mock_add_activity("system", "Research synthesis complete!", "success")
        
    except Exception as e:
        error_str = str(e)
        mock_add_activity("system", f"Research failed: {error_str}", "error")
        # Fail any active timeline agents
        for k in state.agent_states:
            if state.agent_states[k]["status"] == "running":
                state.agent_states[k]["status"] = "error"
                state.agent_states[k]["error_msg"] = error_str[:120]
    finally:
        state.is_running = False


@app.post("/api/research")
def trigger_research(dto: ResearchDTO):
    """Trigger a query search loop."""
    if state.is_running:
        raise HTTPException(status_code=400, detail="Research is already in progress.")
        
    # Start thread
    thread = threading.Thread(target=run_research_in_background, args=(dto,))
    thread.daemon = True
    thread.start()
    
    return {"status": "success", "message": "Research started in background"}


# ─── Custom Agents CRUD ───

@app.get("/api/agents")
def list_agents():
    """List built-in and custom agents with their configs."""
    cfg = config_store.get_config()
    agents = []
    for name, ac in cfg["agents"].items():
        agents.append({"name": name, "builtin": True, **ac, "api_key_set": bool(ac.get("api_key"))})
    for ca in cfg["custom_agents"]:
        agents.append({**ca, "builtin": False, "api_key_set": bool(ca.get("api_key"))})
    return {"agents": agents, "tool_registry": config_store.TOOL_REGISTRY}


@app.post("/api/agents")
def create_agent(dto: AgentDefDTO):
    """Create or update a custom agent."""
    if dto.name in config_store.BUILTIN_AGENTS:
        raise HTTPException(status_code=400, detail="Cannot use a built-in agent name")
    config_store.set_agent_config(dto.name, dto.model_dump())
    return {"status": "success", "agent": config_store.get_agent_config(dto.name)}


@app.delete("/api/agents/{name}")
def delete_agent(name: str):
    if not config_store.delete_custom_agent(name):
        raise HTTPException(status_code=400, detail="Agent not found or is built-in")
    return {"status": "success"}


# ─── Teams CRUD ───

@app.get("/api/teams")
def list_teams():
    return {"teams": config_store.list_teams()}


@app.post("/api/teams")
def save_team(dto: TeamDTO):
    team = config_store.upsert_team(dto.model_dump())
    return {"status": "success", "team": team}


@app.delete("/api/teams/{team_id}")
def delete_team(team_id: int):
    if not config_store.delete_team(team_id):
        raise HTTPException(status_code=404, detail="Team not found")
    return {"status": "success"}


@app.post("/api/teams/{team_id}/run")
def run_team(team_id: int, dto: TeamRunDTO):
    """Run a team workflow in a background thread."""
    if state.is_running:
        raise HTTPException(status_code=400, detail="A pipeline is already in progress.")
    team = config_store.get_team(team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    def _runner():
        try:
            state.run_id = f"team-{uuid.uuid4().hex[:8]}"
            state.is_running = True
            state.run_query = dto.query
            state.run_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            state.final_report = ""
            state.report_stats = {}
            state.citation_tracker = CitationTracker()
            mock_reset_timeline()
            reset_streaming_handler()
            handler = get_streaming_handler()
            result = teams_run_team(
                team,
                dto.query,
                tracker=state.citation_tracker,
                callbacks=[handler],
            )
            state.final_report = result["raw_output"]
            state.report_stats = {
                "runtime_seconds": result["runtime_seconds"],
                "agents_used": result["agents_used"],
            }
            _add_to_history_api(dto.query, state.report_stats)
            mock_add_activity("system", f"Team '{team.get('name')}' workflow complete", "success")
        except Exception as e:
            mock_add_activity("system", f"Team run failed: {e}", "error")
        finally:
            state.is_running = False

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    return {"status": "success", "message": "Team run started"}


# ─── Agent Communication (event bus / blackboard) ───

@app.get("/api/comms/log")
def comms_log(run_id: str = "", limit: int = 100):
    """Recent inter-agent messages."""
    return {"messages": comms.get_message_log(run_id=run_id, limit=limit)}


@app.get("/api/comms/events")
def comms_events(limit: int = 100, since_ts: float = 0.0, run_id: str = ""):
    """Recent bus events (polling fallback for SSE)."""
    return {"events": comms.get_events(limit=limit, since_ts=since_ts, run_id=run_id)}


@app.get("/api/comms/stream")
async def comms_stream():
    """Server-Sent Events stream of the agent communication bus."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=500)

    def _on_event(event):
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            pass

    comms.subscribe(_on_event)

    async def _gen():
        try:
            yield f"data: {_json.dumps({'type': 'connected'})}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {_json.dumps(event, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            comms.unsubscribe(_on_event)

    return StreamingResponse(_gen(), media_type="text/event-stream")


@app.get("/api/comms/blackboard")
def blackboard(prefix: str = "", run_id: str = ""):
    return {"entries": comms.bb_list(prefix=prefix, run_id=run_id)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="127.0.0.1", port=8000, reload=True)
