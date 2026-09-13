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
  BookOpen
} from "lucide-react";
import HeroLanding from "./hero";

// Backend API interface types
interface AgentState {
  status: "pending" | "running" | "done" | "error";
  progress: number;
  elapsed: number;
  elapsed_str: string;
  error_msg: string;
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

interface AgentDef {
  name: string;
  builtin: boolean;
  role?: string;
  goal?: string;
  backstory?: string;
  provider: string;
  model: string;
  api_key_set?: boolean;
  temperature?: number;
  max_tokens?: number;
  base_url?: string;
  tools?: string[];
}

interface WorkflowStep {
  description: string;
  agent_name?: string;
}

interface TeamDef {
  id?: number;
  name: string;
  agent_names: string[];
  coordinator?: string | null;
  coordinator_instructions: string;
  workflow: WorkflowStep[];
}

interface ToolDef {
  id: string;
  label: string;
  needs_tracker: boolean;
}

interface CommsMessage {
  from_agent: string;
  to_agent: string;
  payload: { message: string };
  time_str: string;
  run_id: string;
}

export default function Home() {
  // Main Top Navigation Tab State: 'agents' | 'teams' | 'workspace' | 'settings'
  const [activeTab, setActiveTab] = useState<"agents" | "teams" | "workspace" | "settings">("agents");

  // Middle Form State for AI Teams Tab
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

  // Notification Toasts
  const [alert, setAlert] = useState<{ type: "success" | "error" | "info"; msg: string } | null>(null);
  const [isConfigSaving, setIsConfigSaving] = useState(false);

  // Custom Agents & Teams State
  const [allAgents, setAllAgents] = useState<AgentDef[]>([]);
  const [toolRegistry, setToolRegistry] = useState<ToolDef[]>([]);
  const [teams, setTeams] = useState<TeamDef[]>([]);
  const [selectedTeamId, setSelectedTeamId] = useState<number | null>(null);
  const [teamName, setTeamName] = useState("");
  const [teamAgents, setTeamAgents] = useState<string[]>(["researcher", "web_searcher", "analyst", "summarizer"]);
  const [coordinator, setCoordinator] = useState<string>("");
  const [coordinatorInstructions, setCoordinatorInstructions] = useState(
    "The coordinator must regulate the sequence and clarity of work execution based on the list of necessary tasks. Main points must be approved only with consent."
  );
  const [teamWorkflow, setTeamWorkflow] = useState<WorkflowStep[]>([]);
  const [showAgentModal, setShowAgentModal] = useState(false);
  const [editingAgent, setEditingAgent] = useState<AgentDef | null>(null);
  const [commsMessages, setCommsMessages] = useState<CommsMessage[]>([]);
  const [testingKeyFor, setTestingKeyFor] = useState<string>("");
  const [showHero, setShowHero] = useState(true);

  const API_URL = ""; // Relative proxy path

  const selectedTeam = teams.find((t) => t.id === selectedTeamId) || null;

  // Default workflow steps for a new team
  useEffect(() => {
    setTeamWorkflow([
      { description: "Define the research topic, target sources, and key claims.", agent_name: "researcher" },
      { description: "Execute web search queries across DuckDuckGo.", agent_name: "web_searcher" },
      { description: "Extract raw page text and filter snippets for relevance.", agent_name: "web_searcher" },
      { description: "Calculate confidence scores (0-100%) and validate evidence.", agent_name: "analyst" },
      { description: "Synthesize findings into executive markdown report.", agent_name: "summarizer" }
    ]);
  }, []);

  // Initial load
  useEffect(() => {
    fetchConfig();
    fetchHistory();
    fetchAgents();
    fetchTeams();
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
            model: agentsConfig[key].model || (document.getElementById(`model-${key}`) as HTMLInputElement)?.value || "",
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

  // ─── Custom Agents & Teams API ───

  const fetchAgents = async () => {
    try {
      const res = await fetch(`${API_URL}/api/agents`);
      if (!res.ok) return;
      const data = await res.json();
      setAllAgents(data.agents || []);
      setToolRegistry(data.tool_registry || []);
    } catch (e) {
      console.error("Agents fetch error", e);
    }
  };

  const fetchTeams = async () => {
    try {
      const res = await fetch(`${API_URL}/api/teams`);
      if (!res.ok) return;
      const data = await res.json();
      setTeams(data.teams || []);
    } catch (e) {
      console.error("Teams fetch error", e);
    }
  };

  const saveTeam = async () => {
    if (!teamName.trim()) {
      showAlert("error", "Give your team a name first.");
      return;
    }
    if (teamAgents.length === 0) {
      showAlert("error", "Add at least one agent to the team.");
      return;
    }
    try {
      const res = await fetch(`${API_URL}/api/teams`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: selectedTeam?.id,
          name: teamName,
          agent_names: teamAgents,
          coordinator: coordinator || null,
          coordinator_instructions: coordinatorInstructions,
          workflow: teamWorkflow
        })
      });
      const data = await res.json();
      if (data.status === "success") {
        showAlert("success", `Team "${teamName}" saved!`);
        setSelectedTeamId(data.team.id);
        fetchTeams();
      } else {
        showAlert("error", data.detail || "Failed to save team");
      }
    } catch (e) {
      showAlert("error", "Could not reach the backend to save the team.");
    }
  };

  const deleteTeamById = async (id: number) => {
    try {
      await fetch(`${API_URL}/api/teams/${id}`, { method: "DELETE" });
      if (selectedTeamId === id) {
        setSelectedTeamId(null);
        setTeamName("");
      }
      fetchTeams();
      showAlert("success", "Team deleted.");
    } catch (e) {
      showAlert("error", "Failed to delete team.");
    }
  };

  const loadTeamIntoEditor = (team: TeamDef) => {
    setSelectedTeamId(team.id || null);
    setTeamName(team.name);
    setTeamAgents(team.agent_names);
    setCoordinator(team.coordinator || "");
    setCoordinatorInstructions(team.coordinator_instructions || "");
    setTeamWorkflow(team.workflow.length > 0 ? team.workflow : teamWorkflow);
  };

  const runTeamWorkflow = async () => {
    if (!selectedTeam?.id) {
      showAlert("error", "Save the team first, then run it.");
      return;
    }
    if (!teamTaskPrompt.trim()) {
      showAlert("error", "Describe what the team should do first.");
      return;
    }
    try {
      const res = await fetch(`${API_URL}/api/teams/${selectedTeam.id}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: teamTaskPrompt })
      });
      const data = await res.json();
      if (data.status === "success") {
        setIsRunning(true);
        setCommsMessages([]);
        setActiveTab("workspace");
        showAlert("info", `Team "${selectedTeam.name}" workflow started!`);
        fetchHistory();
      } else {
        showAlert("error", data.detail || "Failed to start team run");
      }
    } catch (e) {
      showAlert("error", "Ensure backend server is running on port 8000.");
    }
  };

  const deleteAgentByName = async (name: string) => {
    try {
      const res = await fetch(`${API_URL}/api/agents/${name}`, { method: "DELETE" });
      const data = await res.json();
      if (data.status === "success") {
        showAlert("success", `Agent "${name}" deleted.`);
        fetchAgents();
      } else {
        showAlert("error", data.detail || "Failed to delete agent");
      }
    } catch (e) {
      showAlert("error", "Failed to delete agent.");
    }
  };

  const saveAgentDef = async (agent: AgentDef) => {
    try {
      const res = await fetch(`${API_URL}/api/agents`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(agent)
      });
      const data = await res.json();
      if (data.status === "success") {
        showAlert("success", `Agent "${agent.name}" saved!`);
        setShowAgentModal(false);
        setEditingAgent(null);
        fetchAgents();
      } else {
        showAlert("error", data.detail || "Failed to save agent");
      }
    } catch (e) {
      showAlert("error", "Could not reach the backend to save the agent.");
    }
  };

  const testAgentKey = async (agentName: string, provider: string, model: string) => {
    const key = (document.getElementById(`api-key-${agentName}`) as HTMLInputElement)?.value || "";
    setTestingKeyFor(agentName);
    try {
      const res = await fetch(`${API_URL}/api/config/test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider, api_key: key, model })
      });
      const data = await res.json();
      if (data.valid) {
        showAlert("success", `${agentName}: key works!`);
      } else {
        showAlert("error", `${agentName}: ${data.error || "key invalid"}`);
      }
    } catch (e) {
      showAlert("error", "Key test failed — backend unreachable.");
    } finally {
      setTestingKeyFor("");
    }
  };

  // ─── SSE: live agent communication feed ───
  useEffect(() => {
    const es = new EventSource(`${API_URL}/api/comms/stream`);
    es.onmessage = (ev) => {
      try {
        const event = JSON.parse(ev.data);
        if (event.type === "agent_message") {
          setCommsMessages((prev) => [
            ...prev.slice(-99),
            {
              from_agent: event.from_agent,
              to_agent: event.to_agent,
              payload: event.payload,
              time_str: event.time_str,
              run_id: event.run_id
            }
          ]);
        }
      } catch {}
    };
    es.onerror = () => {
      // Browser auto-reconnects
    };
    return () => es.close();
  }, []);

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

  if (showHero) {
    return (
      <HeroLanding
        onEnter={(tab) => {
          if (tab) setActiveTab(tab);
          setShowHero(false);
        }}
      />
    );
  }

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[#faf7f2] text-[#1c2331] font-sans">
      
      {/* ─── 1. LEFTMOST VERTICAL ICON STRIP ─── */}
      <div className="flex flex-col items-center justify-between w-14 bg-white border-r-1.5 border-[#1c2331] py-4 shrink-0 z-30 shadow-[2px_0px_0px_#1c2331]">
        <div className="flex flex-col items-center gap-4 w-full">
          {/* Brand Sigil App Logo — click opens the hero landing */}
          <button
            onClick={() => setShowHero(true)}
            className="w-10 h-10 flex items-center justify-center cursor-pointer transition-all hover:scale-115 p-0.5"
            title="About Coraxis"
          >
            <img
              src="/brand_sigil.jpg"
              alt="Brand Sigil Logo"
              className="w-full h-full object-contain mix-blend-multiply"
            />
          </button>
          
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

        <button
          onClick={() => setActiveTab("settings")}
          className="w-8 h-8 rounded-full bg-white border-1.5 border-[#1c2331] text-slate-700 flex items-center justify-center text-xs font-bold shadow-[1.5px_1.5px_0px_#1c2331]"
          title="Settings"
        >
          <User size={16} />
        </button>
      </div>


      {/* ─── 2. MAIN DASHBOARD CONTENT AREA (sidebar removed — single-surface layout) ─── */}
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

        {/* Top Bar — reference-style: brand · centered pill nav · actions */}
        <header className="flex items-center justify-between px-6 py-3 bg-white border-b-1.5 border-[#1c2331] shrink-0">
          <div className="flex items-center gap-2.5 w-56">
            <button
              onClick={() => setShowHero(true)}
              className="w-8 h-8 rounded-xl border-1.5 border-[#1c2331] bg-white flex items-center justify-center shadow-[1.5px_1.5px_0px_#1c2331] hover:scale-105 transition-all cursor-pointer"
              title="About Coraxis"
            >
              <img src="/brand_sigil.jpg" alt="Coraxis" className="w-5 h-5 object-contain mix-blend-multiply" />
            </button>
            <span className="font-display font-bold text-sm tracking-[0.14em] text-[#1c2331]">CORAXIS</span>
          </div>

          {/* Centered pill navigation */}
          <nav className="flex items-center gap-0.5 bg-[#f4f0e8] border-1.5 border-[#1c2331] rounded-full px-1.5 py-1 shadow-[2px_2px_0px_#1c2331]">
            {[
              { id: "agents", label: "Overview" },
              { id: "workspace", label: "Research" },
              { id: "teams", label: "AI Teams" },
              { id: "settings", label: "Settings" }
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as any)}
                className={`px-4 py-1.5 rounded-full text-xs font-display font-bold transition-all ${
                  activeTab === tab.id
                    ? "bg-[#1c2331] text-white shadow-[1.5px_1.5px_0px_#8b5cf6]"
                    : "text-slate-600 hover:text-[#1c2331]"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </nav>

          <div className="flex items-center gap-2 justify-end w-56">
            {isRunning && (
              <span className="badge-purple text-[10px] px-3 py-1.5 rounded-full font-semibold flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-indigo-600 animate-ping" />
                Running
              </span>
            )}
            <button
              onClick={() => setActiveTab("settings")}
              className="w-8 h-8 rounded-lg border-1.5 border-[#1c2331] flex items-center justify-center text-slate-700 hover:bg-[#faf7f2] shadow-[1.5px_1.5px_0px_#1c2331]"
              title="Settings"
            >
              <Settings size={15} />
            </button>
            <button
              onClick={handleNewProject}
              className="btn-neo-primary text-xs px-4 py-2 flex items-center gap-1.5 cursor-pointer"
            >
              <span>New Run</span>
              <Plus size={13} />
            </button>
          </div>
        </header>


        {/* ─── TAB ROUTING CONTENT ─── */}
        <div className="flex-1 overflow-y-auto p-8">

          {/* ════════════════════════════════════════════════════════════ */}
          {/* TAB 1: MY AGENTS & PROJECTS OVERVIEW (IMAGE 1) */}
          {/* ════════════════════════════════════════════════════════════ */}
          {activeTab === "agents" && (
            <div className="max-w-6xl mx-auto space-y-6 animate-fade-in">              {/* Recent Research Runs (real data) */}
              <div>
                <div className="flex items-center justify-between mb-3">
                  <span className="text-xs font-bold text-slate-700 block font-display">Recent Research Runs</span>
                  <button onClick={handleNewProject} className="text-[10px] font-semibold text-indigo-600 hover:text-indigo-800 flex items-center gap-1">
                    <Plus size={12} /> New Run
                  </button>
                </div>
                <div className="space-y-2.5">
                  {history.length === 0 ? (
                    <div className="template-card p-6 text-center bg-white">
                      <span className="text-2xl block mb-1">🔬</span>
                      <p className="text-xs font-semibold text-slate-800">No research runs yet</p>
                      <p className="text-[11px] text-slate-500 mt-1">
                        Start your first multi-agent research from the workspace input bar, or run a saved team from the AI Teams tab.
                      </p>
                      <button onClick={handleNewProject} className="btn-neo-primary text-xs px-4 py-2 mt-3 inline-flex items-center gap-1.5 cursor-pointer">
                        <span>Start a Run</span>
                        <ChevronRight size={13} />
                      </button>
                    </div>
                  ) : (
                    history.slice().reverse().map((run, revIdx) => {
                      const realIdx = history.length - 1 - revIdx;
                      const stats = run.stats || {};
                      return (
                        <div
                          key={realIdx}
                          onClick={() => selectHistoryProject(realIdx)}
                          className="template-card p-4 flex items-center justify-between hover:border-slate-300 transition-all cursor-pointer bg-white"
                        >
                          <div className="flex items-center gap-3 min-w-0">
                            <span className="text-base">🔬</span>
                            <div className="min-w-0">
                              <span className="text-sm font-semibold text-slate-800 font-display truncate block">{run.query}</span>
                              <span className="text-[10px] text-slate-400 font-mono">{run.timestamp}</span>
                            </div>
                          </div>

                          <div className="flex items-center gap-3 shrink-0">
                            {stats.total_sources != null && (
                              <span className="text-[10px] font-medium px-2.5 py-0.5 rounded-full badge-purple">{stats.total_sources} sources</span>
                            )}
                            {stats.total_claims != null && (
                              <span className="text-[10px] font-medium px-2.5 py-0.5 rounded-full badge-mint">{stats.total_claims} claims</span>
                            )}
                            <ChevronRight size={16} className="text-slate-400" />
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>

              {/* Bottom Quick-Action Cards */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6 pt-4">
                
                {/* Banner 1: Build an AI Team (wired to Teams tab) */}
                <button
                  onClick={() => setActiveTab("teams")}
                  className="template-card p-6 bg-gradient-to-br from-emerald-50 via-teal-50 to-white relative overflow-hidden flex flex-col justify-between h-[210px] text-left cursor-pointer hover:border-emerald-300 transition-all"
                >
                  <div className="z-10">
                    <div className="flex gap-2 mb-3">
                      <span className="text-[10px] font-semibold bg-white border border-slate-200 px-2.5 py-0.5 rounded-full text-slate-600 shadow-xs">
                        {teams.length} team{teams.length === 1 ? "" : "s"} saved
                      </span>
                      <span className="text-[10px] font-semibold bg-white border border-slate-200 px-2.5 py-0.5 rounded-full text-slate-600 shadow-xs">
                        {allAgents.length} agents
                      </span>
                    </div>
                    <h3 className="text-xl font-bold font-display text-slate-900 max-w-xs">
                      Combine AI Agents in a Team
                    </h3>
                    <p className="text-xs text-slate-500 mt-1">Build crews, arrange workflows, run them live →</p>
                  </div>
                  
                  {/* Decorative mesh vector background */}
                  <div className="absolute right-[-20px] bottom-[-20px] w-48 h-48 opacity-25 pointer-events-none">
                    <div className="w-full h-full rounded-full border-4 border-emerald-400/40 animate-spin" style={{ animationDuration: "20s" }} />
                  </div>
                </button>

                {/* Banner 2: Quick Research (wired to workspace) */}
                <div className="template-card p-6 bg-[#eeeffe] border-indigo-100 flex items-center justify-between h-[210px]">
                  <div className="flex gap-5 items-center">
                    <div className="w-24 h-24 rounded-2xl bg-slate-900 flex items-center justify-center text-4xl shadow-md shrink-0">
                      🔬
                    </div>
                    <div className="space-y-1">
                      <h3 className="text-lg font-bold font-display text-slate-900">
                        Start a Research Run
                      </h3>
                      <p className="text-xs text-slate-600 max-w-xs leading-relaxed">
                        Four agents decompose your question, crawl the web, score confidence, and return a cited markdown report.
                      </p>
                      <button
                        onClick={handleNewProject}
                        className="bg-[#111827] hover:bg-slate-800 text-white font-semibold font-display text-xs px-4 py-2 rounded-lg shadow-xs transition-all mt-2"
                      >
                        New Run
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

                {/* Team Selector */}
                <div className="template-card p-4">
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-xs font-bold font-display text-slate-800">AI Teams</span>
                    <span className="text-[10px] font-mono text-slate-400">{teams.length} saved</span>
                  </div>
                  <div className="space-y-1.5">
                    {teams.length === 0 ? (
                      <p className="text-[11px] text-slate-400 italic">No teams yet — build one below.</p>
                    ) : (
                      teams.map((team) => (
                        <div key={team.id} className={`flex items-center justify-between p-2 rounded-xl border text-xs transition-all ${selectedTeamId === team.id ? "bg-indigo-50 border-indigo-300" : "bg-slate-50 border-slate-200/60 hover:bg-white"}`}>
                          <button onClick={() => loadTeamIntoEditor(team)} className="flex items-center gap-2 flex-1 text-left">
                            <span>🤝</span>
                            <span className="font-semibold text-slate-800 truncate">{team.name}</span>
                            <span className="text-[9px] text-slate-400 font-mono">({team.agent_names.length})</span>
                          </button>
                          <button onClick={() => deleteTeamById(team.id!)} className="text-slate-400 hover:text-rose-500 px-1" title="Delete team">
                            🗑
                          </button>
                        </div>
                      ))
                    )}
                    <button
                      onClick={() => {
                        setSelectedTeamId(null);
                        setTeamName("");
                        setCoordinator("");
                        showAlert("info", "New team — configure and save.");
                      }}
                      className="w-full border border-dashed border-slate-300 rounded-xl py-2 text-xs font-medium text-slate-500 hover:text-slate-800 flex items-center justify-center gap-1 mt-2"
                    >
                      <span>New Team</span>
                      <Plus size={14} />
                    </button>
                  </div>
                </div>

                {/* Agents List (live from backend) */}
                <div className="template-card p-4">
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-xs font-bold font-display text-slate-800">Agents</span>
                    <span className="text-[10px] font-mono text-slate-400">{allAgents.length} total</span>
                  </div>
                  <div className="space-y-1.5">
                    {allAgents.map((agent) => (
                      <div key={agent.name} className="flex items-center justify-between p-2 rounded-xl bg-slate-50 border border-slate-200/60 hover:bg-white transition-all text-xs">
                        <div className="flex items-center gap-2 min-w-0">
                          <input
                            type="checkbox"
                            checked={teamAgents.includes(agent.name)}
                            onChange={(e) => {
                              if (e.target.checked) setTeamAgents([...teamAgents, agent.name]);
                              else setTeamAgents(teamAgents.filter((n) => n !== agent.name));
                            }}
                            className="w-3.5 h-3.5 rounded text-indigo-600"
                          />
                          <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${agent.builtin ? "bg-emerald-500" : "bg-purple-500"}`} title={agent.builtin ? "Built-in" : "Custom"} />
                          <span className="font-semibold text-slate-800 truncate">{agent.name}</span>
                          <span className="text-[9px] text-slate-400 font-mono shrink-0">{agent.provider}</span>
                        </div>
                        <div className="flex items-center gap-1 shrink-0">
                          {!agent.builtin && (
                            <button onClick={() => deleteAgentByName(agent.name)} className="text-slate-400 hover:text-rose-500 px-1" title="Delete agent">🗑</button>
                          )}
                          <button
                            onClick={() => {
                              setEditingAgent(agent);
                              setShowAgentModal(true);
                            }}
                            className="text-slate-400 hover:text-slate-700 px-1"
                            title={agent.builtin ? "View config" : "Edit agent"}
                          >
                            ⚙️
                          </button>
                        </div>
                      </div>
                    ))}
                    <button
                      onClick={() => {
                        setEditingAgent(null);
                        setShowAgentModal(true);
                      }}
                      className="w-full border border-dashed border-slate-300 rounded-xl py-2 text-xs font-medium text-slate-500 hover:text-slate-800 flex items-center justify-center gap-1 mt-2"
                    >
                      <span>Add New Agent</span>
                      <Plus size={14} />
                    </button>
                  </div>
                </div>
              </div>

              {/* Middle Form Column (Matching Image 2) */}
              <div className="template-card p-6 space-y-5">
                
                {/* Team identity header */}
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-bold font-display text-slate-900">
                    {selectedTeam ? `Editing: ${selectedTeam.name}` : "New Team"}
                  </h3>
                  {selectedTeam && (
                    <button
                      onClick={() => {
                        setSelectedTeamId(null);
                        setTeamName("");
                        setCoordinator("");
                        showAlert("info", "Creating a new team.");
                      }}
                      className="text-[10px] text-slate-500 hover:text-slate-800"
                    >
                      + New instead
                    </button>
                  )}
                </div>

                {/* Team Name */}
                <div className="space-y-1.5">
                  <label className="text-xs font-bold text-slate-800 block">Team Name</label>
                  <input
                    type="text"
                    value={teamName}
                    onChange={(e) => setTeamName(e.target.value)}
                    placeholder={selectedTeam ? selectedTeam.name : "e.g. Deep Research Crew"}
                    className="w-full bg-slate-50 border border-slate-200 rounded-xl p-2.5 text-xs text-slate-800 outline-none font-medium"
                  />
                  {selectedTeam && (
                    <p className="text-[10px] text-emerald-600 font-semibold">✓ Editing saved team #{selectedTeam.id}</p>
                  )}
                </div>

                {/* Language Model Selector */}
                <div className="space-y-1.5">
                  <label className="text-xs font-bold text-slate-800 block">Language Model</label>
                  <p className="text-[11px] text-slate-400">Applies to all agents without an explicit provider override (see Settings)</p>
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
                      setUseGlobalKey(true);
                      showAlert("info", `Global provider set to ${prov.toUpperCase()} — save in Settings to persist.`);
                    }}
                    className="w-full bg-slate-50 border border-slate-200 rounded-xl p-2.5 text-xs text-slate-800 outline-none font-medium"
                  >
                    <option value="Groq (Llama 3.3 70B)">Groq — Llama 3.3 70B (free tier)</option>
                    <option value="GPT 5 (Open AI)">OpenAI — GPT-4o Mini</option>
                    <option value="Gemini 2.5 Flash">Google — Gemini 1.5 Flash</option>
                    <option value="Ollama (Local DeepSeek)">Ollama — Llama 3.1 (local, no key)</option>
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

                <div className="grid grid-cols-2 gap-2">
                  <button
                    onClick={saveTeam}
                    className="w-full bg-white hover:bg-slate-50 text-[#1c2331] border-1.5 border-[#1c2331] font-semibold font-display text-xs py-2.5 rounded-xl shadow-[2px_2px_0px_#1c2331] transition-all flex items-center justify-center gap-2 cursor-pointer"
                  >
                    <Check size={14} />
                    <span>Save Team</span>
                  </button>
                  <button
                    onClick={runTeamWorkflow}
                    disabled={isRunning}
                    className="w-full bg-[#111827] hover:bg-slate-800 disabled:opacity-50 text-white font-semibold font-display text-xs py-2.5 rounded-xl shadow-xs transition-all flex items-center justify-center gap-2 cursor-pointer"
                  >
                    {isRunning ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                    <span>Run Team Workflow Task</span>
                  </button>
                </div>

                {/* Coordinator Responsibilities */}
                <div className="space-y-1.5">
                  <label className="text-xs font-bold text-slate-800 block">Set Up Team Coordinator</label>
                  <select
                    value={coordinator}
                    onChange={(e) => setCoordinator(e.target.value)}
                    className="w-full bg-slate-50 border border-slate-200 rounded-xl p-2.5 text-xs text-slate-800 outline-none font-medium"
                  >
                    <option value="">No coordinator (pure sequential)</option>
                    {teamAgents.map((name) => (
                      <option key={name} value={name}>{name} (final review & consolidation)</option>
                    ))}
                  </select>
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs font-bold text-slate-800 block">Type main team coordinator responsibility</label>
                  <textarea
                    rows={3}
                    value={coordinatorInstructions}
                    onChange={(e) => setCoordinatorInstructions(e.target.value)}
                    className="w-full bg-slate-50 border border-slate-200 rounded-xl p-3 text-xs text-slate-800 outline-none resize-none"
                  />
                </div>
              </div>

              {/* Right Column: Set Up Workflow Sequential Chain (Matching Image 2) */}
              <div className="template-card p-6 space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-xs font-bold font-display text-slate-800">Set Up Workflow</h3>
                    <p className="text-[11px] text-slate-400">Arrange tasks and agents according to their use and execution.</p>
                  </div>
                  <button
                    onClick={() => setTeamWorkflow([...teamWorkflow, { description: "New step — describe the task.", agent_name: teamAgents[0] || "researcher" }])}
                    className="text-[10px] font-semibold text-indigo-600 border border-indigo-200 rounded-lg px-2 py-1 hover:bg-indigo-50 flex items-center gap-1"
                  >
                    <Plus size={12} /> Add Step
                  </button>
                </div>

                <div className="space-y-3 relative">
                  {teamWorkflow.map((step, idx) => (
                    <div key={idx} className="relative flex flex-col items-center">
                      <div
                        onClick={() => setActiveNodeIdx(idx)}
                        className={`w-full p-3 rounded-xl border text-xs leading-relaxed relative transition-all ${
                          activeNodeIdx === idx
                            ? "bg-indigo-50 border-indigo-300 text-indigo-900 shadow-sm"
                            : "bg-slate-50 border-slate-200 text-slate-700 hover:border-slate-300"
                        }`}
                      >
                        <div className="flex items-center justify-between mb-1">
                          <span className={`font-bold ${activeNodeIdx === idx ? "text-indigo-900" : "text-slate-900"}`}>Step {idx + 1}</span>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setTeamWorkflow(teamWorkflow.filter((_, i) => i !== idx));
                            }}
                            className="text-slate-300 hover:text-rose-500 text-[10px]"
                            title="Remove step"
                          >
                            ✕
                          </button>
                        </div>
                        <textarea
                          rows={2}
                          value={step.description}
                          onClick={(e) => e.stopPropagation()}
                          onChange={(e) => {
                            const next = [...teamWorkflow];
                            next[idx] = { ...next[idx], description: e.target.value };
                            setTeamWorkflow(next);
                          }}
                          className="w-full bg-white/70 border border-slate-200 rounded-lg p-2 text-[11px] text-slate-700 outline-none resize-none"
                        />
                        <select
                          value={step.agent_name || ""}
                          onClick={(e) => e.stopPropagation()}
                          onChange={(e) => {
                            const next = [...teamWorkflow];
                            next[idx] = { ...next[idx], agent_name: e.target.value };
                            setTeamWorkflow(next);
                          }}
                          className="mt-1.5 w-full bg-white border border-slate-200 rounded-lg px-2 py-1 text-[10px] text-slate-700 outline-none"
                        >
                          {teamAgents.map((name) => (
                            <option key={name} value={name}>{name}</option>
                          ))}
                        </select>
                      </div>
                      {idx < teamWorkflow.length - 1 && (
                        <div className="w-0.5 h-3 bg-slate-300 my-0.5" />
                      )}
                    </div>
                  ))}
                  {teamWorkflow.length === 0 && (
                    <p className="text-[11px] text-slate-400 italic">
                      No steps — each agent will handle the goal directly in sequence.
                    </p>
                  )}
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
                      {pipelineQuery || "Multi-Agent Research Workspace"}
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

                    {/* Agent-to-Agent Message Bus Feed */}
                    {commsMessages.length > 0 && (
                      <div className="border border-indigo-900/60 rounded-xl p-2.5 space-y-1.5 bg-slate-900/60">
                        <span className="text-[10px] font-bold text-indigo-300 flex items-center gap-1.5">
                          <span className="w-1.5 h-1.5 rounded-full bg-indigo-400 animate-pulse" />
                          AGENT MESSAGE BUS ({commsMessages.length})
                        </span>
                        <div className="max-h-28 overflow-y-auto space-y-1 pr-1">
                          {commsMessages.map((msg, idx) => (
                            <div key={idx} className="text-[10px] leading-relaxed">
                              <span className="text-slate-500">{msg.time_str}</span>
                              <span className="text-indigo-400 font-bold"> [{msg.from_agent} → {msg.to_agent}]</span>
                              <span className="text-slate-300"> {msg.payload.message}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

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
                        <h4 className="text-xs font-bold font-display text-slate-900">Coraxis Research Crew</h4>
                        <p className="text-[10px] text-slate-500">Autonomous 4-Agent Pipeline</p>
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
                  {Object.keys(agentsConfig).map((agentKey) => (
                    <div key={agentKey} className="flex items-center gap-3 bg-slate-50 p-3 rounded-xl border border-slate-200">
                      <span className="text-xs font-semibold text-slate-800 capitalize w-28 flex items-center gap-1">
                        {agentKey}
                        {agentsConfig[agentKey]?.key_set && (
                          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" title="Key saved" />
                        )}
                      </span>
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
                      <input
                        id={`model-${agentKey}`}
                        type="text"
                        value={agentsConfig[agentKey]?.model || ""}
                        onChange={(e) =>
                          setAgentsConfig({
                            ...agentsConfig,
                            [agentKey]: { ...agentsConfig[agentKey], model: e.target.value }
                          })
                        }
                        placeholder="Model (default)"
                        className="w-32 bg-white border border-slate-200 text-xs text-slate-800 rounded-lg p-2 outline-none"
                      />
                      <button
                        onClick={() => testAgentKey(agentKey, agentsConfig[agentKey]?.provider || "groq", agentsConfig[agentKey]?.model || "")}
                        disabled={testingKeyFor === agentKey}
                        className="text-[10px] font-semibold text-indigo-600 border border-indigo-200 rounded-lg px-2 py-1.5 hover:bg-indigo-50 flex items-center gap-1 shrink-0"
                      >
                        {testingKeyFor === agentKey ? <Loader2 size={11} className="animate-spin" /> : <Zap size={11} />}
                        Test
                      </button>
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
                    Skills Plane
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
                    Declared
                  </span>
                </div>
              </div>

            </div>
          )}

        </div>
      </div>

      {/* ─── AGENT EDITOR MODAL ─── */}
      {showAgentModal && (
        <AgentEditorModal
          agent={editingAgent}
          toolRegistry={toolRegistry}
          onClose={() => {
            setShowAgentModal(false);
            setEditingAgent(null);
          }}
          onSave={saveAgentDef}
        />
      )}
    </div>
  );
}

// ─── Agent Editor Modal Component ───

function AgentEditorModal({
  agent,
  toolRegistry,
  onClose,
  onSave,
}: {
  agent: AgentDef | null;
  toolRegistry: ToolDef[];
  onClose: () => void;
  onSave: (agent: AgentDef) => void;
}) {
  const isNew = !agent;
  const [draft, setDraft] = useState<AgentDef>(
    agent || {
      name: "",
      builtin: false,
      role: "",
      goal: "",
      backstory: "",
      provider: "groq",
      model: "",
      temperature: 0.2,
      max_tokens: 4096,
      base_url: "",
      tools: ["duckduckgo_search"]
    }
  );

  const disabled = !isNew; // built-ins are read-only here

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div
        onClick={(e) => e.stopPropagation()}
        className="bg-white rounded-2xl border-1.5 border-[#1c2331] shadow-[4px_4px_0px_#1c2331] w-full max-w-lg max-h-[85vh] overflow-y-auto p-6 space-y-4"
      >
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-bold font-display text-slate-900">
            {isNew ? "Create New Agent" : `Agent: ${agent!.name}`}
          </h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700 text-sm">✕</button>
        </div>

        {disabled && (
          <p className="text-[10px] text-amber-600 bg-amber-50 border border-amber-200 rounded-lg p-2">
            Built-in agent — identity is fixed. Configure its provider/model/key in Settings.
          </p>
        )}

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-[10px] font-bold text-slate-700 block mb-1">Name (lowercase, no spaces)</label>
            <input
              type="text"
              value={draft.name}
              disabled={disabled}
              onChange={(e) => setDraft({ ...draft, name: e.target.value.toLowerCase().replace(/\s+/g, "_") })}
              placeholder="e.g. brand_strategist"
              className="w-full bg-slate-50 border border-slate-200 rounded-lg p-2 text-xs outline-none disabled:opacity-60"
            />
          </div>
          <div>
            <label className="text-[10px] font-bold text-slate-700 block mb-1">Provider</label>
            <select
              value={draft.provider}
              disabled={disabled}
              onChange={(e) => setDraft({ ...draft, provider: e.target.value })}
              className="w-full bg-slate-50 border border-slate-200 rounded-lg p-2 text-xs outline-none"
            >
              <option value="groq">Groq</option>
              <option value="gemini">Gemini</option>
              <option value="openai">OpenAI</option>
              <option value="ollama">Ollama</option>
            </select>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-[10px] font-bold text-slate-700 block mb-1">Model (optional)</label>
            <input
              type="text"
              value={draft.model}
              disabled={disabled}
              onChange={(e) => setDraft({ ...draft, model: e.target.value })}
              placeholder="provider default"
              className="w-full bg-slate-50 border border-slate-200 rounded-lg p-2 text-xs outline-none disabled:opacity-60"
            />
          </div>
          <div>
            <label className="text-[10px] font-bold text-slate-700 block mb-1">API Key (optional)</label>
            <input
              type="password"
              value={draft.api_key_set ? "" : ""}
              disabled={disabled}
              onChange={(e) => setDraft({ ...draft, api_key_set: undefined })}
              placeholder={draft.api_key_set ? "Key saved — leave blank to keep" : "sk-... / gsk_..."}
              className="w-full bg-slate-50 border border-slate-200 rounded-lg p-2 text-xs outline-none disabled:opacity-60"
            />
          </div>
        </div>

        <div>
          <label className="text-[10px] font-bold text-slate-700 block mb-1">Role</label>
          <input
            type="text"
            value={draft.role || ""}
            disabled={disabled}
            onChange={(e) => setDraft({ ...draft, role: e.target.value })}
            placeholder="e.g. Brand Strategy Analyst"
            className="w-full bg-slate-50 border border-slate-200 rounded-lg p-2 text-xs outline-none disabled:opacity-60"
          />
        </div>

        <div>
          <label className="text-[10px] font-bold text-slate-700 block mb-1">Goal</label>
          <textarea
            rows={2}
            value={draft.goal || ""}
            disabled={disabled}
            onChange={(e) => setDraft({ ...draft, goal: e.target.value })}
            placeholder="What this agent is trying to achieve"
            className="w-full bg-slate-50 border border-slate-200 rounded-lg p-2 text-xs outline-none resize-none disabled:opacity-60"
          />
        </div>

        <div>
          <label className="text-[10px] font-bold text-slate-700 block mb-1">Backstory</label>
          <textarea
            rows={2}
            value={draft.backstory || ""}
            disabled={disabled}
            onChange={(e) => setDraft({ ...draft, backstory: e.target.value })}
            placeholder="Persona and expertise background"
            className="w-full bg-slate-50 border border-slate-200 rounded-lg p-2 text-xs outline-none resize-none disabled:opacity-60"
          />
        </div>

        <div>
          <label className="text-[10px] font-bold text-slate-700 block mb-2">Tools</label>
          <div className="grid grid-cols-1 gap-1.5">
            {toolRegistry.map((tool) => (
              <label key={tool.id} className="flex items-center gap-2 text-xs text-slate-700 bg-slate-50 border border-slate-200 rounded-lg p-2 cursor-pointer">
                <input
                  type="checkbox"
                  disabled={disabled}
                  checked={(draft.tools || []).includes(tool.id)}
                  onChange={(e) => {
                    const tools = e.target.checked
                      ? [...(draft.tools || []), tool.id]
                      : (draft.tools || []).filter((t) => t !== tool.id);
                    setDraft({ ...draft, tools });
                  }}
                  className="w-3.5 h-3.5 rounded text-indigo-600"
                />
                <span className="font-medium">{tool.label}</span>
              </label>
            ))}
          </div>
          <p className="text-[9px] text-slate-400 mt-1">
            Every agent also gets messaging tools (send_message, read_inbox) and blackboard access automatically.
          </p>
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} className="text-xs px-4 py-2 rounded-xl border border-slate-200 text-slate-600 hover:bg-slate-50">
            Cancel
          </button>
          {!disabled && (
            <button
              onClick={() => {
                if (!draft.name.trim()) return;
                onSave(draft);
              }}
              className="text-xs px-4 py-2 rounded-xl bg-[#111827] text-white font-semibold hover:bg-slate-800 flex items-center gap-1.5"
            >
              <Check size={13} />
              Save Agent
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
