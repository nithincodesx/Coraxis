"use client";

import React, { useState, useEffect, useRef } from "react";
import {
  Home as HomeIcon,
  Bell,
  Database,
  BarChart2,
  Calendar,
  FileText,
  Settings,
  User,
  Plus,
  Star,
  ChevronRight,
  ChevronDown,
  Search,
  Zap,
  Check,
  MoreHorizontal,
  Send,
  Paperclip,
  Maximize2,
  Flame,
  Bot,
  Users as UsersIcon,
  Sliders,
  Sparkles,
  ExternalLink,
  Edit2,
  ShieldCheck,
  Loader2,
  CheckCircle,
  AlertCircle,
  Download,
  BookOpen,
  Share2,
  Copy,
  Trash2,
  RefreshCw,
  Activity,
  Network,
  Layers
} from "lucide-react";

// Backend API interface types
interface AgentState {
  status: "pending" | "running" | "done" | "error";
  progress: number;
  elapsed: number;
  elapsed_str: string;
  error_msg: string;
}

interface LangGraphSessionDTO {
  session_id: string;
  thread_id: string;
  name: string;
  graph_id: string;
  checkpointer: string;
  status: string;
  created_at: string;
  checkpoint_count: number;
  tags: string[];
}

interface LangGraphConfigDTO {
  endpoint_url: string;
  assistant_id: string;
  sync_mode: string;
  checkpointer_type: string;
  is_connected: boolean;
  last_ping?: string;
  latency_ms?: number;
  active_session_id?: string;
  has_api_key?: boolean;
}

interface Source {
  id: number;
  title: string;
  url: string;
  relevance: number;
  relevance_pct: number;
  claims: number;
}

interface StatusResponse {
  is_running: boolean;
  query: string;
  timestamp: string;
  agent_states: Record<string, AgentState>;
  final_report: string;
  report_stats: {
    total_sources?: number;
    total_claims?: number;
    avg_confidence?: number;
    avg_relevance?: number;
    runtime_seconds?: number;
  };
  sources: Source[];
}

interface LogEntry {
  timestamp: number;
  time_str: string;
  agent: string;
  message: string;
  level: "info" | "success" | "warning" | "error";
}

interface HistoryItem {
  query: string;
  timestamp: string;
  stats: Record<string, any>;
}

export default function Home() {
  // Main Top Navigation Tab State: 'agents' | 'teams' | 'workspace' | 'settings'
  const [activeTab, setActiveTab] = useState<"agents" | "teams" | "workspace" | "settings">("agents");
  
  // Selected Sidebar Project State
  const [activeProject, setActiveProject] = useState("Landing Design");

  // Middle Form State for AI Teams Tab
  const [middleFormTab, setMiddleFormTab] = useState<"basic" | "tools" | "schedules" | "advanced">("basic");
  const [selectedModel, setSelectedModel] = useState("Groq (Llama 3.3 70B)");
  const [teamTaskPrompt, setTeamTaskPrompt] = useState(
    "Your task is to conduct multi-agent research from scratch, crawl web resources, extract claims, calculate confidence scores, and synthesize a structured markdown publication."
  );

  // Backend Research Pipeline State
  const [queryInput, setQueryInput] = useState("Need A New Design For Landing Page");
  const [isRunning, setIsRunning] = useState(false);
  const [pipelineQuery, setPipelineQuery] = useState("");
  const [runTimestamp, setRunTimestamp] = useState("");
  const [agentStates, setAgentStates] = useState<Record<string, AgentState>>({
    researcher: { status: "pending", progress: 0, elapsed: 0, elapsed_str: "0s", error_msg: "" },
    web_searcher: { status: "pending", progress: 0, elapsed: 0, elapsed_str: "0s", error_msg: "" },
    analyst: { status: "pending", progress: 0, elapsed: 0, elapsed_str: "0s", error_msg: "" },
    summarizer: { status: "pending", progress: 0, elapsed: 0, elapsed_str: "0s", error_msg: "" }
  });
  const [finalReport, setFinalReport] = useState("");
  const [reportStats, setReportStats] = useState<any>({});
  const [sources, setSources] = useState<Source[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [historyLoadedIndex, setHistoryLoadedIndex] = useState(-1);
  const chatInputRef = useRef<HTMLInputElement>(null);
  const [activeNodeIdx, setActiveNodeIdx] = useState(-1);

  const handleNewProject = () => {
    setQueryInput("");
    setActiveTab("workspace");
    setTimeout(() => chatInputRef.current?.focus(), 100);
  };

  // API Config State
  const [useGlobalKey, setUseGlobalKey] = useState(false);
  const [globalProvider, setGlobalProvider] = useState("groq");
  const [globalKey, setGlobalKey] = useState("");
  const [agentsConfig, setAgentsConfig] = useState<Record<string, { provider: string; model: string; key_set?: boolean }>>({
    researcher: { provider: "groq", model: "" },
    web_searcher: { provider: "groq", model: "" },
    analyst: { provider: "groq", model: "" },
    summarizer: { provider: "groq", model: "" }
  });

  // LangGraph Connection & Session State
  const [langgraphConfig, setLanggraphConfig] = useState<LangGraphConfigDTO>({
    endpoint_url: "http://127.0.0.1:8123",
    assistant_id: "coraxis_research_graph",
    sync_mode: "local",
    checkpointer_type: "in_memory",
    is_connected: true,
    active_session_id: "lg-sess-primary"
  });
  const [langgraphSessions, setLanggraphSessions] = useState<LangGraphSessionDTO[]>([]);
  const [isTestingLangGraph, setIsTestingLangGraph] = useState(false);
  const [isCreatingSession, setIsCreatingSession] = useState(false);
  const [newSessionName, setNewSessionName] = useState("");
  const [newSessionGraph, setNewSessionGraph] = useState("coraxis_research_graph");
  const [newSessionCheckpointer, setNewSessionCheckpointer] = useState("MemorySaver");
  const [showSessionForm, setShowSessionForm] = useState(false);

  // Notification Toasts
  const [alert, setAlert] = useState<{ type: "success" | "error" | "info"; msg: string } | null>(null);
  const [isConfigSaving, setIsConfigSaving] = useState(false);

  const API_URL = ""; // Relative proxy path

  // Initial load
  useEffect(() => {
    fetchConfig();
    fetchHistory();
    fetchLangGraphConfig();
    fetchLangGraphSessions();
    pollStatus();
  }, []);

  // Poll execution status
  useEffect(() => {
    let intervalId: any;
    if (isRunning) {
      intervalId = setInterval(() => {
        pollStatus();
      }, 1200);
    } else {
      pollStatus();
    }
    return () => clearInterval(intervalId);
  }, [isRunning]);

  const showAlert = (type: "success" | "error" | "info", msg: string) => {
    setAlert({ type, msg });
    setTimeout(() => setAlert(null), 4000);
  };

  const fetchLangGraphConfig = async () => {
    try {
      const res = await fetch(`${API_URL}/api/langgraph/config`);
      if (!res.ok) return;
      const data = await res.json();
      setLanggraphConfig(data);
    } catch (e) {
      console.error("LangGraph config fetch error", e);
    }
  };

  const fetchLangGraphSessions = async () => {
    try {
      const res = await fetch(`${API_URL}/api/langgraph/sessions`);
      if (!res.ok) return;
      const data = await res.json();
      setLanggraphSessions(data.sessions || []);
    } catch (e) {
      console.error("LangGraph sessions fetch error", e);
    }
  };

  const testLangGraphConnection = async () => {
    setIsTestingLangGraph(true);
    try {
      const res = await fetch(`${API_URL}/api/langgraph/test-connection`, { method: "POST" });
      const data = await res.json();
      if (data.status === "connected") {
        showAlert("success", `LangGraph Server Connected (${data.latency_ms}ms)`);
        setLanggraphConfig((prev) => ({
          ...prev,
          is_connected: true,
          latency_ms: data.latency_ms,
          last_ping: data.timestamp
        }));
      } else {
        showAlert("error", `Connection failed: ${data.message}`);
      }
    } catch (e) {
      showAlert("error", "Could not reach LangGraph server endpoint.");
    } finally {
      setIsTestingLangGraph(false);
    }
  };

  const createLangGraphSession = async () => {
    setIsCreatingSession(true);
    try {
      const res = await fetch(`${API_URL}/api/langgraph/sessions/new`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: newSessionName.trim() || `Research Thread #${langgraphSessions.length + 1}`,
          graph_id: newSessionGraph,
          checkpointer: newSessionCheckpointer,
          tags: ["coraxis", "client-created"]
        })
      });
      const data = await res.json();
      if (data.status === "success") {
        showAlert("success", `Session created: ${data.session.name}`);
        setNewSessionName("");
        setShowSessionForm(false);
        fetchLangGraphSessions();
        fetchLangGraphConfig();
      } else {
        showAlert("error", `Failed to create session: ${data.message}`);
      }
    } catch (e) {
      showAlert("error", "Error contacting API backend to create session.");
    } finally {
      setIsCreatingSession(false);
    }
  };

  const activateLangGraphSession = async (sessionId: string) => {
    try {
      const res = await fetch(`${API_URL}/api/langgraph/sessions/${sessionId}/activate`, { method: "POST" });
      const data = await res.json();
      if (data.status === "success") {
        showAlert("success", `Activated session ${sessionId}`);
        fetchLangGraphConfig();
        fetchLangGraphSessions();
      } else {
        showAlert("error", `Failed to activate: ${data.message}`);
      }
    } catch (e) {
      showAlert("error", "Error setting active session.");
    }
  };

  const deleteLangGraphSession = async (sessionId: string) => {
    try {
      const res = await fetch(`${API_URL}/api/langgraph/sessions/${sessionId}`, { method: "DELETE" });
      const data = await res.json();
      if (data.status === "success") {
        showAlert("info", `Deleted session ${sessionId}`);
        fetchLangGraphConfig();
        fetchLangGraphSessions();
      } else {
        showAlert("error", `Failed to delete: ${data.message}`);
      }
    } catch (e) {
      showAlert("error", "Error deleting session.");
    }
  };

  const fetchConfig = async () => {
    try {
      const res = await fetch(`${API_URL}/api/config`);
      if (!res.ok) return;
      const data = await res.json();
      setUseGlobalKey(data.use_global_key);
      setGlobalProvider(data.global_provider);
      
      const configMap: any = {};
      Object.keys(data.agents).forEach((key) => {
        configMap[key] = {
          provider: data.agents[key].provider,
          model: data.agents[key].model,
          key_set: data.agents[key].key_set
        };
      });
      setAgentsConfig(configMap);
    } catch (e) {
      console.error("Config fetch error", e);
    }
  };

  const saveConfig = async () => {
    setIsConfigSaving(true);
    try {
      const payload = {
        use_global_key: useGlobalKey,
        global_provider: globalProvider,
        global_key: globalKey,
        agents: Object.keys(agentsConfig).reduce((acc: any, key) => {
          acc[key] = {
            provider: agentsConfig[key].provider,
            model: agentsConfig[key].model,
            api_key: (document.getElementById(`api-key-${key}`) as HTMLInputElement)?.value || ""
          };
          return acc;
        }, {})
      };

      const res = await fetch(`${API_URL}/api/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (data.status === "success") {
        showAlert("success", "API configuration saved successfully!");
        fetchConfig();
      } else {
        showAlert("error", `Save failed: ${data.message}`);
      }
    } catch (e) {
      showAlert("error", "Could not connect to FastAPI backend server.");
    } finally {
      setIsConfigSaving(false);
    }
  };

  const fetchHistory = async () => {
    try {
      const res = await fetch(`${API_URL}/api/history`);
      if (!res.ok) return;
      const data = await res.json();
      setHistory(data);
    } catch (e) {
      console.error("History fetch error", e);
    }
  };

  const selectHistoryProject = async (index: number) => {
    try {
      const res = await fetch(`${API_URL}/api/history/select`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ index })
      });
      const data = await res.json();
      if (data.status === "success") {
        setHistoryLoadedIndex(index);
        setActiveTab("workspace");
        pollStatus();
      } else {
        showAlert("error", `Failed to load: ${data.message}`);
      }
    } catch (e) {
      showAlert("error", "Error contacting API server.");
    }
  };

  const pollStatus = async () => {
    try {
      const resStatus = await fetch(`${API_URL}/api/status`);
      if (!resStatus.ok) return;
      const dataStatus: StatusResponse = await resStatus.json();
      
      setIsRunning(dataStatus.is_running);
      setPipelineQuery(dataStatus.query);
      setRunTimestamp(dataStatus.timestamp);
      setAgentStates(dataStatus.agent_states);
      setFinalReport(dataStatus.final_report);
      setReportStats(dataStatus.report_stats);
      setSources(dataStatus.sources);

      if (dataStatus.is_running || dataStatus.query) {
        const resLogs = await fetch(`${API_URL}/api/logs`);
        if (resLogs.ok) {
          const dataLogs = await resLogs.json();
          setLogs(dataLogs);
        }
      }
    } catch (e) {
      console.error("Status polling error", e);
    }
  };

  const triggerResearch = async () => {
    if (!queryInput.trim()) return;
    
    setFinalReport("");
    setSources([]);
    setLogs([]);
    setHistoryLoadedIndex(-1);

    try {
      const res = await fetch(`${API_URL}/api/research`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: queryInput,
          max_sources: 5,
          min_confidence: 0.3,
          include_memory: true
        })
      });
      const data = await res.json();
      if (data.status === "success") {
        setIsRunning(true);
        setActiveTab("workspace");
        showAlert("info", "Multi-Agent task sequence kicked off!");
        fetchHistory();
      } else {
        showAlert("error", `Failed to start: ${data.message}`);
      }
    } catch (e) {
      showAlert("error", "Ensure backend server is running on port 8000.");
    }
  };

  // Helper inline style parser
  const renderInlineStyles = (text: string) => {
    const regex = /(\*\*.*?\*\*|`.*?`|\[\^\d+\])/g;
    const parts = text.split(regex);
    return parts.map((part, index) => {
      if (part.startsWith("**") && part.endsWith("**")) {
        return (
          <strong key={index} className="font-semibold text-slate-900">
            {part.slice(2, -2)}
          </strong>
        );
      }
      if (part.startsWith("`") && part.endsWith("`")) {
        return (
          <code
            key={index}
            className="font-mono text-xs bg-slate-100 text-indigo-600 px-1.5 py-0.5 rounded border border-slate-200"
          >
            {part.slice(1, -1)}
          </code>
        );
      }
      if (part.startsWith("[^") && part.endsWith("]")) {
        const num = part.slice(2, -1);
        return (
          <sup key={index} className="align-super text-[10px] font-mono font-bold text-indigo-600 ml-0.5 hover:underline">
            <a href={`#source-${num}`}>[{num}]</a>
          </sup>
        );
      }
      return part;
    });
  };

  const parseMarkdownToReact = (markdownText: string) => {
    if (!markdownText) return null;
    const lines = markdownText.split("\n");
    let listItems: React.ReactNode[] = [];
    const elements: React.ReactNode[] = [];

    const flushList = (key: number) => {
      if (listItems.length > 0) {
        elements.push(
          <ul key={`list-${key}`} className="list-disc pl-5 mb-3 space-y-1 text-slate-700">
            {listItems}
          </ul>
        );
        listItems = [];
      }
    };

    lines.forEach((line, index) => {
      const trimmed = line.trim();

      if (trimmed.startsWith("# ")) {
        flushList(index);
        elements.push(
          <h1 key={index} className="text-xl font-bold font-display text-slate-900 mt-4 mb-2">
            {trimmed.slice(2)}
          </h1>
        );
      } else if (trimmed.startsWith("## ")) {
        flushList(index);
        elements.push(
          <h2 key={index} className="text-lg font-semibold font-display text-slate-900 mt-3 mb-2 border-b border-slate-100 pb-1">
            {trimmed.slice(3)}
          </h2>
        );
      } else if (trimmed.startsWith("### ")) {
        flushList(index);
        elements.push(
          <h3 key={index} className="text-base font-semibold font-display text-slate-800 mt-3 mb-1">
            {trimmed.slice(4)}
          </h3>
        );
      } else if (trimmed.startsWith("> ")) {
        flushList(index);
        elements.push(
          <blockquote key={index} className="border-l-4 border-indigo-500 pl-3 py-1.5 italic bg-slate-50 text-slate-700 my-3 rounded-r-md text-xs">
            {renderInlineStyles(trimmed.slice(2))}
          </blockquote>
        );
      } else if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
        listItems.push(
          <li key={index} className="text-xs leading-relaxed text-slate-700">
            {renderInlineStyles(trimmed.slice(2))}
          </li>
        );
      } else if (!trimmed) {
        flushList(index);
      } else {
        flushList(index);
        elements.push(
          <p key={index} className="text-xs leading-relaxed text-slate-700 mb-3">
            {renderInlineStyles(trimmed)}
          </p>
        );
      }
    });

    flushList(lines.length);
    return elements;
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[#faf7f2] text-[#1c2331] font-sans">
      
      {/* ─── 1. LEFTMOST VERTICAL ICON STRIP ─── */}
      <div className="flex flex-col items-center justify-between w-14 bg-white border-r-1.5 border-[#1c2331] py-4 shrink-0 z-30 shadow-[2px_0px_0px_#1c2331]">
        <div className="flex flex-col items-center gap-4 w-full">
          {/* Brand Sigil App Logo (Frameless, Blends directly into page) */}
          <div className="w-10 h-10 flex items-center justify-center cursor-pointer transition-all hover:scale-115 p-0.5">
            <img
              src="/brand_sigil.jpg"
              alt="Brand Sigil Logo"
              className="w-full h-full object-contain mix-blend-multiply"
            />
          </div>
          
          <div className="w-6 border-b border-slate-200 my-1" />

          {/* Navigation Icons matching Template */}
          <button onClick={() => setActiveTab("agents")} className={`w-9 h-9 rounded-full flex items-center justify-center transition-all ${activeTab === "agents" ? "bg-[#1c2331] text-white font-bold shadow-[2px_2px_0px_#8b5cf6]" : "text-slate-500 hover:text-slate-900 hover:bg-slate-100"}`} title="Home">
            <HomeIcon size={18} />
          </button>

          <button onClick={() => setActiveTab("workspace")} className={`w-9 h-9 rounded-full flex items-center justify-center transition-all ${activeTab === "workspace" ? "bg-[#1c2331] text-white font-bold shadow-[2px_2px_0px_#f43f5e]" : "text-slate-500 hover:text-slate-900 hover:bg-slate-100"}`} title="Projects & Workspace">
            <Database size={18} />
          </button>

          <button onClick={() => setActiveTab("teams")} className={`w-9 h-9 rounded-full flex items-center justify-center transition-all ${activeTab === "teams" ? "bg-[#1c2331] text-white font-bold shadow-[2px_2px_0px_#f4a261]" : "text-slate-500 hover:text-slate-900 hover:bg-slate-100"}`} title="AI Teams Workflow">
            <BarChart2 size={18} />
          </button>

          <button onClick={() => setActiveTab("settings")} className={`w-9 h-9 rounded-full flex items-center justify-center transition-all ${activeTab === "settings" ? "bg-[#1c2331] text-white font-bold shadow-[2px_2px_0px_#10b981]" : "text-slate-500 hover:text-slate-900 hover:bg-slate-100"}`} title="Settings">
            <Settings size={18} />
          </button>
        </div>

        <button className="w-8 h-8 rounded-full bg-white border-1.5 border-[#1c2331] text-slate-700 flex items-center justify-center text-xs font-bold shadow-[1.5px_1.5px_0px_#1c2331]" title="User Profile">
          <User size={16} />
        </button>
      </div>


      {/* ─── 2. SECOND COLUMN: MY WORKSPACE TREE SIDEBAR ─── */}
      <div className="flex flex-col w-60 bg-white border-r-1.5 border-[#1c2331] py-5 shrink-0 z-20">
        <div className="px-5 mb-4">
          <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500 font-mono">MY WORKSPACE</span>
        </div>

        <div className="flex-1 overflow-y-auto px-3 space-y-4">
          
          {/* Section 1: Personal Projects */}
          <div>
            <div className="flex items-center gap-2 px-2 py-1 text-xs font-semibold text-slate-700 cursor-pointer">
              <span className="text-amber-500 text-sm">🔥</span>
              <span>Personal Projects</span>
            </div>
          </div>

          {/* Section 2: Main Workspace Tree */}
          <div>
            <div className="flex items-center gap-2 px-2 py-1 text-xs font-bold text-slate-900 cursor-pointer">
              <span className="text-emerald-500 text-sm">🌳</span>
              <span>Main Workspace</span>
            </div>
            
            <div className="pl-6 pt-1 space-y-0.5 border-l-1.5 border-slate-300 ml-4">
              {[
                { name: "UX Project", icon: "💡" },
                { name: "Landing Design", icon: "🔥" },
                { name: "SEO", icon: "📝" },
                { name: "Brainstorm", icon: "🧠" }
              ].map((item) => (
                <button
                  key={item.name}
                  onClick={() => {
                    setActiveProject(item.name);
                    setActiveTab("workspace");
                  }}
                  className={`w-full text-left px-2.5 py-1.5 rounded-lg text-xs flex items-center gap-2 transition-all ${
                    activeProject === item.name
                      ? "bg-[#faf7f2] font-bold text-[#1c2331] border-1.5 border-[#1c2331] shadow-[1.5px_1.5px_0px_#1c2331]"
                      : "text-slate-600 hover:bg-slate-50 hover:text-slate-900"
                  }`}
                >
                  <span className="text-xs">{item.icon}</span>
                  <span className="truncate">{item.name}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Section 3: Additional Workspace Categories */}
          <div className="space-y-1 pt-1">
            {[
              { label: "Work Team Org", icon: "📝" },
              { label: "Study", icon: "🧠" },
              { label: "AI Agents Description", icon: "🔥" },
              { label: "Product Management", icon: "💎" }
            ].map((cat, i) => (
              <div key={i} className="flex items-center gap-2 px-2 py-1.5 rounded-lg text-xs font-medium text-slate-600 hover:bg-slate-50 cursor-pointer transition-all">
                <span>{cat.icon}</span>
                <span className="truncate">{cat.label}</span>
              </div>
            ))}
          </div>

          {/* Add New Button */}
          <div className="pt-2">
            <button className="w-full border-1.5 border-dashed border-[#1c2331] hover:bg-[#faf7f2] rounded-xl py-2 text-xs font-bold text-[#1c2331] flex items-center justify-center gap-1.5 transition-all cursor-pointer">
              <span>Add New</span>
              <Plus size={14} />
            </button>
          </div>
        </div>
      </div>


      {/* ─── 3. MAIN DASHBOARD CONTENT AREA ─── */}
      <div className="flex flex-col flex-1 min-w-0 relative bg-[#faf7f2] overflow-hidden">
        
        {/* Floating Notification Toast */}
        {alert && (
          <div className="absolute top-4 right-6 flex items-center gap-2.5 bg-[#1c2331] text-white text-xs px-4 py-2.5 rounded-xl border-1.5 border-[#1c2331] shadow-[3px_3px_0px_#f43f5e] z-50 animate-slide-in font-display font-semibold">
            {alert.type === "info" && <Loader2 size={15} className="animate-spin text-purple-400" />}
            {alert.type === "success" && <CheckCircle size={15} className="text-emerald-400" />}
            {alert.type === "error" && <AlertCircle size={15} className="text-rose-400" />}
            <span>{alert.msg}</span>
          </div>
        )}

        {/* Dashboard Top Header Bar */}
        <header className="flex items-center justify-between px-8 py-4 bg-white border-b-1.5 border-[#1c2331] shrink-0">
          <div>
            <div className="flex items-center gap-1.5 text-xs text-slate-500 font-medium">
              <span>Home</span>
              <ChevronRight size={12} />
              <span>Main Workspace</span>
              <ChevronRight size={12} />
              <span className="text-[#1c2331] font-bold font-mono">{activeTab.toUpperCase()}</span>
            </div>
            <h1 className="text-xl font-bold font-display text-[#1c2331] mt-0.5">
              {activeTab === "agents" && "Workspace Overview"}
              {activeTab === "teams" && "AI Team Configuration"}
              {activeTab === "workspace" && (pipelineQuery || activeProject)}
              {activeTab === "settings" && "Automations & Settings"}
            </h1>
          </div>

          <div className="flex items-center gap-2">
            <button className="w-8 h-8 rounded-lg border-1.5 border-[#1c2331] flex items-center justify-center text-slate-700 hover:bg-[#faf7f2] shadow-[1.5px_1.5px_0px_#1c2331]" title="Favorite">
              <Star size={16} />
            </button>
            <button className="w-8 h-8 rounded-lg border-1.5 border-[#1c2331] flex items-center justify-center text-slate-700 hover:bg-[#faf7f2] shadow-[1.5px_1.5px_0px_#1c2331]" title="Settings">
              <Settings size={16} />
            </button>
            <button
              onClick={handleNewProject}
              className="btn-neo-primary text-xs px-4 py-2 flex items-center gap-1.5 cursor-pointer"
            >
              <span>New Project</span>
              <Plus size={14} />
            </button>
          </div>
        </header>

        {/* Horizontal Navigation Cards */}
        <div className="px-8 py-3.5 bg-white border-b-1.5 border-[#1c2331] flex items-center gap-3 shrink-0">
          {[
            { id: "agents", label: "My Agents", icon: "🤖" },
            { id: "teams", label: "AI Teams", icon: "🤝" },
            { id: "workspace", label: "Automations & Research", icon: "📝" },
            { id: "settings", label: "Import & Settings", icon: "🔥" }
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as any)}
              className={`flex items-center gap-2 px-5 py-2.5 rounded-xl text-xs font-display font-bold transition-all border-1.5 ${
                activeTab === tab.id
                  ? "bg-[#faf7f2] border-[#1c2331] text-[#1c2331] shadow-[2.5px_2.5px_0px_#1c2331]"
                  : "bg-white border-slate-200 text-slate-600 hover:text-slate-900 hover:border-[#1c2331]"
              }`}
            >
              <span>{tab.icon}</span>
              <span>{tab.label}</span>
            </button>
          ))}
        </div>


        {/* ─── TAB ROUTING CONTENT ─── */}
        <div className="flex-1 overflow-y-auto p-8">

          {/* ════════════════════════════════════════════════════════════ */}
          {/* TAB 1: MY AGENTS & PROJECTS OVERVIEW (IMAGE 1) */}
          {/* ════════════════════════════════════════════════════════════ */}
          {activeTab === "agents" && (
            <div className="max-w-6xl mx-auto space-y-6 animate-fade-in">
              
              {/* Projects List Card Table (Matching Image 1) */}
              <div>
                <span className="text-xs font-bold text-slate-700 block mb-3 font-display">Projects</span>
                <div className="space-y-2.5">
                  {[
                    { name: "UX Project", icon: "💡", date: "12.12.2023", badges: [{ text: "Personal", type: "purple" }, { text: "Work", type: "purple" }] },
                    { name: "Landing Design", icon: "🔥", date: "05.08.2023", badges: [{ text: "Urgent", type: "mint" }] },
                    { name: "SEO", icon: "📝", date: "14.09.2023", badges: [{ text: "Urgent", type: "mint" }] },
                    { name: "Brainstorm", icon: "🧠", date: "12.12.2023", badges: [{ text: "Personal", type: "purple" }, { text: "Work", type: "purple" }] }
                  ].map((proj, idx) => (
                    <div
                      key={idx}
                      onClick={() => {
                        setActiveProject(proj.name);
                        setActiveTab("workspace");
                      }}
                      className="template-card p-4 flex items-center justify-between hover:border-slate-300 transition-all cursor-pointer bg-white"
                    >
                      <div className="flex items-center gap-3">
                        <span className="text-base">{proj.icon}</span>
                        <span className="text-sm font-semibold text-slate-800 font-display">{proj.name}</span>
                      </div>

                      <div className="flex items-center gap-3">
                        <span className="text-xs text-slate-400 font-mono flex items-center gap-1">
                          📅 {proj.date}
                        </span>
                        
                        {proj.badges.map((b, i) => (
                          <span
                            key={i}
                            className={`text-[10px] font-medium px-2.5 py-0.5 rounded-full ${
                              b.type === "purple" ? "badge-purple" : "badge-mint"
                            }`}
                          >
                            {b.text}
                          </span>
                        ))}

                        <button className="text-slate-400 hover:text-slate-600 p-1">
                          <MoreHorizontal size={16} />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Bottom Promo Cards (Matching Image 1) */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6 pt-4">
                
                {/* Banner 1: Combine AI Agents in Team */}
                <div className="template-card p-6 bg-gradient-to-br from-emerald-50 via-teal-50 to-white relative overflow-hidden flex flex-col justify-between h-[210px]">
                  <div className="z-10">
                    <div className="flex gap-2 mb-3">
                      <span className="text-[10px] font-semibold bg-white border border-slate-200 px-2.5 py-0.5 rounded-full text-slate-600 shadow-xs">
                        AI Team ⚡
                      </span>
                      <span className="text-[10px] font-semibold bg-white border border-slate-200 px-2.5 py-0.5 rounded-full text-slate-600 shadow-xs">
                        AI Agent 🤖
                      </span>
                    </div>
                    <h3 className="text-xl font-bold font-display text-slate-900 max-w-xs">
                      Combine AI Agents in Team
                    </h3>
                    <p className="text-xs text-slate-500 mt-1">Get Full Team in a Couple Clicks</p>
                  </div>
                  
                  {/* Decorative mesh vector background */}
                  <div className="absolute right-[-20px] bottom-[-20px] w-48 h-48 opacity-25 pointer-events-none">
                    <div className="w-full h-full rounded-full border-4 border-emerald-400/40 animate-spin" style={{ animationDuration: "20s" }} />
                  </div>
                </div>

                {/* Banner 2: Create New Project with AI */}
                <div className="template-card p-6 bg-[#eeeffe] border-indigo-100 flex items-center justify-between h-[210px]">
                  <div className="flex gap-5 items-center">
                    <div className="w-24 h-24 rounded-2xl bg-slate-900 flex items-center justify-center text-4xl shadow-md shrink-0">
                      🤖
                    </div>
                    <div className="space-y-1">
                      <h3 className="text-lg font-bold font-display text-slate-900">
                        Create New Project with AI
                      </h3>
                      <p className="text-xs text-slate-600 max-w-xs leading-relaxed">
                        Use ready-made templates to create new projects. Configured agents for tasks are already trained.
                      </p>
                      <button
                        onClick={handleNewProject}
                        className="bg-[#111827] hover:bg-slate-800 text-white font-semibold font-display text-xs px-4 py-2 rounded-lg shadow-xs transition-all mt-2"
                      >
                        New Project
                      </button>
                    </div>
                  </div>
                </div>

              </div>
            </div>
          )}


          {/* ════════════════════════════════════════════════════════════ */}
          {/* TAB 2: AI TEAMS CONFIGURATION & WORKFLOW (IMAGE 2) */}
          {/* ════════════════════════════════════════════════════════════ */}
          {activeTab === "teams" && (
            <div className="max-w-6xl mx-auto grid grid-cols-1 lg:grid-cols-3 gap-6 animate-fade-in">
              
              {/* Left Column: Team Coordinator Card & Agent Roles */}
              <div className="space-y-5">
                
                {/* Team Coordinator Card */}
                <div className="template-card overflow-hidden">
                  <div className="h-20 bg-gradient-to-r from-teal-100 via-indigo-100 to-purple-100 flex items-center justify-center">
                    <div className="w-14 h-14 rounded-2xl bg-white border border-slate-200 flex items-center justify-center text-2xl shadow-sm translate-y-4">
                      🤖
                    </div>
                  </div>
                  <div className="p-5 pt-8 text-center">
                    <h3 className="font-bold text-base font-display text-slate-900">Team Coordinator</h3>
                    <p className="text-xs text-slate-500 mt-1 leading-relaxed">
                      Manages communication, schedules, and resources for an AI team.
                    </p>
                  </div>
                </div>

                {/* Agents List */}
                <div className="template-card p-4">
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-xs font-bold font-display text-slate-800">Agents</span>
                    <Settings size={14} className="text-slate-400 cursor-pointer" />
                  </div>
                  <div className="space-y-1.5">
                    {[
                      { name: "Senior Researcher", icon: "🔬", color: "badge-purple" },
                      { name: "Search Specialist", icon: "🔍", color: "badge-mint" },
                      { name: "Synthesis Analyst", icon: "📊", color: "badge-amber" },
                      { name: "Lead Report Writer", icon: "📝", color: "badge-purple" },
                      { name: "Brand Strategist", icon: "🌲", color: "badge-mint" }
                    ].map((agent, i) => (
                      <div key={i} className="flex items-center justify-between p-2 rounded-xl bg-slate-50 border border-slate-200/60 hover:bg-white transition-all text-xs">
                        <div className="flex items-center gap-2">
                          <span>{agent.icon}</span>
                          <span className="font-semibold text-slate-800">{agent.name}</span>
                        </div>
                        <span className="text-slate-400">⚙️</span>
                      </div>
                    ))}
                    <button className="w-full border border-dashed border-slate-300 rounded-xl py-2 text-xs font-medium text-slate-500 hover:text-slate-800 flex items-center justify-center gap-1 mt-2">
                      <span>Add New</span>
                      <Plus size={14} />
                    </button>
                  </div>
                </div>
              </div>

              {/* Middle Form Column (Matching Image 2) */}
              <div className="template-card p-6 space-y-5">
                
                {/* Form Tabs */}
                <div className="flex items-center gap-1 bg-slate-100 p-1 rounded-xl border border-slate-200 text-xs font-medium">
                  {["basic", "tools", "schedules", "advanced"].map((tabKey) => (
                    <button
                      key={tabKey}
                      onClick={() => setMiddleFormTab(tabKey as any)}
                      className={`flex-1 py-1.5 rounded-lg capitalize transition-all ${
                        middleFormTab === tabKey ? "bg-white text-slate-900 font-semibold shadow-xs" : "text-slate-500 hover:text-slate-800"
                      }`}
                    >
                      {tabKey === "basic" ? "Basic Settings" : tabKey}
                    </button>
                  ))}
                </div>

                {/* Language Model Selector */}
                <div className="space-y-1.5">
                  <label className="text-xs font-bold text-slate-800 block">Language Model</label>
                  <p className="text-[11px] text-slate-400">Choose an AI provider engine</p>
                  <select
                    value={selectedModel}
                    onChange={(e) => {
                      const val = e.target.value;
                      setSelectedModel(val);
                      let prov = "groq";
                      if (val.includes("GPT")) prov = "openai";
                      if (val.includes("Gemini")) prov = "gemini";
                      if (val.includes("Ollama")) prov = "ollama";
                      setGlobalProvider(prov);
                      showAlert("info", `Model provider set to ${prov.toUpperCase()}`);
                    }}
                    className="w-full bg-slate-50 border border-slate-200 rounded-xl p-2.5 text-xs text-slate-800 outline-none font-medium"
                  >
                    <option value="Groq (Llama 3.3 70B)">Groq (Llama 3.3 70B Fast / Free Tier)</option>
                    <option value="GPT 5 (Open AI)">GPT 5 (Open AI)</option>
                    <option value="Gemini 2.5 Flash">Gemini 2.5 Flash</option>
                    <option value="Ollama (Local DeepSeek)">Ollama (Local DeepSeek R1)</option>
                  </select>
                </div>

                {/* Team Task Prompt Input */}
                <div className="space-y-1.5">
                  <label className="text-xs font-bold text-slate-800 block">Describe what team should do and how work</label>
                  <p className="text-[11px] text-slate-400">This will help them connect the tasks together.</p>
                  <textarea
                    rows={4}
                    value={teamTaskPrompt}
                    onChange={(e) => setTeamTaskPrompt(e.target.value)}
                    className="w-full bg-slate-50 border border-slate-200 rounded-xl p-3 text-xs text-slate-800 outline-none resize-none"
                  />
                </div>

                <button
                  onClick={() => {
                    setQueryInput(teamTaskPrompt);
                    triggerResearch();
                  }}
                  disabled={isRunning}
                  className="w-full bg-[#111827] hover:bg-slate-800 disabled:opacity-50 text-white font-semibold font-display text-xs py-2.5 rounded-xl shadow-xs transition-all flex items-center justify-center gap-2 cursor-pointer"
                >
                  {isRunning ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                  <span>Run Team Workflow Task</span>
                </button>

                {/* Coordinator Responsibilities */}
                <div className="space-y-1.5">
                  <label className="text-xs font-bold text-slate-800 block">Set Up Team Coordinator</label>
                  <select className="w-full bg-slate-50 border border-slate-200 rounded-xl p-2.5 text-xs text-slate-800 outline-none font-medium">
                    <option>Set Up Team Coordinator</option>
                  </select>
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs font-bold text-slate-800 block">Type main team coordinator responsibility</label>
                  <textarea
                    rows={3}
                    defaultValue="The coordinator must regulate the sequence and clarity of work execution based on the list of necessary tasks. Main points must be approved only with consent."
                    className="w-full bg-slate-50 border border-slate-200 rounded-xl p-3 text-xs text-slate-800 outline-none resize-none"
                  />
                </div>
              </div>

              {/* Right Column: Set Up Workflow Sequential Chain (Matching Image 2) */}
              <div className="template-card p-6 space-y-4">
                <h3 className="text-xs font-bold font-display text-slate-800">Set Up Workflow</h3>
                <p className="text-[11px] text-slate-400">Arrange tasks and agents according to their use and execution.</p>

                <div className="space-y-3 relative">
                  {[
                    "Define the research topic, target sources, and key claims.",
                    "Execute concurrent web search queries across DuckDuckGo.",
                    "Extract raw page text and filter snippets for relevance context.",
                    "Calculate confidence scores (0-100%) and validate evidence.",
                    "Synthesize findings into executive markdown report.",
                    "Generate source citation table with verified links.",
                    "Save structured findings into ChromaDB semantic memory."
                  ].map((step, idx) => (
                    <div key={idx} className="relative flex flex-col items-center">
                      <div 
                        onClick={() => setActiveNodeIdx(idx)}
                        className={`w-full p-3 rounded-xl border text-xs leading-relaxed relative cursor-pointer transition-all ${
                          activeNodeIdx === idx 
                            ? "bg-indigo-50 border-indigo-300 text-indigo-900 shadow-sm" 
                            : "bg-slate-50 border-slate-200 text-slate-700 hover:border-slate-300"
                        }`}
                      >
                        <span className={`font-bold block mb-1 ${activeNodeIdx === idx ? "text-indigo-900" : "text-slate-900"}`}>Step {idx + 1}</span>
                        {step}
                        <button className="absolute right-2 bottom-2 w-5 h-5 rounded-full bg-slate-900 text-white flex items-center justify-center text-xs">
                          +
                        </button>
                      </div>
                      {idx < 6 && (
                        <div className="w-0.5 h-3 bg-slate-300 my-0.5" />
                      )}
                    </div>
                  ))}
                </div>
              </div>

            </div>
          )}


          {/* ════════════════════════════════════════════════════════════ */}
          {/* TAB 3: RESEARCH WORKSPACE / CHAT EXECUTION VIEW */}
          {/* ════════════════════════════════════════════════════════════ */}
          {activeTab === "workspace" && (
            <div className="max-w-6xl mx-auto space-y-6 animate-fade-in">
              
              {/* Top Controls Bar */}
              <div className="template-card p-4 flex flex-col md:flex-row items-center justify-between gap-4 bg-white">
                <div className="flex items-center gap-3 w-full md:w-auto">
                  <span className="text-2xl">🔬</span>
                  <div>
                    <h2 className="text-base font-bold font-display text-slate-900">
                      {pipelineQuery || activeProject || "Multi-Agent Research Workspace"}
                    </h2>
                    <div className="flex items-center gap-2 mt-0.5">
                      <span className="text-[10px] text-slate-400 font-mono">
                        📅 {runTimestamp || "Active Session"}
                      </span>
                      {isRunning && (
                        <span className="badge-purple text-[10px] px-2.5 py-0.5 rounded-full font-medium flex items-center gap-1">
                          <span className="w-1.5 h-1.5 rounded-full bg-indigo-600 animate-pulse" />
                          Synthesizing...
                        </span>
                      )}
                      {!isRunning && finalReport && (
                        <span className="badge-mint text-[10px] px-2 py-0.5 rounded-full font-medium">
                          Completed
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                {/* Input Bar inside Workspace */}
                <div className="flex items-center gap-2 w-full md:w-auto flex-1 max-w-xl">
                  <div className="relative flex-1">
                    <input
                      ref={chatInputRef}
                      type="text"
                      value={queryInput}
                      onChange={(e) => setQueryInput(e.target.value)}
                      placeholder="Ask any research topic or query..."
                      className="w-full bg-slate-50 border border-slate-200 rounded-xl px-4 py-2 text-xs text-slate-800 outline-none focus:border-indigo-500 transition-all pr-8"
                      onKeyDown={(e) => e.key === "Enter" && triggerResearch()}
                    />
                    {queryInput && (
                      <button
                        onClick={() => setQueryInput("")}
                        className="absolute right-2.5 top-2 text-slate-400 hover:text-slate-600 text-xs"
                      >
                        ✕
                      </button>
                    )}
                  </div>
                  <button
                    onClick={triggerResearch}
                    disabled={isRunning || !queryInput.trim()}
                    className="btn-neo-primary disabled:opacity-50 text-xs px-5 py-2 flex items-center gap-1.5 shrink-0 cursor-pointer"
                  >
                    {isRunning ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                    <span>Run</span>
                  </button>
                </div>
              </div>

              {/* Main Grid: Left Execution/Report Area + Right Details Panel */}
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                
                {/* Left 2 Columns */}
                <div className="lg:col-span-2 space-y-6">
                  
                  {/* Live Execution Timeline & Agent Progress Card */}
                  <div className="template-card p-5 bg-white space-y-4">
                    <div className="flex items-center justify-between border-b border-slate-100 pb-3">
                      <h3 className="text-xs font-bold font-display text-slate-800 flex items-center gap-2">
                        <Sparkles size={15} className="text-indigo-600" />
                        4-Agent Sequential Pipeline Progress
                      </h3>
                      {isRunning && (
                        <span className="text-[10px] font-mono text-indigo-600 flex items-center gap-1">
                          <Loader2 size={12} className="animate-spin" />
                          Live Execution Active
                        </span>
                      )}
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      {[
                        { key: "researcher", title: "Senior Researcher", icon: "🔬", color: "indigo" },
                        { key: "web_searcher", title: "Search Specialist", icon: "🔍", color: "emerald" },
                        { key: "analyst", title: "Synthesis Analyst", icon: "📊", color: "amber" },
                        { key: "summarizer", title: "Lead Report Writer", icon: "📝", color: "purple" }
                      ].map((agent) => {
                        const st = agentStates[agent.key] || { status: "pending", progress: 0, elapsed_str: "0s", error_msg: "" };
                        return (
                          <div
                            key={agent.key}
                            className={`p-3 rounded-xl border transition-all ${
                              st.status === "running"
                                ? "bg-indigo-50/70 border-indigo-300 shadow-xs"
                                : st.status === "done"
                                ? "bg-emerald-50/50 border-emerald-200"
                                : st.status === "error"
                                ? "bg-rose-50/50 border-rose-200"
                                : "bg-slate-50 border-slate-200"
                            }`}
                          >
                            <div className="flex items-center justify-between text-xs mb-1.5">
                              <div className="flex items-center gap-2">
                                <span>{agent.icon}</span>
                                <span className="font-semibold text-slate-800">{agent.title}</span>
                              </div>
                              
                              <div className="flex items-center gap-1.5">
                                {st.status === "running" && (
                                  <span className="badge-purple text-[9px] px-2 py-0.5 rounded-full font-semibold flex items-center gap-1">
                                    <span className="w-1.5 h-1.5 rounded-full bg-indigo-600 animate-ping" />
                                    Active
                                  </span>
                                )}
                                {st.status === "done" && (
                                  <span className="badge-mint text-[9px] px-2 py-0.5 rounded-full font-semibold">
                                    Done ({st.elapsed_str})
                                  </span>
                                )}
                                {st.status === "error" && (
                                  <span className="badge-rose text-[9px] px-2 py-0.5 rounded-full font-semibold">
                                    Error
                                  </span>
                                )}
                                {st.status === "pending" && (
                                  <span className="text-[10px] text-slate-400 font-mono">Idle</span>
                                )}
                              </div>
                            </div>

                            {/* Progress bar */}
                            <div className="w-full h-1.5 bg-slate-200 rounded-full overflow-hidden mt-2">
                              <div
                                className={`h-full progress-fill ${
                                  st.status === "done"
                                    ? "bg-emerald-500"
                                    : st.status === "error"
                                    ? "bg-rose-500"
                                    : "bg-indigo-600"
                                }`}
                                style={{ width: `${st.status === "done" ? 100 : st.progress}%` }}
                              />
                            </div>
                            {st.error_msg && (
                              <p className="text-[10px] text-rose-600 mt-1 truncate">{st.error_msg}</p>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>

                  {/* Real-time Activity Log Terminal */}
                  <div className="template-card p-4 bg-slate-950 text-slate-100 rounded-2xl space-y-2 font-mono">
                    <div className="flex items-center justify-between border-b border-slate-800 pb-2 text-xs">
                      <span className="flex items-center gap-2 text-slate-300 font-bold">
                        <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse" />
                        Live Execution Feed ({logs.length} events)
                      </span>
                      <button
                        onClick={() => setLogs([])}
                        className="text-[10px] text-slate-400 hover:text-white"
                      >
                        Clear
                      </button>
                    </div>

                    <div className="h-44 overflow-y-auto space-y-1.5 pr-2 text-[11px] leading-relaxed">
                      {logs.length === 0 ? (
                        <p className="text-slate-500 italic">No logs yet. Trigger a research query to start stream.</p>
                      ) : (
                        logs.map((log, idx) => (
                          <div key={idx} className="flex items-start gap-2">
                            <span className="text-slate-500 shrink-0">{log.time_str}</span>
                            <span className={`shrink-0 font-bold ${
                              log.level === "success" ? "text-emerald-400" :
                              log.level === "error" ? "text-rose-400" :
                              log.level === "warning" ? "text-amber-400" : "text-indigo-400"
                            }`}>
                              [{log.agent.toUpperCase()}]
                            </span>
                            <span className="text-slate-300 break-words">{log.message}</span>
                          </div>
                        ))
                      )}
                    </div>
                  </div>

                  {/* Executive Markdown Synthesis Report Card */}
                  {finalReport ? (
                    <div className="template-card p-6 bg-white space-y-4 border-indigo-100 shadow-sm">
                      <div className="flex items-center justify-between border-b border-slate-100 pb-3">
                        <div>
                          <h3 className="text-sm font-bold font-display text-slate-900 flex items-center gap-2">
                            <BookOpen size={16} className="text-indigo-600" />
                            Executive Synthesis Report
                          </h3>
                          {reportStats && (
                            <div className="flex items-center gap-3 text-[11px] text-slate-500 mt-1 font-mono">
                              <span>Sources: {reportStats.total_sources || sources.length}</span>
                              <span>•</span>
                              <span>Claims: {reportStats.total_claims || 0}</span>
                              <span>•</span>
                              <span>Avg Confidence: {reportStats.avg_confidence ? `${Math.round(reportStats.avg_confidence * 100)}%` : "N/A"}</span>
                              <span>•</span>
                              <span>Runtime: {reportStats.runtime_seconds ? `${reportStats.runtime_seconds.toFixed(1)}s` : "N/A"}</span>
                            </div>
                          )}
                        </div>

                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => {
                              navigator.clipboard.writeText(finalReport);
                              showAlert("success", "Markdown report copied to clipboard!");
                            }}
                            className="text-xs text-slate-600 hover:text-slate-900 border border-slate-200 px-3 py-1.5 rounded-lg flex items-center gap-1 font-medium bg-slate-50"
                          >
                            Copy
                          </button>
                          <button
                            onClick={() => {
                              const el = document.createElement("a");
                              el.href = URL.createObjectURL(new Blob([finalReport], { type: "text/markdown" }));
                              el.download = `${(pipelineQuery || "research").replace(/\s+/g, "_")}_report.md`;
                              el.click();
                            }}
                            className="text-xs text-white bg-indigo-600 hover:bg-indigo-700 px-3 py-1.5 rounded-lg flex items-center gap-1 font-semibold shadow-xs"
                          >
                            <Download size={13} />
                            Export .md
                          </button>
                        </div>
                      </div>

                      {/* Rendered Markdown Output */}
                      <div className="prose max-w-none text-xs leading-relaxed text-slate-700 bg-slate-50/50 p-4 rounded-xl border border-slate-100">
                        {parseMarkdownToReact(finalReport)}
                      </div>
                    </div>
                  ) : (
                    !isRunning && (
                      <div className="template-card p-8 text-center space-y-2 bg-white">
                        <span className="text-3xl block">🧬</span>
                        <h3 className="text-sm font-bold text-slate-800">Ready for Research Synthesis</h3>
                        <p className="text-xs text-slate-500 max-w-md mx-auto">
                          Enter your research question in the input bar above to decompose queries, crawl web resources, score relevance, and generate an executive report.
                        </p>
                      </div>
                    )
                  )}

                  {/* Verified Sources & Citations Table */}
                  {sources.length > 0 && (
                    <div className="template-card p-5 bg-white space-y-3">
                      <h3 className="text-xs font-bold font-display text-slate-800 flex items-center gap-2 border-b border-slate-100 pb-2">
                        <ShieldCheck size={16} className="text-emerald-600" />
                        Verified Citation Sources ({sources.length})
                      </h3>

                      <div className="divide-y divide-slate-100">
                        {sources.map((src) => (
                          <div key={src.id} id={`source-${src.id}`} className="py-2.5 flex items-center justify-between gap-4 text-xs">
                            <div className="flex items-center gap-2.5 min-w-0 flex-1">
                              <span className="w-5 h-5 rounded-full bg-indigo-50 text-indigo-700 flex items-center justify-center text-[10px] font-mono font-bold shrink-0">
                                [{src.id}]
                              </span>
                              <div className="min-w-0 flex-1">
                                <a
                                  href={src.url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="font-semibold text-slate-800 hover:text-indigo-600 truncate block flex items-center gap-1"
                                >
                                  <span>{src.title || src.url}</span>
                                  <ExternalLink size={11} className="text-slate-400 shrink-0" />
                                </a>
                                <span className="text-[10px] text-slate-400 font-mono truncate block">{src.url}</span>
                              </div>
                            </div>

                            <div className="flex items-center gap-3 shrink-0">
                              <div className="w-24 bg-slate-100 rounded-full h-2 overflow-hidden">
                                <div
                                  className="bg-emerald-500 h-full rounded-full"
                                  style={{ width: `${src.relevance_pct || 70}%` }}
                                />
                              </div>
                              <span className="text-[10px] font-mono font-bold text-slate-700 w-10 text-right">
                                {src.relevance_pct || 70}%
                              </span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                </div>

                {/* Right Column: Active Agents & Tools Panel */}
                <div className="space-y-4">
                  
                  {/* Team Coordinator Header */}
                  <div className="template-card p-5 bg-gradient-to-br from-indigo-50/60 to-white">
                    <div className="flex items-center gap-2.5 mb-2">
                      <div className="w-8 h-8 rounded-xl bg-indigo-600 text-white flex items-center justify-center text-sm font-bold shadow-xs">
                        🤖
                      </div>
                      <div>
                        <h4 className="text-xs font-bold font-display text-slate-900">Synapse AI Crew</h4>
                        <p className="text-[10px] text-slate-500">Autonomous 4-Agent Research Team</p>
                      </div>
                    </div>
                    <p className="text-[11px] text-slate-600 leading-relaxed mt-2">
                      Active research pipeline bound to specified provider models with semantic ChromaDB caching.
                    </p>
                  </div>

                  {/* History Runs Panel */}
                  <div className="template-card p-4 space-y-3">
                    <div className="flex items-center justify-between border-b border-slate-100 pb-2">
                      <span className="text-xs font-bold font-display text-slate-800">Past Research Runs</span>
                      <span className="text-[10px] font-mono text-slate-400">{history.length} Saved</span>
                    </div>

                    <div className="space-y-1.5 max-h-56 overflow-y-auto pr-1">
                      {history.length === 0 ? (
                        <p className="text-[11px] text-slate-400 italic">No past runs recorded.</p>
                      ) : (
                        history.map((item, idx) => (
                          <div
                            key={idx}
                            onClick={() => selectHistoryProject(idx)}
                            className={`p-2.5 rounded-xl border text-xs cursor-pointer transition-all ${
                              historyLoadedIndex === idx
                                ? "bg-indigo-50 border-indigo-200 text-indigo-900 font-semibold"
                                : "bg-slate-50 border-slate-100 text-slate-700 hover:bg-white hover:border-slate-200"
                            }`}
                          >
                            <p className="truncate text-xs font-medium">{item.query}</p>
                            <span className="text-[9px] text-slate-400 font-mono mt-0.5 block">{item.timestamp}</span>
                          </div>
                        ))
                      )}
                    </div>
                  </div>

                  {/* Active Tools Panel */}
                  <div className="template-card p-4 space-y-3">
                    <span className="text-xs font-bold font-display text-slate-800 block border-b border-slate-100 pb-2">
                      Enabled Toolkits
                    </span>
                    <div className="space-y-2">
                      {[
                        { name: "DuckDuckGo Search", desc: "Real-time web resource query crawler", icon: "🔍" },
                        { name: "Trafilatura Cleaner", desc: "Clean article text extraction engine", icon: "📄" },
                        { name: "ChromaDB Memory", desc: "Vector store semantic caching", icon: "🧠" },
                        { name: "Citation Tracker", desc: "Inline citation & claim registration", icon: "📌" }
                      ].map((tool, idx) => (
                        <div key={idx} className="p-2.5 rounded-xl bg-slate-50 border border-slate-100 text-xs space-y-0.5">
                          <div className="flex items-center justify-between">
                            <span className="font-bold text-slate-800 flex items-center gap-1.5">
                              <span>{tool.icon}</span>
                              <span>{tool.name}</span>
                            </span>
                            <span className="text-[9px] text-emerald-600 font-semibold bg-emerald-50 px-1.5 py-0.5 rounded">Active</span>
                          </div>
                          <p className="text-[10px] text-slate-500 leading-tight">{tool.desc}</p>
                        </div>
                      ))}
                    </div>
                  </div>

                </div>

              </div>

            </div>
          )}


          {/* ════════════════════════════════════════════════════════════ */}
          {/* TAB 4: SETTINGS & MODEL MANAGEMENT */}
          {/* ════════════════════════════════════════════════════════════ */}
          {activeTab === "settings" && (
            <div className="max-w-3xl mx-auto space-y-6 animate-fade-in">
              <div className="template-card p-6 space-y-5 bg-white">
                <h3 className="text-base font-bold font-display text-slate-900">API Key & Provider Configurations</h3>
                
                <div className="flex items-center justify-between border-b border-slate-100 pb-4">
                  <div>
                    <h4 className="text-xs font-bold text-slate-800">Use Global Master API Key</h4>
                    <p className="text-[11px] text-slate-500">Apply a single provider API key across all agent roles.</p>
                  </div>
                  <input
                    type="checkbox"
                    checked={useGlobalKey}
                    onChange={(e) => setUseGlobalKey(e.target.checked)}
                    className="w-4 h-4 rounded text-indigo-600 bg-slate-100 border-slate-300"
                  />
                </div>

                {useGlobalKey && (
                  <div className="grid grid-cols-2 gap-4 bg-slate-50 p-4 rounded-xl border border-slate-200">
                    <div>
                      <label className="text-xs font-semibold text-slate-700 block mb-1">Global Provider</label>
                      <select
                        value={globalProvider}
                        onChange={(e) => setGlobalProvider(e.target.value)}
                        className="w-full bg-white border border-slate-200 text-xs rounded-lg p-2 text-slate-800 outline-none"
                      >
                        <option value="groq">Groq (Free Tier / High Speed)</option>
                        <option value="gemini">Google Gemini</option>
                        <option value="openai">OpenAI</option>
                        <option value="ollama">Ollama (Local)</option>
                      </select>
                    </div>
                    <div>
                      <label className="text-xs font-semibold text-slate-700 block mb-1">Master API Key</label>
                      <input
                        type="password"
                        value={globalKey}
                        onChange={(e) => setGlobalKey(e.target.value)}
                        placeholder="gsk_... or AIza..."
                        className="w-full bg-white border border-slate-200 text-xs rounded-lg p-2 text-slate-800 outline-none"
                      />
                    </div>
                  </div>
                )}

                <div className="pt-2 space-y-3">
                  <h4 className="text-xs font-bold text-slate-800">Per-Agent Provider Keys</h4>
                  {["researcher", "web_searcher", "analyst", "summarizer"].map((agentKey) => (
                    <div key={agentKey} className="flex items-center gap-3 bg-slate-50 p-3 rounded-xl border border-slate-200">
                      <span className="text-xs font-semibold text-slate-800 capitalize w-28">{agentKey}</span>
                      <select
                        value={agentsConfig[agentKey]?.provider || "groq"}
                        onChange={(e) =>
                          setAgentsConfig({
                            ...agentsConfig,
                            [agentKey]: { ...agentsConfig[agentKey], provider: e.target.value }
                          })
                        }
                        className="bg-white border border-slate-200 text-xs text-slate-800 rounded-lg p-2 outline-none"
                      >
                        <option value="groq">Groq</option>
                        <option value="gemini">Gemini</option>
                        <option value="openai">OpenAI</option>
                        <option value="ollama">Ollama</option>
                      </select>
                      <input
                        id={`api-key-${agentKey}`}
                        type="password"
                        placeholder="Agent API Key (optional)"
                        className="flex-1 bg-white border border-slate-200 text-xs text-slate-800 rounded-lg p-2 outline-none"
                      />
                    </div>
                  ))}
                </div>

                <div className="pt-4 border-t border-slate-100 flex justify-end">
                  <button
                    onClick={saveConfig}
                    disabled={isConfigSaving}
                    className="bg-[#111827] hover:bg-slate-800 text-white font-semibold font-display text-xs px-5 py-2.5 rounded-xl shadow-xs transition-all flex items-center gap-2"
                  >
                    {isConfigSaving ? <Loader2 size={14} className="animate-spin" /> : <ShieldCheck size={14} />}
                    Save Settings
                  </button>
                </div>
              </div>

              {/* AAS Core & Agent Skills Control Plane Card */}
              <div className="template-card p-6 space-y-4 bg-white border-indigo-100">
                <div className="flex items-center justify-between border-b border-slate-100 pb-3">
                  <div>
                    <h3 className="text-base font-bold font-display text-slate-900 flex items-center gap-2">
                      <Sparkles size={18} className="text-indigo-600" />
                      AAS Skill Control Plane & Catalog (2,005+ Skills)
                    </h3>
                    <p className="text-[11px] text-slate-500 mt-0.5">
                      Local agent-first control plane for skill discovery, stack validation, and MCP tools.
                    </p>
                  </div>
                  <span className="badge-purple text-xs px-3 py-1 rounded-full font-semibold">
                    100% Validated
                  </span>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  <div className="p-3 bg-slate-50 border border-slate-200 rounded-xl space-y-1">
                    <span className="text-xs font-bold text-slate-800 flex items-center gap-1.5">
                      <span>⚡</span>
                      <span>agentic-awesome-skills</span>
                    </span>
                    <p className="text-[10px] text-slate-500 leading-tight">Catalog discovery, stack validator, and local MCP server</p>
                    <span className="text-[9px] font-mono text-emerald-600 font-bold block pt-1">Active (.agents/skills)</span>
                  </div>

                  <div className="p-3 bg-slate-50 border border-slate-200 rounded-xl space-y-1">
                    <span className="text-xs font-bold text-slate-800 flex items-center gap-1.5">
                      <span>🌐</span>
                      <span>agent-browser</span>
                    </span>
                    <p className="text-[10px] text-slate-500 leading-tight">CLI browser automation & accessibility tree ref navigation</p>
                    <span className="text-[9px] font-mono text-emerald-600 font-bold block pt-1">Active (.agents/skills)</span>
                  </div>

                  <div className="p-3 bg-slate-50 border border-slate-200 rounded-xl space-y-1">
                    <span className="text-xs font-bold text-slate-800 flex items-center gap-1.5">
                      <span>🧠</span>
                      <span>ChromaDB Vector Store</span>
                    </span>
                    <p className="text-[10px] text-slate-500 leading-tight">Semantic research memory cache & similarity search</p>
                    <span className="text-[9px] font-mono text-emerald-600 font-bold block pt-1">Active (memory/)</span>
                  </div>
                </div>

                <div className="p-3.5 bg-indigo-50/60 border border-indigo-200 rounded-xl flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2">
                    <CheckCircle size={16} className="text-indigo-600" />
                    <span className="font-semibold text-indigo-900">mcp_config.json declared for AAS Core & Agent Browser</span>
                  </div>
                  <span className="font-mono text-[10px] text-indigo-700 bg-white px-2 py-0.5 rounded border border-indigo-200">
                    Status: Connected
                  </span>
                </div>
              </div>

              {/* ════════════════════════════════════════════════════════════ */}
              {/* LANGGRAPH CONNECTION & SESSION MANAGER CARD */}
              {/* ════════════════════════════════════════════════════════════ */}
              <div className="template-card p-6 space-y-5 bg-white border-purple-100 shadow-sm">
                <div className="flex items-center justify-between border-b border-slate-100 pb-4">
                  <div className="flex items-center gap-2.5">
                    <div className="w-9 h-9 rounded-xl bg-[#8b5cf6] text-white flex items-center justify-center font-bold text-base shadow-[2px_2px_0px_#1c2331]">
                      🕸️
                    </div>
                    <div>
                      <h3 className="text-base font-bold font-display text-slate-900 flex items-center gap-2">
                        LangGraph Cloud & Local Graph Connection
                      </h3>
                      <p className="text-[11px] text-slate-500">
                        Manage persistent thread sessions, checkpoint states, and local/remote Studio connectivity.
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <span className={`text-[10px] font-mono font-bold px-2.5 py-1 rounded-full border flex items-center gap-1.5 ${
                      langgraphConfig.is_connected
                        ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                        : "bg-rose-50 text-rose-700 border-rose-200"
                    }`}>
                      <span className={`w-2 h-2 rounded-full ${langgraphConfig.is_connected ? "bg-emerald-500 animate-pulse" : "bg-rose-500"}`} />
                      {langgraphConfig.is_connected ? "Connected" : "Offline"}
                      {langgraphConfig.latency_ms && ` (${langgraphConfig.latency_ms}ms)`}
                    </span>
                  </div>
                </div>

                {/* Connection Configuration Form */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 bg-slate-50 p-4 rounded-xl border border-slate-200">
                  <div>
                    <label className="text-xs font-semibold text-slate-700 block mb-1">
                      LangGraph Server Endpoint URL
                    </label>
                    <input
                      type="text"
                      value={langgraphConfig.endpoint_url}
                      onChange={(e) => setLanggraphConfig({ ...langgraphConfig, endpoint_url: e.target.value })}
                      placeholder="http://127.0.0.1:8123"
                      className="w-full bg-white border border-slate-200 text-xs rounded-lg p-2.5 text-slate-800 outline-none font-mono"
                    />
                    <div className="flex gap-1.5 mt-1.5">
                      <button
                        onClick={() => setLanggraphConfig({ ...langgraphConfig, endpoint_url: "http://127.0.0.1:8123" })}
                        className="text-[10px] font-mono text-indigo-600 bg-indigo-50 hover:bg-indigo-100 px-2 py-0.5 rounded"
                      >
                        Local Studio (8123)
                      </button>
                      <button
                        onClick={() => setLanggraphConfig({ ...langgraphConfig, endpoint_url: "https://api.smith.langchain.com" })}
                        className="text-[10px] font-mono text-purple-600 bg-purple-50 hover:bg-purple-100 px-2 py-0.5 rounded"
                      >
                        LangGraph Cloud
                      </button>
                    </div>
                  </div>

                  <div>
                    <label className="text-xs font-semibold text-slate-700 block mb-1">
                      Graph Topology / Assistant ID
                    </label>
                    <select
                      value={langgraphConfig.assistant_id}
                      onChange={(e) => setLanggraphConfig({ ...langgraphConfig, assistant_id: e.target.value })}
                      className="w-full bg-white border border-slate-200 text-xs rounded-lg p-2.5 text-slate-800 outline-none"
                    >
                      <option value="coraxis_research_graph">Coraxis Sequential Research Graph</option>
                      <option value="multi_agent_pipeline">Parallel Multi-Agent Hub</option>
                      <option value="deep_research_v2">Deep Search StateGraph</option>
                    </select>
                    <div className="flex justify-between items-center mt-2">
                      <span className="text-[10px] text-slate-500 font-mono">Sync: {langgraphConfig.sync_mode}</span>
                      <button
                        onClick={testLangGraphConnection}
                        disabled={isTestingLangGraph}
                        className="text-xs font-semibold text-[#1c2331] bg-white hover:bg-slate-100 border border-slate-300 px-3 py-1 rounded-lg flex items-center gap-1.5 shadow-xs transition-all cursor-pointer"
                      >
                        {isTestingLangGraph ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
                        <span>Test Ping</span>
                      </button>
                    </div>
                  </div>
                </div>

                {/* Session Creation & Controls Header */}
                <div className="flex items-center justify-between pt-2 border-t border-slate-100">
                  <div>
                    <h4 className="text-xs font-bold text-slate-900 font-display flex items-center gap-1.5">
                      <Layers size={14} className="text-indigo-600" />
                      LangGraph Thread Sessions ({langgraphSessions.length})
                    </h4>
                    <p className="text-[11px] text-slate-500">
                      Active thread: <code className="bg-slate-100 px-1 py-0.5 rounded text-indigo-700 font-mono font-bold text-[10px]">{langgraphConfig.active_session_id || "None"}</code>
                    </p>
                  </div>

                  <button
                    onClick={() => setShowSessionForm(!showSessionForm)}
                    className="btn-neo-primary text-xs px-3.5 py-1.5 flex items-center gap-1.5 cursor-pointer"
                  >
                    <Plus size={13} />
                    <span>{showSessionForm ? "Hide Form" : "Create New Session"}</span>
                  </button>
                </div>

                {/* Interactive Create Session Drawer */}
                {showSessionForm && (
                  <div className="bg-gradient-to-r from-purple-50 via-indigo-50 to-slate-50 p-4 rounded-xl border-1.5 border-[#8b5cf6] space-y-3 animate-fade-in shadow-[2px_2px_0px_#1c2331]">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold text-slate-900 font-display">➕ Spawn New LangGraph Session</span>
                      <span className="text-[10px] font-mono text-purple-700 bg-white px-2 py-0.5 rounded border border-purple-200">Auto UUID Generator</span>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                      <div>
                        <label className="text-[11px] font-semibold text-slate-700 block mb-1">Session Thread Name</label>
                        <input
                          type="text"
                          value={newSessionName}
                          onChange={(e) => setNewSessionName(e.target.value)}
                          placeholder="e.g. Market Synthesis Alpha"
                          className="w-full bg-white border border-slate-300 text-xs rounded-lg p-2 text-slate-800 outline-none"
                        />
                      </div>

                      <div>
                        <label className="text-[11px] font-semibold text-slate-700 block mb-1">Graph Blueprint</label>
                        <select
                          value={newSessionGraph}
                          onChange={(e) => setNewSessionGraph(e.target.value)}
                          className="w-full bg-white border border-slate-300 text-xs rounded-lg p-2 text-slate-800 outline-none"
                        >
                          <option value="coraxis_research_graph">coraxis_research_graph</option>
                          <option value="multi_agent_pipeline">multi_agent_pipeline</option>
                          <option value="deep_research_v2">deep_research_v2</option>
                        </select>
                      </div>

                      <div>
                        <label className="text-[11px] font-semibold text-slate-700 block mb-1">State Checkpointer</label>
                        <select
                          value={newSessionCheckpointer}
                          onChange={(e) => setNewSessionCheckpointer(e.target.value)}
                          className="w-full bg-white border border-slate-300 text-xs rounded-lg p-2 text-slate-800 outline-none"
                        >
                          <option value="MemorySaver">MemorySaver (In-Memory)</option>
                          <option value="SqliteSaver">SqliteSaver (Local DB)</option>
                          <option value="PostgresSaver">PostgresSaver (Remote)</option>
                        </select>
                      </div>
                    </div>

                    <div className="flex justify-end gap-2 pt-1">
                      <button
                        onClick={() => setShowSessionForm(false)}
                        className="px-3 py-1.5 text-xs text-slate-600 hover:text-slate-800 bg-white border border-slate-300 rounded-lg cursor-pointer"
                      >
                        Cancel
                      </button>
                      <button
                        onClick={createLangGraphSession}
                        disabled={isCreatingSession}
                        className="bg-[#1c2331] hover:bg-slate-800 text-white font-semibold font-display text-xs px-4 py-1.5 rounded-lg flex items-center gap-1.5 shadow-[1.5px_1.5px_0px_#8b5cf6] cursor-pointer"
                      >
                        {isCreatingSession ? <Loader2 size={13} className="animate-spin" /> : <CheckCircle size={13} />}
                        <span>Initialize Session</span>
                      </button>
                    </div>
                  </div>
                )}

                {/* Registered Sessions List Table */}
                <div className="space-y-2 max-h-60 overflow-y-auto pr-1">
                  {langgraphSessions.length === 0 ? (
                    <div className="text-center py-6 text-xs text-slate-400 bg-slate-50 rounded-xl border border-dashed border-slate-200">
                      No active LangGraph sessions. Click "Create New Session" above to initialize a thread.
                    </div>
                  ) : (
                    langgraphSessions.map((sess) => {
                      const isActive = sess.session_id === langgraphConfig.active_session_id;
                      return (
                        <div
                          key={sess.session_id}
                          className={`p-3 rounded-xl border text-xs flex items-center justify-between gap-3 transition-all ${
                            isActive
                              ? "bg-purple-50/70 border-purple-300 shadow-xs"
                              : "bg-slate-50 border-slate-200 hover:bg-white hover:border-slate-300"
                          }`}
                        >
                          <div className="flex items-center gap-3 min-w-0 flex-1">
                            <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${isActive ? "bg-purple-600 ring-4 ring-purple-100" : "bg-slate-300"}`} />
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-2">
                                <span className="font-bold text-slate-900 truncate font-display">{sess.name}</span>
                                <span className="text-[10px] font-mono text-purple-700 bg-white px-1.5 py-0.5 rounded border border-purple-200 shrink-0">
                                  {sess.session_id}
                                </span>
                              </div>
                              <div className="flex items-center gap-2 text-[10px] text-slate-500 font-mono mt-0.5">
                                <span>Thread: {sess.thread_id.slice(0, 16)}...</span>
                                <span>•</span>
                                <span>{sess.graph_id}</span>
                                <span>•</span>
                                <span>Checkpoints: {sess.checkpoint_count}</span>
                              </div>
                            </div>
                          </div>

                          <div className="flex items-center gap-1.5 shrink-0">
                            <button
                              onClick={() => {
                                navigator.clipboard.writeText(sess.thread_id);
                                showAlert("info", `Thread ID copied: ${sess.thread_id.slice(0, 8)}...`);
                              }}
                              className="p-1.5 text-slate-500 hover:text-slate-900 rounded-md hover:bg-white border border-transparent hover:border-slate-200 cursor-pointer"
                              title="Copy Thread ID"
                            >
                              <Copy size={13} />
                            </button>

                            {!isActive ? (
                              <button
                                onClick={() => activateLangGraphSession(sess.session_id)}
                                className="px-2.5 py-1 text-[11px] font-semibold text-purple-700 bg-white hover:bg-purple-100 border border-purple-200 rounded-lg cursor-pointer transition-all"
                              >
                                Activate
                              </button>
                            ) : (
                              <span className="text-[10px] font-bold text-emerald-600 bg-emerald-50 px-2 py-1 rounded-lg border border-emerald-200">
                                Active Thread
                              </span>
                            )}

                            <button
                              onClick={() => deleteLangGraphSession(sess.session_id)}
                              className="p-1.5 text-slate-400 hover:text-rose-600 rounded-md hover:bg-rose-50 border border-transparent hover:border-rose-200 cursor-pointer"
                              title="Delete Session"
                            >
                              <Trash2 size={13} />
                            </button>
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>

            </div>
          )}

        </div>
      </div>
    </div>
  );
}
