"""
Sidebar Component — Workspace navigation and recent runs project listing.
Styled to match the premium Dribbble design system.
"""

import streamlit as st
from components.settings import render_settings, init_session_state


def render_sidebar():
    """Render the sidebar with workspace branding and history folders."""
    init_session_state()

    with st.sidebar:
        # 1. Inject the left vertical workspace strip HTML (mimics double sidebar)
        st.markdown(
            """
            <div class="workspace-strip">
                <div class="workspace-item active" title="Synapse Workspace (Active)">S</div>
                <div class="workspace-item" title="Design Team">D</div>
                <div class="workspace-item" title="Engineering Team">E</div>
                <div class="workspace-item" title="Marketing Team">M</div>
                <div class="workspace-add" title="Create New Team">+</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # 2. Workspace Branding Header
        st.markdown(
            """
            <div style="padding-bottom: 0.75rem; border-bottom: 1px solid var(--panel-border); margin-bottom: 1.25rem;">
                <p style="margin: 0; font-size: 0.6rem; font-weight: 700; color: var(--ink-subtle); text-transform: uppercase; letter-spacing: 0.05em;">Workspace</p>
                <h2 style="margin: 0; font-size: 1.15rem; font-family: 'Space Grotesk', sans-serif; font-weight: 700; color: var(--ink);">
                    Synapse Team 1
                </h2>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # 3. Project Folders / Research History
        st.markdown('<p class="sidebar-header">Projects</p>', unsafe_allow_html=True)
        _render_history_panel()

        # Spacer to push profile to bottom
        st.markdown(
            """
            <div style="height: 100px; display: flex; flex-direction: column; justify-content: flex-end; margin-top: auto;">
            </div>
            """,
            unsafe_allow_html=True,
        )

        # 4. User Profile Card at bottom (mimicking Dribbble avatar strip)
        st.divider()
        st.markdown(
            """
            <div style="display: flex; align-items: center; gap: 10px; padding-top: 0.25rem;">
                <div style="width: 32px; height: 32px; border-radius: 50%; background: var(--accent); color: #FFFFFF; display: flex; align-items: center; justify-content: center; font-size: 0.85rem; font-weight: bold; box-shadow: 0 2px 6px rgba(79, 70, 229, 0.25);">
                    S
                </div>
                <div style="flex: 1; min-width: 0;">
                    <p style="margin: 0; font-size: 0.75rem; font-weight: 600; color: var(--ink); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">Synapse User</p>
                    <p style="margin: 0; font-size: 0.65rem; color: var(--ink-subtle); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">shulk@synapse.ai</p>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _render_history_panel():
    """Render research history as Dribbble-style project list items."""
    history = st.session_state.get("research_history", [])
    if not history:
        st.markdown(
            "<p style='font-size:0.75rem; color:var(--ink-subtle); font-style:italic; padding-left:8px;'>No projects yet. Run a query.</p>",
            unsafe_allow_html=True
        )
        return

    for i, run in enumerate(reversed(history[-10:])):
        idx = len(history) - 1 - i
        query_truncated = run['query'][:22] + '...' if len(run['query']) > 22 else run['query']
        label = f"📁  {query_truncated}"
        
        # Clicking project loads findings and switches view to Research tab
        if st.button(label, key=f"view_hist_{idx}"):
            st.session_state.view_history_index = idx
            st.session_state.run_query = run['query']
            # Force dashboard rendering code to select the Research tab
            st.session_state.main_nav_tab = "🔬 Research Workspace"
            st.rerun()