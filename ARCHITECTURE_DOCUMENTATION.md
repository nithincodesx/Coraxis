# Synapse Multi-Agent Research Laboratory — Architecture & Pipeline Documentation

This document provides a comprehensive overview of the system architecture, the 4-agent execution pipeline, feature capabilities, and how API keys (including free-tier & small quota keys) are managed throughout the application.

---

## 1. System Architecture Overview

Synapse is built as a **decoupled, high-performance web application** consisting of:

```
┌────────────────────────────────────────────────────────┐
│               Unified Next.js Frontend                 │
│               (http://localhost:3000)                  │
│   • Light Modern Workspace UI                          │
│   • Project Tree & Top Tabs (My Agents, AI Teams...)   │
│   • Live Pipeline Execution Feed & Markdown Viewer     │
└──────────────────────────┬─────────────────────────────┘
                           │ Next.js Rewrites (/api/*)
                           ▼
┌────────────────────────────────────────────────────────┐
│               FastAPI Thick Python Backend             │
│               (http://127.0.0.1:8000)                  │
│   • REST API Routes (/api/config, /api/research...)    │
│   • Worker Thread Executor                             │
│   • Citation Tracker & Activity Feed Logger            │
└──────────────────────────┬─────────────────────────────┘
                           │
       ┌───────────────────┼───────────────────┐
       ▼                   ▼                   ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  CrewAI 4x   │    │  ChromaDB    │    │  DuckDuckGo  │
│ Agent Chain  │    │ Vector Memory│    │ Web Scraper  │
└──────────────┘    └──────────────┘    └──────────────┘
```

- **Frontend**: Next.js 16 (App Router + Turbopack + Tailwind CSS) providing a single-host interface on `http://localhost:3000`.
- **Backend API**: FastAPI server (`api.py`) running on `http://127.0.0.1:8000` handling multi-agent orchestration, streaming callbacks, and citation tracking.
- **Agent Framework**: CrewAI + LangChain executing a 4-agent sequential workflow.
- **Semantic Memory**: ChromaDB vector store (`memory/chroma_client.py`) caching past research findings.
- **Search & Scraping**: DuckDuckGo search + Trafilatura clean text scraper (`tools/search_tools.py`).

---

## 2. The 4-Agent Research Pipeline

Research requests run sequentially through 4 specialized AI agents:

```
[Query Input] ──► 🔬 Researcher ──► 🔍 Web Searcher ──► 📊 Analyst ──► 📝 Summarizer ──► [Final Report]
```

### Step 1: 🔬 Senior Researcher
- **Role**: Query Decomposition & Memory Recall
- **Task**: Decomposes the main query into 4–7 surgical sub-questions covering distinct angles and queries ChromaDB semantic memory for prior findings.

### Step 2: 🔍 Web Searcher
- **Role**: Concurrent Web Resource Crawling
- **Task**: Executes DuckDuckGo queries for each sub-question, fetches full web page contents, extracts clean text, and filters out noise/paywalls.

### Step 3: 📊 Synthesis Analyst
- **Role**: Relevance Scoring & Claim Validation
- **Task**: Cross-references gathered text, detects contradictions, calculates source relevance scores (0–100%), and logs claims into the `CitationTracker`.

### Step 4: 📝 Lead Report Writer (Summarizer)
- **Role**: Publication Synthesis
- **Task**: Formats findings into an executive markdown publication containing inline citation tags (`[^1]`, `[^2]`), executive summary, key bullet points, and reference links.

---

## 3. API Key Architecture & Small Key Support

To ensure the architecture works seamlessly **even with free-tier keys or small quotas**, the LLM Factory implements intelligent fallbacks and lightweight default models:

### Provider & Model Defaults

| Provider | Default Model | Free Tier Compatibility |
| :--- | :--- | :--- |
| **Groq** | `llama-3.1-8b-instant` | ✅ **Excellent** (High RPM/TPM limit, fast execution) |
| **Google Gemini** | `gemini-1.5-flash` | ✅ **Excellent** (Generous free tier) |
| **OpenAI** | `gpt-4o-mini` | ✅ **Cost-Effective** (Low token cost) |
| **Ollama** | `llama3.1` | 🏠 **100% Local / Free** (No API key required) |

### Key Resolution Priority
When an agent executes, the API key is resolved in the following priority:
1. **Agent-Specific Key**: Key entered for that specific agent role in *Settings*.
2. **Global Master Key**: Master key set under *Use Global Master Key* in *Settings*.
3. **Environment Variables**: `GROQ_API_KEY`, `GOOGLE_API_KEY`, or `OPENAI_API_KEY` defined in `.env`.

> [!TIP]
> **Free-Tier Recommendation**: Use **Groq** with model `llama-3.1-8b-instant`. It provides high performance with 30 requests/min and zero rate-limit 429 errors.

---

## 4. Current Features Overview

1. **Workspace & Projects Dashboard (`My Agents` Tab)**:
   - View past research runs with tags (`Personal`, `Urgent`, `Work`).
   - Template banner cards (*Combine AI Agents in Team* & *Create New Project with AI*).

2. **AI Teams & Workflow Configurator (`AI Teams` Tab)**:
   - Team Coordinator overview card.
   - Model selection dropdown (`Groq`, `GPT-5`, `Gemini`, `Ollama`).
   - Interactive 7-step **Set Up Workflow** node chain.

3. **Interactive Research Workspace (`Automations & Research` Tab)**:
   - User prompt card & agent system status pills (*Setting new conversation with...*).
   - Rendered Markdown output with inline citation links `[^1]`.
   - Verified source table with relevance percentage bars (0-100%).
   - Real-time terminal activity log & one-click `.md` export.

4. **Automations & Settings Tab**:
   - Single-click key saving for Groq, Gemini, OpenAI, and Ollama.
   - **LangGraph Session & Connection Studio**: Connect to local LangGraph Studio (`http://127.0.0.1:8123`) or LangGraph Cloud.
   - **Interactive Session Creator**: Spawn new threads with custom thread IDs, topology blueprints (`coraxis_research_graph`, `multi_agent_pipeline`, `deep_research_v2`), and checkpointers (`MemorySaver`, `SqliteSaver`, `PostgresSaver`).
   - Active thread switcher and live ping latency diagnostics.
   - ChromaDB semantic memory toggle.

---

## 5. LangGraph REST Endpoints Reference

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/langgraph/config` | Retrieve active LangGraph server connection and active session ID |
| `POST` | `/api/langgraph/config` | Update LangGraph server URL, API key, and graph ID |
| `POST` | `/api/langgraph/test-connection` | Ping LangGraph endpoint and measure latency |
| `GET` | `/api/langgraph/sessions` | List all registered sessions, thread UUIDs, and checkpoint stats |
| `POST` | `/api/langgraph/sessions/new` | Create a new LangGraph thread session |
| `GET` | `/api/langgraph/sessions/{id}` | Inspect thread state, checkpoints, and execution history |
| `POST` | `/api/langgraph/sessions/{id}/activate` | Switch active research thread |
| `DELETE` | `/api/langgraph/sessions/{id}` | Remove a session and its checkpoint context |

---

## 6. Startup & Command Reference

Start both the FastAPI backend and Next.js frontend concurrently with a single command:

```powershell
python start.py
```

Then open your browser to **`http://localhost:3000`**.
