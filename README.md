# 🔬 Kimi — Multi-Agent Research Assistant

A portfolio-grade, design-forward multi-agent research assistant built on **CrewAI** with **Streamlit**.
Kimi decomposes a research query into sub-questions, searches the web (DuckDuckGo, no API key),
fetches and extracts page content, synthesizes evidence-backed claims with confidence and relevance
scores, and writes a structured markdown report with inline citations — all on **100% free-tier services**.

---

## ✨ Features

- **4-Agent Sequential Chain** (CrewAI): Researcher → Web Searcher → Analyst → Summarizer
- **Per-Agent LLM Configuration**: Each agent can use Groq, Gemini, OpenAI, or Ollama independently
- **Citation Tracking**: Automatic source attribution with relevance scores and export
- **Semantic Memory** (ChromaDB): Recalls prior findings to avoid redundant research
- **Live UI Updates**: Real-time timeline, activity feed, and progress indicators
- **Structured Reports**: Executive summary, key findings, detailed sections, confidence assessment
- **Export**: Download as Markdown or PDF
- **Design System**: "Deep Slate Command" — intentional dark theme, not generic Streamlit

---

## 🏗️ Architecture

```
app.py                      # Streamlit entry point, pipeline orchestration
├── components/
│   ├── sidebar.py          # Navigation, research input, history
│   ├── settings.py         # Per-agent LLM provider/key config (session-only)
│   ├── timeline.py         # Live agent-status timeline (signature element)
│   ├── activity_feed.py    # Real-time agent activity log
│   ├── sources_table.py    # Citation sources with relevance bars
│   ├── wordcloud.py        # Topic visualization
│   └── report_view.py      # Report preview + export buttons
├── agents.py               # CrewAI agent factory (per-agent LLM binding)
├── tasks.py                # Sequential task chain (Pydantic output schemas)
├── tools/
│   ├── crew_tools.py       # CrewAI tool wrappers (search, fetch, memory, register_claim)
│   ├── search.py           # DuckDuckGo search + page fetching
│   └── citations.py        # CitationTracker (source + claim tracking)
├── memory/
│   └── chroma_client.py    # ChromaDB semantic memory client
├── utils/
│   ├── llm_factory.py      # Provider-specific LLM creation
│   ├── streaming.py        # Callback handler for live UI updates
│   └── export.py           # Markdown / PDF export
└── styles/
    └── custom.css          # Deep Slate Command design system
```

---

## 🚀 Quick Start (Local)

### Prerequisites
- Python 3.11+
- At least one free LLM API key:
  - **Groq** (recommended, fastest): https://console.groq.com
  - **Gemini** (free tier): https://aistudio.google.com/apikey
  - **Ollama** (local, no key): https://ollama.ai

### Setup

```bash
# Clone / download
cd Kimi

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate    # Windows
# source .venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# (Optional) Add API keys to .env (or enter in Settings UI)
cp .env.example .env
# Edit .env with your keys

# Run
streamlit run app.py
```

Open http://localhost:8501

---

## ⚙️ Configuration

### Settings UI (recommended)
1. Click **⚙️ Settings** in the sidebar
2. Toggle **"Use one key for all agents"** for simplicity, OR
3. Configure **per-agent** provider + key in **Per-Agent Settings**
4. Keys live **only in your browser session** — never saved to disk

### Environment Variables (optional)
Copy `.env.example` to `.env` and fill in:
```
GROQ_API_KEY=your_key_here
GOOGLE_API_KEY=your_key_here
OPENAI_API_KEY=your_key_here
```

---

## 📊 Usage

1. Enter a research question in the **🔬 Research** tab
2. (Optional) Adjust **Advanced Options**: max sources, min confidence, memory usage
3. Click **🚀 Start Research**
4. Watch the **timeline** and **activity feed** update in real-time
5. Review the **report** with inline citations `[^n]`
6. **Export** as Markdown or PDF

---

## 🧠 How It Works

1. **Researcher** decomposes the query into 4-7 sub-questions and recalls prior findings from memory
2. **Web Searcher** runs DuckDuckGo searches per sub-question and fetches full page content
3. **Analyst** cross-references findings, scores source relevance, detects contradictions, and
   registers claims with citations via the `register_claim` tool
4. **Summarizer** writes a polished markdown report with inline citations and a source appendix

---

## 🌐 Deploy to Streamlit Community Cloud

1. Push this repo to GitHub
2. Go to https://share.streamlit.io
3. Connect your repo, set **Main file path** = `app.py`
4. (Optional) Add secrets in **Advanced settings** — they map to env vars:
   ```
   GROQ_API_KEY = "your_key"
   GOOGLE_API_KEY = "your_key"
   ```
5. Deploy!

**Note**: ChromaDB persistence works in the cloud sandbox. For the lightest deploy, you can
disable semantic memory (it's used as a cache, not required for reports).

---

## 📝 Notes

- **Free-tier only**: No paid services required. DuckDuckGo for search, Groq/Gemini for LLMs.
- **Session-only keys**: API keys entered in the UI never touch disk.
- **Rate limits**: Free tiers are rate-limited. Use the global-toggle + per-agent config to spread load.
- **PDF export**: Requires WeasyPrint system libraries (Pango, Cairo). On Windows, install via
  the WeasyPrint wheel or system packages. Markdown export always works.

---

## 📄 License

MIT — do whatever you want, just don't claim you built it from scratch if you didn't.

---

Built as a portfolio piece. Design matters.
