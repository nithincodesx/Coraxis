"""
Timeline Component — Signature Element: Live Agent-Status Timeline.
Vertical timeline with animated progress, pulsing dots, elapsed time.
"""

import streamlit as st
import time
from typing import Optional
from dataclasses import dataclass, field


AGENT_ORDER = [
    ("researcher", "🔬", "Researcher"),
    ("web_searcher", "🔍", "Web Searcher"),
    ("analyst", "📊", "Analyst"),
    ("summarizer", "📝", "Summarizer"),
]


@dataclass
class AgentState:
    """Runtime state for a single agent."""
    status: str = "pending"  # pending, running, done, error
    progress: int = 0  # 0-100
    start_time: float = 0.0
    end_time: float = 0.0
    error_msg: str = ""

    @property
    def elapsed(self) -> float:
        if self.start_time == 0:
            return 0.0
        end = self.end_time or time.time()
        return end - self.start_time

    @property
    def elapsed_str(self) -> str:
        e = self.elapsed
        if e < 60:
            return f"{e:.1f}s"
        return f"{int(e//60)}m {int(e%60)}s"


def init_timeline_state():
    """Initialize timeline state in session."""
    if "agent_states" not in st.session_state:
        st.session_state.agent_states = {k: AgentState() for k, _, _ in AGENT_ORDER}
    if "timeline_start_time" not in st.session_state:
        st.session_state.timeline_start_time = 0.0


def reset_timeline():
    """Reset all agent states."""
    init_timeline_state()
    for state in st.session_state.agent_states.values():
        state.status = "pending"
        state.progress = 0
        state.start_time = 0.0
        state.end_time = 0.0
        state.error_msg = ""
    st.session_state.timeline_start_time = time.time()


def start_agent(agent_key: str):
    """Mark agent as running."""
    init_timeline_state()
    state = st.session_state.agent_states[agent_key]
    state.status = "running"
    state.progress = 0
    state.start_time = time.time()
    state.end_time = 0.0


def update_agent_progress(agent_key: str, progress: int):
    """Update agent progress (0-100)."""
    init_timeline_state()
    state = st.session_state.agent_states[agent_key]
    state.progress = max(0, min(100, progress))


def complete_agent(agent_key: str, success: bool = True, error: str = ""):
    """Mark agent as done or error."""
    init_timeline_state()
    state = st.session_state.agent_states[agent_key]
    state.status = "done" if success else "error"
    state.progress = 100 if success else state.progress
    state.end_time = time.time()
    state.error_msg = error


def get_agent_state(agent_key: str) -> AgentState:
    """Get agent state."""
    init_timeline_state()
    return st.session_state.agent_states[agent_key]


def render_timeline(compact: bool = False):
    """Render the live agent-status timeline."""
    init_timeline_state()

    st.markdown("### 📈 Agent Timeline")

    # Overall progress
    total_progress = sum(s.progress for s in st.session_state.agent_states.values()) / len(AGENT_ORDER)
    st.progress(total_progress / 100)

    # Timeline items
    for i, (key, icon, name) in enumerate(AGENT_ORDER):
        state = st.session_state.agent_states[key]
        is_last = i == len(AGENT_ORDER) - 1
        _render_timeline_item(key, icon, name, state, is_last, compact)


def _render_timeline_item(key: str, icon: str, name: str, state: AgentState, is_last: bool, compact: bool):
    """Render a single timeline item."""
    # Status label
    status_labels = {
        "pending": "Queued",
        "running": "Running",
        "done": "Complete",
        "error": "Error",
    }
    status_text = status_labels.get(state.status, state.status)

    # Determine colors
    dot_color = _dot_color(state.status)
    dot_shadow = _dot_shadow(state.status)
    pulse_anim = 'animation: pulse 1.5s ease-in-out infinite;' if state.status == 'running' else ''

    # Build HTML with cleaner structure
    connector = "" if is_last else '<div class="timeline-connector"></div>'

    html = f"""
    <div class="timeline-item">
        <div class="timeline-marker">
            {connector}
            <div class="timeline-dot" style="
                background: {dot_color};
                box-shadow: {dot_shadow};
                {pulse_anim}
            "></div>
        </div>
        <div class="timeline-content">
            <div class="timeline-header">
                <span class="timeline-icon">{icon}</span>
                <span class="timeline-name">{name}</span>
                <span class="timeline-status">{status_text}</span>
            </div>
            <div class="timeline-progress-wrap">
                <div class="timeline-progress" style="width: {state.progress}%;"></div>
            </div>
            <div class="timeline-meta">
                <span>Progress: {state.progress}%</span>
                <span>Elapsed: {state.elapsed_str}</span>
                {f'<span class="timeline-error">Error: {state.error_msg[:40]}</span>' if state.error_msg else ''}
            </div>
        </div>
    </div>
    """

    st.markdown(html, unsafe_allow_html=True)


def _dot_color(status: str) -> str:
    colors = {
        "pending": "var(--ink-subtle)",
        "running": "var(--accent)",
        "done": "var(--success)",
        "error": "var(--error)",
    }
    return colors.get(status, "var(--ink-subtle)")


def _dot_shadow(status: str) -> str:
    if status == "running":
        return "0 0 0 3px var(--accent-muted)"
    elif status == "done":
        return "0 0 0 3px var(--success-muted)"
    elif status == "error":
        return "0 0 0 3px var(--error-muted)"
    return "none"


# Streamlit-native version (fallback)
def render_timeline_native(compact: bool = False):
    """Render timeline using native Streamlit components (fallback)."""
    init_timeline_state()

    st.markdown("### 📈 Agent Timeline")

    # Overall progress
    total_progress = sum(s.progress for s in st.session_state.agent_states.values()) / len(AGENT_ORDER)
    st.progress(total_progress / 100)

    for key, icon, name in AGENT_ORDER:
        state = st.session_state.agent_states[key]

        col1, col2 = st.columns([1, 6])
        with col1:
            st.markdown(f"<div style='font-size:1.5rem; text-align:center'>{icon}</div>", unsafe_allow_html=True)
        with col2:
            st.markdown(f"**{name}**")
            # Progress bar
            prog_col, meta_col = st.columns([3, 1])
            with prog_col:
                st.progress(state.progress / 100)
            with meta_col:
                st.caption(f"{state.progress}% • {state.elapsed_str}")

            # Status badge
            if state.status == "running":
                st.markdown("🟢 **Running**")
            elif state.status == "done":
                st.markdown("✅ **Complete**")
            elif state.status == "error":
                st.markdown("🔴 **Error**")
            else:
                st.markdown("⚪ **Queued**")

            if state.error_msg:
                st.caption(f"Error: {state.error_msg}")