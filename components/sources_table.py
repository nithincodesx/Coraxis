"""
Sources Table Component — Top sources with relevance bars.
Styled to match the Deep Slate Command design system.
"""

import streamlit as st
import pandas as pd
from typing import Optional
from tools.citations import CitationTracker, CitationEntry


def render_sources_table(tracker: Optional[CitationTracker] = None):
    """Render the sources table with relevance bars using design system styling."""
    if tracker is None:
        tracker = st.session_state.get("citation_tracker")

    if not tracker or not tracker.citations:
        st.markdown("""
        <div class="kimi-card" style="text-align:center; padding:3rem; color:var(--ink-subtle);">
            No sources yet. Run a research query to populate.
        </div>
        """, unsafe_allow_html=True)
        return

    # Convert to DataFrame
    rows = []
    for i, (cit_id, entry) in enumerate(tracker.citations.items(), 1):
        rows.append({
            "#": i,
            "Source": entry.title[:80] + ("..." if len(entry.title) > 80 else ""),
            "URL": entry.url,
            "Relevance": entry.relevance,
            "Relevance %": entry.relevance_pct,
            "Claims": len(entry.claim_ids),
        })

    df = pd.DataFrame(rows)

    # Configure columns with design system styling
    column_config = {
        "#": st.column_config.NumberColumn("#", width="small"),
        "Source": st.column_config.TextColumn("Source", width="medium"),
        "URL": st.column_config.LinkColumn("URL", display_text="Open", width="medium"),
        "Relevance": st.column_config.ProgressColumn(
            "Relevance",
            format="%d%%",
            min_value=0,
            max_value=1,
            width="large",
        ),
        "Relevance %": None,  # Hide duplicate
        "Claims": st.column_config.NumberColumn("Claims", width="small"),
    }

    # Display using Streamlit dataframe (styled via CSS)
    st.dataframe(
        df,
        column_config=column_config,
        hide_index=True,
        use_container_width=True,
        height=min(400, 35 * len(df) + 40),
    )

    # Summary stats with styled metrics
    stats = tracker.get_stats()
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Sources", stats["total_sources"])
    with col2:
        st.metric("Avg Relevance", f"{stats['avg_relevance']*100:.0f}%")
    with col3:
        st.metric("Total Claims", stats["total_claims"])


def render_sources_table_native(tracker: Optional[CitationTracker] = None):
    """Native Streamlit version with custom HTML for relevance bars."""
    if tracker is None:
        tracker = st.session_state.get("citation_tracker")

    if not tracker or not tracker.citations:
        st.info("No sources yet. Run a research query to populate.")
        return

    st.markdown("### 📚 Sources")

    for i, (cit_id, entry) in enumerate(tracker.citations.items(), 1):
        with st.container(border=True):
            col1, col2 = st.columns([4, 1])
            with col1:
                st.markdown(f"**{i}. {entry.title}**")
                st.caption(entry.url)
            with col2:
                # Relevance badge
                color = "var(--success)" if entry.relevance > 0.7 else "var(--signal)" if entry.relevance > 0.4 else "var(--ink-subtle)"
                st.markdown(
                    f'<div style="text-align:right; color:{color}; font-weight:600;">{entry.relevance_pct}%</div>',
                    unsafe_allow_html=True,
                )

            # Relevance bar
            st.markdown(
                f"""
                <div class="relevance-bar-wrap">
                    <div class="relevance-bar" style="width: {entry.relevance_pct}%;"></div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            if entry.snippet:
                with st.expander("Snippet"):
                    st.caption(entry.snippet)

            st.caption(f"Referenced in {len(entry.claim_ids)} claim(s)")