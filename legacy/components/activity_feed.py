"""
Activity Feed Component — Live agent-activity log with timestamps.
Styled to match the Deep Slate Command design system.
"""

import streamlit as st
import time
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ActivityEntry:
    timestamp: float
    agent: str
    message: str
    level: str = "info"  # info, success, warning, error

    @property
    def time_str(self) -> str:
        return datetime.fromtimestamp(self.timestamp).strftime("%H:%M:%S")

    @property
    def agent_color(self) -> str:
        colors = {
            "researcher": "#8B5CF6",    # Violet
            "web_searcher": "#10B981",  # Emerald
            "analyst": "#F59E0B",      # Amber
            "summarizer": "#EC4899",    # Rose
        }
        return colors.get(self.agent, "var(--ink-subtle)")

    @property
    def level_icon(self) -> str:
        icons = {"info": "ℹ️", "success": "✅", "warning": "⚠️", "error": "🔴"}
        return icons.get(self.level, "ℹ️")

    @property
    def level_class(self) -> str:
        return f"activity-level-{self.level}"


def init_activity_feed():
    """Initialize activity feed in session state."""
    if "activity_feed" not in st.session_state:
        st.session_state.activity_feed = []


def add_activity(agent: str, message: str, level: str = "info"):
    """Add an activity entry."""
    init_activity_feed()
    entry = ActivityEntry(
        timestamp=time.time(),
        agent=agent,
        message=message,
        level=level,
    )
    st.session_state.activity_feed.append(entry)

    # Keep last 100 entries
    if len(st.session_state.activity_feed) > 100:
        st.session_state.activity_feed = st.session_state.activity_feed[-100:]


def clear_activity_feed():
    """Clear the activity feed."""
    st.session_state.activity_feed = []


def render_activity_feed(max_entries: int = 20, height: int = 320):
    """Render the activity feed using design system CSS classes."""
    init_activity_feed()
    entries = st.session_state.activity_feed[-max_entries:]

    if not entries:
        st.markdown(f"""
        <div class="activity-feed" style="height:{height}px; display:flex; align-items:center; justify-content:center; color:var(--ink-subtle);">
            No activity yet. Start a research run.
        </div>
        """, unsafe_allow_html=True)
        return

    # Build HTML for smooth scrolling feed using CSS classes
    html_parts = [f'<div class="activity-feed" style="max-height:{height}px; overflow-y:auto;">']

    for entry in reversed(entries):  # Newest first
        agent_display = entry.agent.replace('_', ' ').title()
        html_parts.append(f"""
        <div class="activity-item {entry.level_class}" style="border-left-color: {entry.agent_color};">
            <span class="activity-time">{entry.time_str}</span>
            <span class="activity-agent" style="color: {entry.agent_color};">{agent_display}</span>
            <span class="activity-text">{entry.level_icon} {entry.message}</span>
        </div>
        """)

    html_parts.append("</div>")
    st.markdown("".join(html_parts), unsafe_allow_html=True)


def render_activity_feed_native(max_entries: int = 20):
    """Native Streamlit version."""
    init_activity_feed()
    entries = st.session_state.activity_feed[-max_entries:]

    if not entries:
        st.info("No activity yet. Start a research run.")
        return

    for entry in reversed(entries):
        with st.container():
            col1, col2, col3 = st.columns([1, 1.5, 6])
            with col1:
                st.caption(entry.time_str)
            with col2:
                st.markdown(f'<span style="color:{entry.agent_color}; font-weight:600;">{entry.agent.replace("_", " ").title()}</span>', unsafe_allow_html=True)
            with col3:
                st.caption(f"{entry.level_icon} {entry.message}")


# Agent name mapping for display
AGENT_DISPLAY = {
    "researcher": ("🔬", "Researcher"),
    "web_searcher": ("🔍", "Web Searcher"),
    "analyst": ("📊", "Analyst"),
    "summarizer": ("📝", "Summarizer"),
}


def log_agent_start(agent_key: str, detail: str = ""):
    """Log agent start."""
    icon, name = AGENT_DISPLAY.get(agent_key, ("", agent_key))
    add_activity(agent_key, f"{detail}", "info")


def log_agent_progress(agent_key: str, detail: str):
    """Log agent progress."""
    icon, name = AGENT_DISPLAY.get(agent_key, ("", agent_key))
    add_activity(agent_key, detail, "info")


def log_agent_complete(agent_key: str, detail: str = ""):
    """Log agent completion."""
    icon, name = AGENT_DISPLAY.get(agent_key, ("", agent_key))
    add_activity(agent_key, f"Completed — {detail}" if detail else "Completed", "success")


def log_agent_error(agent_key: str, error: str):
    """Log agent error."""
    icon, name = AGENT_DISPLAY.get(agent_key, ("", agent_key))
    add_activity(agent_key, f"Error: {error}", "error")


def log_search_results(count: int, query: str):
    """Log search results."""
    add_activity("web_searcher", f"Found {count} results for: {query[:60]}", "success")


def log_fetch_result(url: str, success: bool, words: int = 0):
    """Log page fetch result."""
    if success:
        add_activity("web_searcher", f"Fetched {words} words from {url[:50]}", "success")
    else:
        add_activity("web_searcher", f"Failed to fetch: {url[:50]}", "warning")


def log_memory_hit(topic: str, count: int):
    """Log semantic memory recall."""
    add_activity("researcher", f"Recalled {count} prior findings for '{topic}'", "info")


def log_report_generated(stats: dict):
    """Log report generation."""
    add_activity(
        "summarizer",
        f"Report generated — {stats.get('total_sources',0)} sources, {stats.get('total_claims',0)} claims",
        "success"
    )