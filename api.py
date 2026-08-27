"""
Kimi — FastAPI Backend Server.
Decoupled backend API wrapping the CrewAI multi-agent research pipeline.
Exposes endpoints for the Next.js frontend and implements custom mocks to capture progress updates.
"""

import sys
import os

root_dir = os.path.dirname(os.path.abspath(__file__))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import time
import threading
from datetime import datetime
from types import ModuleType
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

# ─── Mock Streamlit for CrewAI & Langchain Imports ───
mock_st = ModuleType("streamlit")
sys.modules["streamlit"] = mock_st
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

class StubContext:
    def __enter__(self): return self
    def __exit__(self, exc_type, exc_val, exc_tb): pass
    def update(self, *args, **kwargs): None

mock_st.status = lambda *args, **kwargs: StubContext()
mock_st.spinner = lambda *args, **kwargs: StubContext()
mock_st.container = lambda *args, **kwargs: StubContext()

# Initialize stub configurations
from utils.llm_factory import AgentLLMConfig

mock_st.session_state = {
    "llm_config": {
        "researcher": AgentLLMConfig(provider="groq", api_key="", model=""),
        "web_searcher": AgentLLMConfig(provider="groq", api_key="", model=""),
        "analyst": AgentLLMConfig(provider="groq", api_key="", model=""),
        "summarizer": AgentLLMConfig(provider="groq", api_key="", model=""),
    },
    "use_global_key": False,
    "global_key": "",
    "global_provider": "groq",
    "research_history": [],
}


# ─── Mock timeline & activity feed components to capture updates ───
class GlobalState:
    def __init__(self):
        self.is_running = False
        self.run_query = ""
        self.run_timestamp = ""
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

# Mocking modules in sys.modules before imports occur
mock_timeline = ModuleType("components.timeline")
mock_activity = ModuleType("components.activity_feed")

def mock_start_agent(agent_key: str):
    state.agent_states[agent_key]["status"] = "running"
    state.agent_states[agent_key]["progress"] = 0
    state.agent_states[agent_key]["start_time"] = time.time()
    state.agent_states[agent_key]["end_time"] = 0.0
    state.agent_states[agent_key]["error_msg"] = ""

def mock_update_agent_progress(agent_key: str, progress: int):
    state.agent_states[agent_key]["progress"] = max(0, min(100, progress))

def mock_complete_agent(agent_key: str, success: bool = True, error: str = ""):
    state.agent_states[agent_key]["status"] = "done" if success else "error"
    state.agent_states[agent_key]["progress"] = 100 if success else state.agent_states[agent_key]["progress"]
    state.agent_states[agent_key]["end_time"] = time.time()
    state.agent_states[agent_key]["error_msg"] = error

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
from tools.citations import CitationTracker

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
    """Save the credentials and configurations."""
    session = mock_st.session_state
    session["use_global_key"] = dto.use_global_key
    session["global_provider"] = dto.global_provider
    if dto.global_key and dto.global_key.strip():
        session["global_key"] = dto.global_key.strip()

    for k, v in dto.agents.items():
        if k in session["llm_config"]:
            if dto.use_global_key:
                session["llm_config"][k].provider = dto.global_provider
            else:
                session["llm_config"][k].provider = v.provider
            if v.model:
                session["llm_config"][k].model = v.model
            if v.api_key and v.api_key.strip():
                session["llm_config"][k].api_key = v.api_key.strip()
    return {"status": "success", "message": "Configuration saved"}


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
        
        # Build the Crew chain
        crew = create_crew(
            use_global_key=mock_st.session_state["use_global_key"],
            global_key=mock_st.session_state["global_key"],
            tracker=tracker,
            callbacks=[handler],
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


# ─── LangGraph Session & Connection Endpoints ───
from utils.langgraph_client import get_langgraph_session_manager, LangGraphSession

class LangGraphConfigDTO(BaseModel):
    endpoint_url: Optional[str] = None
    api_key: Optional[str] = None
    assistant_id: Optional[str] = None
    sync_mode: Optional[str] = None

class CreateSessionDTO(BaseModel):
    name: str = "Research Session"
    graph_id: str = "coraxis_research_graph"
    checkpointer: str = "MemorySaver"
    tags: List[str] = Field(default_factory=lambda: ["coraxis", "custom"])
    metadata: Dict[str, Any] = Field(default_factory=dict)


@app.get("/api/langgraph/config")
def get_langgraph_config():
    """Retrieve active LangGraph connection status and configuration."""
    mgr = get_langgraph_session_manager()
    cfg = mgr.get_config()
    return {
        "endpoint_url": cfg.endpoint_url,
        "assistant_id": cfg.assistant_id,
        "sync_mode": cfg.sync_mode,
        "checkpointer_type": cfg.checkpointer_type,
        "is_connected": cfg.is_connected,
        "last_ping": cfg.last_ping,
        "latency_ms": cfg.latency_ms,
        "active_session_id": cfg.active_session_id,
        "has_api_key": bool(cfg.api_key),
    }


@app.post("/api/langgraph/config")
def update_langgraph_config(dto: LangGraphConfigDTO):
    """Update LangGraph server connection details."""
    mgr = get_langgraph_session_manager()
    cfg = mgr.update_config(
        endpoint_url=dto.endpoint_url,
        api_key=dto.api_key,
        assistant_id=dto.assistant_id,
        sync_mode=dto.sync_mode,
    )
    return {
        "status": "success",
        "message": "LangGraph connection configuration updated",
        "config": get_langgraph_config(),
    }


@app.post("/api/langgraph/test-connection")
def test_langgraph_connection():
    """Ping and test connectivity to LangGraph endpoint."""
    mgr = get_langgraph_session_manager()
    result = mgr.test_connection()
    return result


@app.get("/api/langgraph/sessions")
def list_langgraph_sessions():
    """List all registered LangGraph sessions and thread checkpoints."""
    mgr = get_langgraph_session_manager()
    sessions = mgr.list_sessions()
    cfg = mgr.get_config()
    return {
        "active_session_id": cfg.active_session_id,
        "total_sessions": len(sessions),
        "sessions": [s.model_dump() for s in sessions],
    }


@app.post("/api/langgraph/sessions/new")
def create_langgraph_session(dto: CreateSessionDTO):
    """Create a brand new LangGraph session and thread ID."""
    mgr = get_langgraph_session_manager()
    sess = mgr.create_session(
        name=dto.name,
        graph_id=dto.graph_id,
        checkpointer=dto.checkpointer,
        tags=dto.tags,
        metadata=dto.metadata,
    )
    mock_add_activity("system", f"Created new LangGraph session: {sess.name} ({sess.thread_id[:8]}...)", "info")
    return {
        "status": "success",
        "message": "LangGraph session created successfully",
        "session": sess.model_dump(),
    }


@app.get("/api/langgraph/sessions/{session_id}")
def get_langgraph_session(session_id: str):
    """Retrieve details for a specific LangGraph session."""
    mgr = get_langgraph_session_manager()
    sess = mgr.get_session(session_id)
    if not sess:
        raise HTTPException(status_code=404, detail="LangGraph session not found")
    return sess.model_dump()


@app.post("/api/langgraph/sessions/{session_id}/activate")
def activate_langgraph_session(session_id: str):
    """Set the active LangGraph session for research pipelines."""
    mgr = get_langgraph_session_manager()
    success = mgr.activate_session(session_id)
    if not success:
        raise HTTPException(status_code=404, detail="LangGraph session not found")
    mock_add_activity("system", f"Activated LangGraph session: {session_id}", "info")
    return {"status": "success", "message": f"Session {session_id} is now active"}


@app.delete("/api/langgraph/sessions/{session_id}")
def delete_langgraph_session(session_id: str):
    """Remove a LangGraph session and its thread context."""
    mgr = get_langgraph_session_manager()
    success = mgr.delete_session(session_id)
    if not success:
        raise HTTPException(status_code=404, detail="LangGraph session not found")
    mock_add_activity("system", f"Deleted LangGraph session: {session_id}", "info")
    return {"status": "success", "message": f"Session {session_id} deleted"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="127.0.0.1", port=8000, reload=True)

