"""
Kimi — Multi-Agent Research Assistant
Main Streamlit entry point.
"""

import streamlit as st
import asyncio
import time
from datetime import datetime

# Page config - must be first Streamlit command
st.set_page_config(
    page_title="Kimi — Multi-Agent Research",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Inject custom CSS
def inject_css():
    with open("styles/custom.css", "r") as f:
        css = f.read()
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)

inject_css()

# Import components
from components.sidebar import render_sidebar
from components.timeline import render_timeline, reset_timeline
from components.sources_table import render_sources_table
from components.wordcloud import render_wordcloud
from components.report_view import render_report_view
from components.activity_feed import render_activity_feed, clear_activity_feed, init_activity_feed
from components.settings import init_session_state
from utils.streaming import reset_streaming_handler, get_streaming_handler
from utils.export import export_markdown, export_pdf
from tasks import create_crew, run_research
from tools.citations import CitationTracker
from memory.chroma_client import get_memory, make_memory_entry
from utils.streaming import get_streaming_handler


def main():
    """Main application entry point."""
    init_session_state()
    init_activity_feed()

    # Ensure navigation tab is initialized in session state
    if "main_nav_tab" not in st.session_state:
        st.session_state.main_nav_tab = "👥 My Team"

    # Render sidebar (contains workspace avatar strip & project history runs)
    render_sidebar()

    # Run the background crew pipeline if research was triggered
    if st.session_state.get("run_triggered"):
        run_research_pipeline()
        st.session_state.run_triggered = False

    # Render main tabbed view dashboard
    render_dashboard()


def render_dashboard():
    """Render the main dashboard using horizontal Dribbble-style tabs."""
    # Main Header
    col1, col2 = st.columns([4, 1])
    with col1:
        st.markdown(
            """
            <h1 style="margin-bottom:0; font-family:'Space Grotesk',sans-serif; font-weight:700;">Synapse</h1>
            <p style="margin-top:0.25rem; color:var(--ink-subtle); font-size:0.9rem; font-family:'Inter',sans-serif;">
                Multi-Agent Research Laboratory — Collaborative Synthesis Engine
            </p>
            """,
            unsafe_allow_html=True,
        )
    with col2:
        if st.session_state.get("final_report"):
            st.markdown(
                f'<span style="float:right; font-size:0.75rem; color:var(--ink-subtle); font-family:\'Space Grotesk\',sans-serif; margin-top:1rem;">Last run: {st.session_state.get("run_timestamp", "")}</span>',
                unsafe_allow_html=True,
            )

    st.divider()

    # Render Dribbble horizontal tabs using our custom radio button hack
    nav_tab = st.radio(
        "Navigation",
        ["👥 My Team", "🔬 Research Workspace", "⚙️ Settings"],
        horizontal=True,
        label_visibility="collapsed",
        key="main_nav_tab"
    )

    st.divider()

    # Route content depending on active tab
    if nav_tab == "👥 My Team":
        _render_my_team()
    elif nav_tab == "🔬 Research Workspace":
        _render_research_workspace()
    elif nav_tab == "⚙️ Settings":
        _render_settings_tab()


def _render_my_team():
    """Render the AI Agents Team view inspired by the Dribbble design."""
    st.markdown("## 👥 AI Agents Crew")
    st.caption("A collaborative network of specialized intelligence agents running sequential research paths.")

    from components.timeline import AGENT_ORDER, get_agent_state
    
    # Custom details for the agent cards
    agent_info = {
        "researcher": {
            "avatar": "🔬",
            "color": "#8B5CF6", # Violet
            "title": "Senior Researcher",
            "desc": "Decomposes queries into searchable sub-questions, extracts key entities, and manages semantic memory caches."
        },
        "web_searcher": {
            "avatar": "🔍",
            "color": "#10B981", # Emerald
            "title": "Search Specialist",
            "desc": "Performs concurrent web searches, crawls raw text from pages, and filters search snippets for context."
        },
        "analyst": {
            "avatar": "📊",
            "color": "#F59E0B", # Amber
            "title": "Synthesis Analyst",
            "desc": "Cross-references page text, scores source relevance (0-100%), resolves conflicts, and logs evidence claims."
        },
        "summarizer": {
            "avatar": "📝",
            "color": "#EC4899", # Rose
            "title": "Lead Report Writer",
            "desc": "Translates analyst findings into a highly structured markdown publication containing inline citation tags."
        }
    }

    # Render agent cards grid
    st.markdown('<div class="agent-grid">', unsafe_allow_html=True)
    cols = st.columns(4)
    for i, (key, icon, name) in enumerate(AGENT_ORDER):
        info = agent_info[key]
        state = get_agent_state(key)
        
        status_class = "active" if state.status == "running" else "idle"
        status_text = "Active" if state.status == "running" else "Idle"
        
        # Check configured model name
        config = st.session_state.llm_config.get(key)
        from utils.llm_factory import get_default_model
        model_name = "default"
        if config:
            if st.session_state.use_global_key:
                model_name = get_default_model(st.session_state.global_provider)
            else:
                model_name = config.model or get_default_model(config.provider)
        
        with cols[i]:
            st.markdown(
                f"""
                <div class="agent-card">
                    <div class="agent-card-header">
                        <div class="agent-avatar" style="background: {info['color']}20; color: {info['color']};">
                            {info['avatar']}
                        </div>
                        <span class="agent-status-badge {status_class}">
                            {status_text}
                        </span>
                    </div>
                    <div class="agent-role">{info['title']}</div>
                    <p class="agent-desc">{info['desc']}</p>
                    <div class="agent-model">🤖 {model_name}</div>
                </div>
                """,
                unsafe_allow_html=True
            )
    st.markdown('</div>', unsafe_allow_html=True)

    st.divider()

    # Dribbble bottom promo cards
    st.markdown("### Templates & Configurations")
    col_promo1, col_promo2 = st.columns(2)
    with col_promo1:
        st.markdown(
            """
            <div class="promo-card gradient-1">
                <div>
                    <div class="promo-title">Configure Custom Teams</div>
                    <p class="promo-desc">Assemble custom agent groups with localized communication routes and custom toolkits.</p>
                </div>
                <button class="promo-btn">Assemble Team</button>
            </div>
            """,
            unsafe_allow_html=True
        )
    with col_promo2:
        st.markdown(
            """
            <div class="promo-card gradient-2">
                <div>
                    <div class="promo-title">Deploy Prebuilt Templates</div>
                    <p class="promo-desc">Run ready-made multi-agent chains customized for competitive research, blogs, or SEO audits.</p>
                </div>
                <button class="promo-btn">Browse Templates</button>
            </div>
            """,
            unsafe_allow_html=True
        )


def _render_research_workspace():
    """Render the research workspace tab (search, timeline trackers, and final report)."""
    st.markdown("## 🔬 Research Workspace")
    st.caption("Ask a complex question. The Synapse crew will crawl resources, analyze claims, and write an executive report.")

    # Search query input and execution button inline
    col_input, col_btn = st.columns([5, 1.2])
    with col_input:
        query = st.text_input(
            "Topic / Question",
            placeholder="e.g. 'How does AlphaFold 3 model DNA-protein interactions?'",
            key="run_query_text_input",
            label_visibility="collapsed"
        )
    
    from components.sidebar import _has_valid_config
    can_run = bool(query.strip()) and _has_valid_config()
    
    with col_btn:
        if st.button("🚀 Run Research", type="primary", use_container_width=True, disabled=not can_run, key="main_run_query_btn"):
            st.session_state.run_query = query
            st.session_state.run_max_sources = st.session_state.get("adv_max_sources", 5)
            st.session_state.run_min_confidence = st.session_state.get("adv_min_confidence", 0.3)
            st.session_state.run_include_memory = st.session_state.get("adv_include_memory", True)
            st.session_state.run_triggered = True
            st.rerun()

    if not _has_valid_config():
        st.info("⚠️ Configure at least one valid API key in the **Settings** tab to start research.")

    # Advanced Options Accordion
    with st.expander("🛠️ Advanced Search Parameters", expanded=False):
        col_a1, col_a2, col_a3 = st.columns(3)
        with col_a1:
            st.slider("Max sources per sub-question", 3, 10, 5, key="adv_max_sources")
        with col_a2:
            st.slider("Min confidence threshold", 0.0, 1.0, 0.3, 0.1, key="adv_min_confidence")
        with col_a3:
            st.checkbox("Use semantic memory (ChromaDB cache)", value=True, key="adv_include_memory")

    st.divider()

    # Active Execution & Result Layouts
    has_results = bool(st.session_state.get("final_report"))
    from components.timeline import get_agent_state
    
    is_running = st.session_state.get("run_triggered", False) or \
                 get_agent_state("researcher").status == "running" or \
                 get_agent_state("summarizer").status == "running"
                 
    has_run_begun = get_agent_state("researcher").status in ["running", "done", "error"]

    if is_running or has_run_begun:
        col_timeline, col_results = st.columns([1.2, 2.8], gap="medium")
        
        with col_timeline:
            st.markdown("### 📈 Live Execution")
            render_timeline()
            st.markdown("### 📋 Activity Logs")
            render_activity_feed(height=280)
            
        with col_results:
            if has_results:
                # Wrap preview in card
                with st.container(border=True):
                    render_report_view()
                
                st.divider()
                # Bottom Grid: Wordcloud + Sources
                col_wc, col_src = st.columns([1.5, 2.5])
                with col_wc:
                    tracker = st.session_state.get("citation_tracker")
                    render_wordcloud(tracker=tracker)
                with col_src:
                    tracker = st.session_state.get("citation_tracker")
                    render_sources_table(tracker)
            else:
                st.markdown(
                    """
                    <div class="kimi-card" style="text-align:center; padding:5rem 2rem; color:var(--ink-subtle); display:flex; flex-direction:column; align-items:center; justify-content:center;">
                        <div style="font-size:3rem; margin-bottom:1rem; animation: spin 2s linear infinite;">🔬</div>
                        <h3 style="margin:0; color:var(--ink);">Crew is Collaborating...</h3>
                        <p style="font-size:0.85rem; margin-top:0.5rem; max-width:400px;">
                            The agents are running sequence tasks. Review execution logs on the left sidebar panel.
                        </p>
                    </div>
                    <style>
                    @keyframes spin {
                        100% { transform: rotate(360deg); }
                    }
                    </style>
                    """,
                    unsafe_allow_html=True
                )
    else:
        # Idle State
        if has_results:
            col_timeline, col_results = st.columns([1.2, 2.8], gap="medium")
            
            with col_timeline:
                st.markdown("### 📈 Run Metadata")
                stats = st.session_state.get("report_stats", {})
                if stats:
                    with st.container(border=True):
                        st.metric("Total Sources", stats.get("total_sources", 0))
                        st.metric("Avg Confidence", f"{stats.get('avg_confidence', 0)*100:.0f}%")
                        st.metric("Runtime", f"{stats.get('runtime_seconds', 0):.1f}s")
                st.markdown("### 📋 Activity Logs")
                render_activity_feed(height=280)
                
            with col_results:
                with st.container(border=True):
                    render_report_view()
                
                st.divider()
                col_wc, col_src = st.columns([1.5, 2.5])
                with col_wc:
                    tracker = st.session_state.get("citation_tracker")
                    render_wordcloud(tracker=tracker)
                with col_src:
                    tracker = st.session_state.get("citation_tracker")
                    render_sources_table(tracker)
        else:
            st.markdown(
                """
                <div class="kimi-card" style="text-align:center; padding:6rem 2rem; color:var(--ink-subtle);">
                    <div style="font-size:3.5rem; margin-bottom:1rem;">🧬</div>
                    <h3 style="margin:0; color:var(--ink);">Ready for Synthesis</h3>
                    <p style="font-size:0.85rem; margin-top:0.5rem;">
                        Enter a research query above or click a project in the sidebar to load past findings.
                      </p>
                </div>
                """,
                unsafe_allow_html=True
            )


def _render_settings_tab():
    """Render Settings LLM Config view directly inside the tab."""
    from components.settings import render_settings
    render_settings()


def run_research_pipeline():
    """Execute the full research pipeline with UI updates and robust error handling."""
    query = st.session_state.get("run_query", "")
    if not query:
        return

    # Reset UI state for new run
    reset_timeline()
    clear_activity_feed()
    reset_streaming_handler()

    # Initialize fresh citation tracker
    tracker = CitationTracker()
    st.session_state.citation_tracker = tracker

    # Store run metadata
    st.session_state.run_query = query
    st.session_state.run_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Get streaming callback handler
    handler = get_streaming_handler()

    # Show running indicator with detailed progress
    with st.status("🔬 Research in progress...", expanded=True) as status:
        try:
            # Run the crew with tracker and callbacks
            crew = create_crew(
                use_global_key=st.session_state.use_global_key,
                global_key=st.session_state.global_key,
                tracker=tracker,
                callbacks=[handler],
            )

            # Execute with progress updates
            result = crew.kickoff(inputs={"query": query})

            # Parse result
            from tasks import FinalReport
            if isinstance(result, FinalReport):
                report = result
            else:
                import json
                try:
                    raw = result.raw if hasattr(result, 'raw') else str(result)
                    report = FinalReport.model_validate_json(raw)
                except Exception:
                    report = FinalReport(
                        markdown=str(result),
                        executive_summary="Report generation completed.",
                        key_findings=[],
                        citations_markdown="",
                    )

            # Store results
            st.session_state.final_report = report.markdown
            st.session_state.report_stats = {
                "total_sources": report.stats.total_sources,
                "total_claims": report.stats.total_claims,
                "avg_confidence": report.stats.avg_confidence,
                "avg_relevance": report.stats.avg_relevance,
                "runtime_seconds": report.stats.runtime_seconds,
            }

            # Store citations from tracker (populated during run)
            # Note: In a full implementation, the agents would populate the tracker
            # For now, we'll parse from the report's citations_markdown
            if report.citations_markdown:
                # Tracker would be populated by agents in production
                pass

            # Save to semantic memory
            _save_to_memory(query, report, tracker)

            # Add to history
            _add_to_history(query, report.stats.model_dump())

            status.update(label="✅ Research complete!", state="complete")

        except Exception as e:
            error_msg = str(e)
            _handle_research_error(error_msg, status, query)

    # Rerun to update UI with results
    st.rerun()


def _handle_research_error(error_msg: str, status, query: str):
    """Handle research errors with user-friendly messages and recovery suggestions."""
    error_lower = error_msg.lower()

    # Rate limit errors
    if any(kw in error_lower for kw in ["rate limit", "429", "too many requests", "quota exceeded"]):
        status.update(label="⚠️ Rate limited", state="error")
        st.error("**Rate limit hit** — Free tier APIs have strict limits.")
        st.markdown("""
        **Suggestions:**
        - Wait 30-60 seconds before retrying
        - Use the **global key toggle** in Settings to spread load across providers
        - Configure **multiple providers** (Groq + Gemini + Ollama) for fallback
        - Reduce `max_sources` in Advanced Options
        """)

    # Authentication/key errors
    elif any(kw in error_lower for kw in ["unauthorized", "401", "403", "invalid key", "authentication", "api key"]):
        status.update(label="🔑 Invalid API key", state="error")
        st.error("**API key validation failed** — The key may be invalid, expired, or lack permissions.")
        st.markdown("""
        **Suggestions:**
        - Check the key in **Settings → Per-Agent Settings**
        - Use the **Validate** button next to each key
        - Ensure the key has access to the selected model
        - For Groq: verify key at console.groq.com
        """)

    # Network/timeout errors
    elif any(kw in error_lower for kw in ["timeout", "connection", "network", "dns", "ssl", "certificate"]):
        status.update(label="🌐 Network error", state="error")
        st.error("**Network issue** — Could not reach the API or search service.")
        st.markdown("""
        **Suggestions:**
        - Check your internet connection
        - Try again in a moment (transient network issues)
        - If using a VPN/proxy, try disabling it
        - DuckDuckGo search may be temporarily unavailable
        """)

    # Model/not found errors
    elif any(kw in error_lower for kw in ["model not found", "does not exist", "invalid model", "404"]):
        status.update(label="🤖 Model error", state="error")
        st.error("**Model not available** — The selected model may not exist or be accessible.")
        st.markdown("""
        **Suggestions:**
        - Check the model name in **Settings**
        - Use the default model for the provider
        - Some models require specific tier access
        """)

    # Memory/ChromaDB errors
    elif any(kw in error_lower for kw in ["chroma", "memory", "embedding", "sentence transformer"]):
        status.update(label="💾 Memory error", state="error")
        st.warning("**Semantic memory issue** — Research completed but couldn't save to memory.")
        st.caption("This doesn't affect the report. Check ChromaDB is accessible.")

    # Generic fallback
    else:
        status.update(label=f"❌ Error: {error_msg[:80]}", state="error")
        st.error(f"**Research failed:** {error_msg}")
        st.markdown("""
        **General troubleshooting:**
        - Check **Settings** for valid API keys
        - Try a simpler query
        - Reduce `max_sources` in Advanced Options
        - See the activity feed for detailed agent logs
        """)

    # Log error to activity feed
    from components.activity_feed import add_activity
    add_activity("system", f"Research error: {error_msg[:100]}", "error")


def _save_to_memory(query: str, report, tracker: CitationTracker):
    """Save findings to ChromaDB semantic memory."""
    try:
        memory = get_memory()
        entries = []

        # Create entries from actual claims in the tracker (populated by Analyst)
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
            # Fallback: create a summary entry
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
    except Exception as e:
        # Memory errors shouldn't break the run
        pass


def _add_to_history(query: str, stats: dict):
    """Add run to history."""
    if "research_history" not in st.session_state:
        st.session_state.research_history = []

    st.session_state.research_history.append({
        "query": query,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "stats": stats,
    })

    # Keep last 50
    if len(st.session_state.research_history) > 50:
        st.session_state.research_history = st.session_state.research_history[-50:]


if __name__ == "__main__":
    main()