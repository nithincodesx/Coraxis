"""
Word Cloud Component — Topic word cloud using Altair with custom theme.
"""

import streamlit as st
try:
    import altair as alt
    import pandas as pd
    import numpy as np
except ImportError:
    alt = None
    pd = None
    np = None
from typing import Optional, List, Dict
from collections import Counter
import re

# Register custom Altair theme
def _kimi_theme():
    return {
        "config": {
            "background": "transparent",
            "title": {"color": "#E2E8F0", "font": "Space Grotesk", "fontSize": 14, "fontWeight": 600},
            "axis": {"labelColor": "#94A3B8", "titleColor": "#E2E8F0", "gridColor": "rgba(56,189,248,0.1)"},
            "legend": {"labelColor": "#E2E8F0", "titleColor": "#E2E8F0"},
            "range": {
                "category": ["#38BDF8", "#F59E0B", "#22C55E", "#EF4444", "#A855F7", "#EC4899"],
            },
        }
    }

if alt is not None:
    alt.themes.register("kimi", _kimi_theme)
    alt.themes.enable("kimi")


STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with",
    "by", "from", "as", "is", "was", "are", "were", "be", "been", "being", "have", "has",
    "had", "do", "does", "did", "will", "would", "could", "should", "may", "might", "must",
    "this", "that", "these", "those", "i", "you", "he", "she", "it", "we", "they", "them",
    "their", "our", "your", "my", "his", "her", "its", "what", "which", "who", "when",
    "where", "why", "how", "all", "each", "every", "some", "any", "no", "not", "so",
    "if", "then", "than", "also", "just", "only", "even", "still", "yet", "already",
    "can", "cannot", "about", "into", "through", "during", "before", "after", "above",
    "below", "between", "under", "over", "again", "further", "once", "more", "most",
    "other", "such", "own", "same", "different", "new", "old", "first", "last", "next",
    "previous", "current", "recent", "latest", "early", "late", "high", "low", "large",
    "small", "big", "little", "long", "short", "right", "left", "top", "bottom",
}


def extract_keywords(text: str, max_words: int = 80) -> List[Dict]:
    """Extract keywords from text using simple TF approach."""
    # Clean and tokenize
    words = re.findall(r"\b[a-zA-Z]{3,}\b", text.lower())
    words = [w for w in words if w not in STOPWORDS and not w.isdigit()]

    # Count frequencies
    freq = Counter(words)

    # Get top words
    top_words = freq.most_common(max_words)

    # Assign positions (spiral layout approximation)
    keywords = []
    for rank, (word, count) in enumerate(top_words):
        # Spiral positioning for organic feel
        angle = rank * 0.55  # Golden angle-ish
        radius = 0.25 + (rank / max(max_words, 1)) * 0.75
        x = radius * np.cos(angle)
        y = radius * np.sin(angle)

        # Size based on frequency (log scale)
        max_count = top_words[0][1] if top_words else 1
        size = 10 + 30 * np.log1p(count) / np.log1p(max_count)

        keywords.append({
            "word": word,
            "count": count,
            "x": x,
            "y": y,
            "size": size,
            "rank": rank,
        })

    return keywords


def render_wordcloud(
    text: str = "",
    tracker=None,
    max_words: int = 60,
    height: int = 300,
):
    """Render word cloud from text or citation tracker claims."""
    if tracker and hasattr(tracker, "claims"):
        # Combine all claim texts
        text = " ".join(c.text for c in tracker.claims)

    if not text or len(text.strip()) < 50:
        st.markdown("""
        <div class="kimi-card wordcloud-container" style="display:flex;align-items:center;justify-content:center;color:var(--ink-subtle); height: 300px;">
            Run a research query to generate a word cloud.
        </div>
        """, unsafe_allow_html=True)
        return

    keywords = extract_keywords(text, max_words)

    if not keywords:
        st.caption("Insufficient text for word cloud.")
        return

    df = pd.DataFrame(keywords)

    # Color by cluster (k-means on position for visual grouping)
    from sklearn.cluster import KMeans
    try:
        n_clusters = min(6, len(df))
        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        df["cluster"] = kmeans.fit_predict(df[["x", "y"]])
    except Exception:
        df["cluster"] = df["rank"] % 6

    # Create chart with better visual design
    chart = alt.Chart(df).mark_text(
        align="center",
        baseline="middle",
        font="Inter",
        fontWeight="500",
    ).encode(
        x=alt.X("x:Q", axis=None, scale=alt.Scale(domain=[-1.2, 1.2])),
        y=alt.Y("y:Q", axis=None, scale=alt.Scale(domain=[-1.2, 1.2])),
        text="word:N",
        size=alt.Size("size:Q", scale=alt.Scale(range=[12, 48]), legend=None),
        color=alt.Color("cluster:N", legend=None),
        opacity=alt.Opacity("count:Q", scale=alt.Scale(range=[0.7, 1.0]), legend=None),
        tooltip=[
            alt.Tooltip("word:N", title="Word"),
            alt.Tooltip("count:Q", title="Frequency"),
            alt.Tooltip("rank:Q", title="Rank"),
        ],
    ).properties(
        width="container",
        height=height,
        title="Topic Word Cloud",
    ).configure_view(
        strokeWidth=0
    ).configure_title(
        fontSize=14,
        fontWeight=600,
        color="#E2E8F0",
        anchor="start",
        offset=10,
    )

    st.altair_chart(chart, use_container_width=True)


def render_wordcloud_simple(text: str = "", tracker=None, max_words: int = 40):
    """Simpler word cloud using native Streamlit (fallback)."""
    if tracker and hasattr(tracker, "claims"):
        text = " ".join(c.text for c in tracker.claims)

    if not text:
        st.info("Run a research query to generate a word cloud.")
        return

    keywords = extract_keywords(text, max_words)
    if not keywords:
        return

    # Display as styled tags
    st.markdown("### ☁️ Topic Word Cloud")

    # Create tag cloud HTML
    max_count = max(k["count"] for k in keywords)
    html_parts = ['<div style="display:flex; flex-wrap:wrap; gap:0.5rem; line-height:2.5;">']

    for kw in keywords:
        # Size based on frequency
        rel_size = 0.8 + 1.2 * (kw["count"] / max_count)
        # Color by rank - using palette colors
        hue = 200 - (kw["rank"] / max_words) * 60  # Cyan to blue
        html_parts.append(
            f'<span style="font-size:{rel_size}rem; color:hsl({hue}, 80%, 60%); '
            f'background:rgba(56,189,248,0.1); padding:0.2rem 0.6rem; '
            f'border-radius:999px; font-weight:500;" title="Frequency: {kw["count"]}">'
            f'{kw["word"]}</span>'
        )

    html_parts.append("</div>")
    st.markdown("".join(html_parts), unsafe_allow_html=True)