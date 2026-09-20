/**
 * Types mirroring the Coraxis API.
 *
 * These are transcribed from the OpenAPI document the backend serves at
 * `/openapi.json`, not hand-invented, so a field rename on the server surfaces
 * here as a compile error rather than as `undefined` in the browser. Optional
 * fields (`?`) match the server's optional properties exactly.
 */

// ─── Errors ──────────────────────────────────────────────────────────

/**
 * The RFC 7807 problem document every non-2xx response carries.
 *
 * `detail` is written for a human and is safe to show verbatim. `code` is the
 * stable machine-readable discriminator; branch on it, never on `detail`.
 */
export interface ProblemDocument {
  type: string;
  title: string;
  status: number;
  detail: string;
  code: string;
  instance?: string;
  request_id?: string;
  /** Present on 429s. Seconds the client should wait before retrying. */
  retry_after?: number;
  /** Present on 422s: one entry per invalid field. */
  errors?: Array<{ field?: string; message: string }>;
  [key: string]: unknown;
}

// ─── Enums ───────────────────────────────────────────────────────────

export type RunStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "timed_out";

export type RunTrigger = "pipeline" | "team" | "retry" | "scheduled";

export type EventLevel = "debug" | "info" | "warning" | "error" | "success";

/**
 * Must match `ProviderName` in the backend's `db/enums.py`.
 *
 * `custom` is any OpenAI-compatible endpoint the user supplies a base URL for.
 * `anthropic` used to be listed here and was never supported by the server, so
 * selecting it produced a validation error rather than a provider.
 */
export type ProviderName = "groq" | "gemini" | "openai" | "ollama" | "custom";

export const TERMINAL_STATUSES: readonly RunStatus[] = [
  "succeeded",
  "failed",
  "cancelled",
  "timed_out",
] as const;

export function isTerminal(status: RunStatus): boolean {
  return TERMINAL_STATUSES.includes(status);
}

// ─── Auth ────────────────────────────────────────────────────────────

export interface User {
  id: string;
  email: string;
  display_name: string;
  is_active: boolean;
  is_superuser: boolean;
  created_at: string;
  last_login_at?: string | null;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_at: string;
  expires_in: number;
  user: User;
}

export interface Session {
  id: string;
  created_at: string;
  expires_at: string;
  revoked_at?: string | null;
  user_agent: string;
  client_ip: string;
  is_current: boolean;
}

// ─── Credentials ─────────────────────────────────────────────────────

/**
 * A stored credential. Note what is *absent*: there is no field capable of
 * carrying the key. The server never sends one back, and `key_hint` is the
 * last four characters.
 */
export interface Credential {
  id: string;
  provider: ProviderName;
  key_hint: string;
  base_url: string;
  /** The model the user pinned for this provider. Empty means "use the default". */
  default_model: string;
  is_active: boolean;
  has_key: boolean;
  last_validated_at?: string | null;
  last_validation_error: string;
  created_at: string;
  updated_at: string;
}

export interface ProviderStatus {
  provider: ProviderName;
  configured: boolean;
  /** Where the active key came from. `none` means the user must add one. */
  source: "user" | "environment" | "none";
  key_hint: string;
  default_model: string;
  requires_key: boolean;
  /** A user-supplied base URL is mandatory — true for `custom`. */
  requires_base_url: boolean;
  /** The user's pinned model, if any. Empty means `default_model` applies. */
  selected_model: string;
}

export interface CredentialTestResult {
  valid: boolean;
  provider: ProviderName;
  model: string;
  error: string;
  latency_ms: number;
}

/** The provider's live model catalogue, as returned by `POST /credentials/models`. */
export interface ModelListResult {
  models: string[];
  error: string;
  /** False when the ids are a fallback rather than what the provider reported. */
  live: boolean;
}

// ─── Agents ──────────────────────────────────────────────────────────

export interface AgentLLMSettings {
  provider: ProviderName;
  model: string;
  temperature: number;
  max_tokens: number;
  base_url: string;
}

export interface Agent {
  id: string;
  slug: string;
  name: string;
  role: string;
  goal: string;
  backstory: string;
  kind: string;
  tools: string[];
  position: number;
  is_builtin: boolean;
  llm: AgentLLMSettings;
  created_at: string;
  updated_at: string;
}

export interface Tool {
  id: string;
  label: string;
  description: string;
  requires_tracker: boolean;
}

export interface AgentCatalog {
  agents: Agent[];
  tools: Tool[];
}

export interface AgentCreate {
  slug: string;
  name: string;
  role?: string;
  goal?: string;
  backstory?: string;
  tools?: string[];
  llm?: Partial<AgentLLMSettings>;
}

// ─── Teams ───────────────────────────────────────────────────────────

export interface TeamStep {
  position: number;
  agent_slug: string;
  description: string;
  expected_output: string;
}

export interface TeamStepInput {
  agent_slug: string;
  description: string;
  expected_output?: string;
}

export interface Team {
  id: string;
  name: string;
  description: string;
  agent_slugs: string[];
  coordinator_slug?: string | null;
  coordinator_instructions: string;
  steps: TeamStep[];
  created_at: string;
  updated_at: string;
}

export interface TeamInput {
  name: string;
  description?: string;
  agent_slugs: string[];
  coordinator_slug?: string | null;
  coordinator_instructions?: string;
  steps?: TeamStepInput[];
}

// ─── Runs ────────────────────────────────────────────────────────────

export interface RunStats {
  total_sources: number;
  total_claims: number;
  avg_confidence: number;
  avg_relevance: number;
  agents_used: string[];
  models_used: Record<string, string>;
  runtime_seconds: number;
}

export interface RunOptions {
  max_sources?: number;
  max_fetch_per_query?: number;
  include_memory?: boolean;
  min_confidence?: number;
}

export interface Run {
  id: string;
  query: string;
  status: RunStatus;
  trigger: RunTrigger;
  team_id?: string | null;
  error: string;
  options: RunOptions;
  stats: RunStats;
  executive_summary: string;
  key_findings: string[];
  source_count: number;
  claim_count: number;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  runtime_seconds: number;
}

export interface Source {
  id: string;
  url: string;
  title: string;
  relevance: number;
  relevance_pct: number;
  snippet: string;
  word_count: number;
  fetch_success: boolean;
}

export interface Claim {
  id: string;
  claim_ref: string;
  text: string;
  confidence: number;
  relevance: number;
  agent: string;
  source_urls: string[];
}

export interface RunDetail extends Run {
  report_markdown: string;
  citations_markdown: string;
  sources: Source[];
  claims: Claim[];
}

export interface RunAccepted {
  run_id: string;
  status: RunStatus;
  stream_url: string;
  detail_url: string;
}

/** One entry in a run's timeline. `seq` is the resume cursor. */
export interface RunEvent {
  id: string;
  seq: number;
  type: string;
  agent: string;
  level: EventLevel;
  message: string;
  payload: Record<string, unknown>;
  created_at: string;
}

// ─── Memory ──────────────────────────────────────────────────────────

export interface MemoryTopic {
  topic: string;
  entries: number;
  last_updated?: string | null;
}

export interface MemoryTopicsResponse {
  topics: MemoryTopic[];
  total_entries: number;
  enabled: boolean;
}

export interface MemoryRecord {
  id: string;
  topic: string;
  claim: string;
  sources: string[];
  confidence: number;
  relevance: number;
  agent: string;
  created_at: string;
}

// ─── System ──────────────────────────────────────────────────────────

export interface Health {
  status: string;
  version: string;
  environment: string;
  uptime_seconds: number;
}

export interface ReadyCheck {
  name: string;
  ok: boolean;
  detail: string;
}

export interface ReadyResponse {
  ready: boolean;
  checks: ReadyCheck[];
}

export interface Metrics {
  total_runs: number;
  runs_by_status: Record<string, number>;
  total_sources_analyzed: number;
  total_claims_synthesized: number;
  avg_confidence: number;
  avg_relevance: number;
  total_runtime_seconds: number;
}

// ─── Pagination ──────────────────────────────────────────────────────

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}
