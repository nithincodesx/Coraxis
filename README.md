# 🔬 Coraxis — Autonomous Multi-Agent Research Platform

> Watch four AI agents research a topic live: search, cross-check sources, reason through findings, and hand you back a cited report. Built solo on an entirely free stack, no paid keys required.

---

## ✨ Key Features

- **4-Agent Sequential Pipeline** (CrewAI): Senior Researcher → Web Searcher → Synthesis Analyst → Lead Report Writer
- **LangGraph Session & Connection Studio**: Manage persistent LangGraph thread sessions, checkpoint state trees, and local Studio / Cloud connectivity
- **AAS Core Skill Control Plane**: Integrated 2,005+ agentic skill catalog discovery (`tools/aas_tools.py`) and `.agents/skills` control plane
- **Decoupled Modern Architecture**: Next.js 16 (Turbopack) frontend + FastAPI backend with async streaming
- **Per-Agent & Global Key Configuration**: Supports Groq (Llama 3.1 8B Instant / 3.3 70B), Gemini, OpenAI, and Ollama (local)
- **LiteLLM Compatibility & Resilient Model Fallback**: Automatic message sanitization for Groq compatibility (`cache_breakpoint` filtering)
- **Citation Tracking & Verification**: Automatic source attribution with relevance scores and markdown reference generation
- **Semantic Memory Engine** (ChromaDB): Vector storage for query caching and cross-session knowledge retrieval
- **CLI & REST Health Monitoring**: GET `/api/health`, GET `/api/metrics`, GET `/api/langgraph/sessions`, and `scripts/health_check.py` CLI utility

---

## 🏗️ Production Architecture

```
Coraxis/
├── start.py                # Dual-process launcher (FastAPI backend + Next.js frontend)
├── api.py                  # FastAPI REST backend endpoints & LangGraph session controller
├── agents.py               # CrewAI 4-Agent definitions & LLM bindings
├── tasks.py                # Sequential Pydantic task definitions
├── frontend/               # Next.js 16 frontend application
│   ├── src/app/page.tsx    # Interactive dashboard with real-time pipeline feed & LangGraph manager
│   ├── src/app/layout.tsx  # Coraxis metadata and global layout
│   └── src/app/globals.css # Neo-brutalist Warm Sand design system
├── tools/                  # Search, fetch, citation, and AAS tools
│   ├── search.py           # DuckDuckGo search & page fetching
│   ├── citations.py        # CitationTracker
│   └── aas_tools.py        # AAS Core skill catalog discovery
├── memory/
│   └── chroma_client.py    # ChromaDB vector store
├── utils/
│   ├── llm_factory.py      # Dynamic LLM creation & litellm completion sanitizer
│   └── langgraph_client.py # LangGraph session, thread & checkpoint manager
├── scripts/
│   └── health_check.py     # CLI system health verification
└── tests/
    └── test_llm_factory.py # Automated unit tests
```

---

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+
- A free Groq API key: [https://console.groq.com](https://console.groq.com)

### Installation & Execution

```bash
# 1. Clone repository
git clone https://github.com/nithincodesx/Coraxis.git
cd Coraxis

# 2. Set up Python virtual environment
python -m venv .venv
.\.venv\Scripts\activate

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. Install Frontend dependencies
cd frontend
npm install
cd ..

# 5. Launch both servers with a single command
python start.py
```

- **Frontend**: [http://localhost:3000](http://localhost:3000)
- **FastAPI Backend**: [http://127.0.0.1:8000](http://127.0.0.1:8000)

---

## 🧪 System Health Verification

To verify that the system servers, health endpoints, and config interfaces are functioning:

```bash
python scripts/health_check.py
```

To run unit tests:

```bash
python -m unittest discover tests
```

---

## 📝 License

MIT — Created by [nithincodesx](https://github.com/nithincodesx).
