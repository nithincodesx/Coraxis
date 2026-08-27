"""
Report View Component — Report preview with inline citations and export.
"""

import streamlit as st
try:
    import markdown
except ImportError:
    markdown = None
import re
from typing import Optional
from tools.citations import CitationTracker
from utils.export import export_markdown, export_pdf


def render_report_view(
    report_md: str = "",
    tracker: Optional[CitationTracker] = None,
    stats: Optional[dict] = None,
):
    """Render the report preview with export buttons."""
    # Get from session if not provided
    if not report_md:
        report_md = st.session_state.get("final_report", "")
    if tracker is None:
        tracker = st.session_state.get("citation_tracker")
    if stats is None:
        stats = st.session_state.get("report_stats", {})

    st.markdown("### 📄 Report Preview")

    if not report_md:
        st.markdown("""
        <div class="kimi-card" style="text-align:center; padding:3rem; color:var(--ink-subtle);">
            No report yet. Run a research query to generate.
        </div>
        """, unsafe_allow_html=True)
        return

    # Stats bar
    if stats:
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Sources", stats.get("total_sources", 0))
        with col2:
            st.metric("Claims", stats.get("total_claims", 0))
        with col3:
            st.metric("Avg Confidence", f"{stats.get('avg_confidence', 0)*100:.0f}%")
        with col4:
            st.metric("Runtime", f"{stats.get('runtime_seconds', 0):.1f}s")

    # Export buttons
    _render_export_buttons(report_md, tracker)

    st.divider()

    # Report content
    _render_report_content(report_md, tracker)


def _render_export_buttons(report_md: str, tracker: Optional[CitationTracker]):
    """Render export download buttons."""
    col1, col2, col3 = st.columns([1, 1, 4])

    with col1:
        md_bytes = export_markdown(report_md, tracker)
        st.download_button(
            "📥 Download .md",
            data=md_bytes,
            file_name=f"kimi_report_{st.session_state.get('run_query', 'research').replace(' ', '_')[:40]}.md",
            mime="text/markdown",
            use_container_width=True,
        )

    with col2:
        try:
            pdf_bytes = export_pdf(report_md, tracker)
            st.download_button(
                "📄 Download PDF",
                data=pdf_bytes,
                file_name=f"kimi_report_{st.session_state.get('run_query', 'research').replace(' ', '_')[:40]}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        except Exception as e:
            st.button("📄 Download PDF", disabled=True, use_container_width=True)
            st.caption(f"PDF unavailable: {str(e)[:50]}")


def _render_report_content(report_md: str, tracker: Optional[CitationTracker]):
    """Render report markdown with proper citation handling."""
    # First, ensure citations from tracker are appended if not already in markdown
    if tracker and tracker.citations:
        tracker_citations = tracker.format_markdown()
        if tracker_citations and tracker_citations not in report_md:
            report_md = report_md + tracker_citations

    # Replace citation markers [^n] with styled links with anchor targets
    def replace_citation(match):
        num = match.group(1)
        return f'<a href="#source-{num}" class="citation" title="Go to source {num}">[^{num}]</a>'

    # Process markdown
    html = markdown.markdown(
        report_md,
        extensions=["fenced_code", "tables", "toc", "attr_list"],
    )

    # Add citation links
    html = re.sub(r"\[\^(\d+)\]", replace_citation, html)

    # Add anchor IDs to source list items
    if tracker:
        # Find the Sources section and add IDs
        def add_source_anchors(match):
            num = match.group(1)
            return match.group(0).replace(f"[^{num}]", f'<a id="source-{num}"></a>[^{num}]')

        # Add IDs to citation references in the Sources section
        html = re.sub(r'\[(\d+)\]:', lambda m: f'<a id="source-{m.group(1)}"></a>[{m.group(1)}]:', html)

    # Wrap in report-view class for styling
    html = f'<div class="report-view">{html}</div>'

    st.markdown(html, unsafe_allow_html=True)


def render_report_simple(report_md: str = "", tracker: Optional[CitationTracker] = None):
    """Simpler native Streamlit version."""
    if not report_md:
        report_md = st.session_state.get("final_report", "")

    if not report_md:
        st.info("No report yet. Run a research query to generate.")
        return

    st.markdown("### 📄 Report Preview")

    # Export buttons
    col1, col2 = st.columns(2)
    with col1:
        md_bytes = export_markdown(report_md, tracker)
        st.download_button("📥 Download .md", data=md_bytes, file_name="report.md", mime="text/markdown")
    with col2:
        try:
            pdf_bytes = export_pdf(report_md, tracker)
            st.download_button("📄 Download PDF", data=pdf_bytes, file_name="report.pdf", mime="application/pdf")
        except Exception:
            st.button("📄 Download PDF", disabled=True)

    st.divider()

    # Render markdown
    st.markdown(report_md)


# Standalone citation formatter
def format_citations_markdown(tracker: CitationTracker) -> str:
    """Format citations as markdown reference list."""
    if not tracker or not tracker.citations:
        return ""

    lines = ["\n---\n### Sources\n"]
    for i, (cit_id, entry) in enumerate(tracker.citations.items(), 1):
        lines.append(
            f"[^{i}]: **{entry.title}** — {entry.url}  "
            f"Relevance: {entry.relevance_pct}%"
        )
        if entry.snippet:
            lines.append(f"    > {entry.snippet[:200]}...")
        lines.append("")

    return "\n".join(lines)