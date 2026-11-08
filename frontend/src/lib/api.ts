/**
 * Typed client for the Coraxis API.
 *
 * Every request in the app goes through here. The rules it enforces, which the
 * previous ad-hoc `fetch` calls did not:
 *
 * 1. **Errors are structured.** A non-2xx response is parsed from its RFC 7807
 *    problem document into an `ApiError`, so the UI can show the server's
 *    human-readable `detail` and branch on the stable `code`. Failures are
 *    never silent: a 401 or 500 that used to `return` early now throws.
 * 2. **Auth is automatic.** The bearer token is attached here, not at 15 call
 *    sites, so no request can forget it.
 * 3. **A 401 is retried once** after a token refresh, then surfaced. Because
 *    the retry goes through the single-flight refresh, concurrent 401s cannot
 *    trigger the refresh-token reuse detection that signs the user out.
 */

import {
  clearSession,
  getAccessToken,
  refreshAccessToken,
} from "./session";
import type {
  Agent,
  AgentCatalog,
  AgentCreate,
  AgentLLMSettings,
  Claim,
  Credential,
  CredentialTestResult,
  ModelListResult,
  Health,
  MemoryRecord,
  MemoryTopicsResponse,
  Metrics,
  Page,
  ProblemDocument,
  ProviderName,
  ProviderStatus,
  ReadyResponse,
  Run,
  RunAccepted,
  RunDetail,
  RunEvent,
  RunOptions,
  RunStatus,
  Session,
  Team,
  TeamInput,
  TokenPair,
  User,
} from "./types";

/** All routes live under this prefix. */
export const API_BASE = "/api/v1";

/** Requests are abandoned after this long so the UI cannot hang forever. */
const DEFAULT_TIMEOUT_MS = 30_000;

/** Research runs can take minutes; polling and streaming need a longer leash. */
const LONG_TIMEOUT_MS = 120_000;

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly problem: ProblemDocument | null;
  /** Seconds to wait before retrying, when the server supplied a hint. */
  readonly retryAfter: number | null;

  constructor(message: string, status: number, code: string, problem: ProblemDocument | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.problem = problem;
    this.retryAfter =
      typeof problem?.retry_after === "number" ? problem.retry_after : null;
  }

  /** True when retrying the same request later could plausibly succeed. */
  get isRetryable(): boolean {
    return this.status === 429 || this.status >= 500;
  }
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null>;
  timeoutMs?: number;
  /** Set for the auth endpoints, which must not attempt a token refresh. */
  skipAuthRetry?: boolean;
  signal?: AbortSignal;
}

function buildUrl(
  path: string,
  query?: RequestOptions["query"],
): string {
  const url = `${API_BASE}${path}`;
  if (!query) return url;

  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") {
      params.set(key, String(value));
    }
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

async function parseProblem(response: Response): Promise<ProblemDocument | null> {
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("json")) return null;
  try {
    return (await response.json()) as ProblemDocument;
  } catch {
    return null;
  }
}

function fallbackMessage(response: Response): string {
  if (response.status === 401) return "Your session has expired. Sign in again.";
  if (response.status === 403) return "You do not have access to that.";
  if (response.status === 404) return "That item no longer exists.";
  if (response.status === 429) return "Too many requests. Wait a moment and retry.";
  if (response.status >= 500) return "The server hit an unexpected error.";
  return `Request failed (${response.status}).`;
}

/**
 * Perform one request, with no auth-retry logic. Throws `ApiError` on failure.
 */
async function rawRequest<T>(path: string, options: RequestOptions): Promise<T> {
  const { method = "GET", body, query, timeoutMs = DEFAULT_TIMEOUT_MS, signal } = options;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  // Honour a caller-supplied signal as well as our timeout.
  const onAbort = () => controller.abort();
  signal?.addEventListener("abort", onAbort);

  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const token = await getAccessToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  let response: Response;
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
      cache: "no-store",
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError(
        "The request timed out. The server may still be working.",
        0,
        "timeout",
        null,
      );
    }
    throw new ApiError(
      "Cannot reach the Coraxis API. Check that the backend is running.",
      0,
      "network_error",
      null,
    );
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  }

  if (!response.ok) {
    const problem = await parseProblem(response);
    throw new ApiError(
      problem?.detail || problem?.title || fallbackMessage(response),
      response.status,
      problem?.code || `http_${response.status}`,
      problem,
    );
  }

  // 204 and other empty responses (report download uses text).
  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("json")) {
    return (await response.text()) as unknown as T;
  }
  return (await response.json()) as T;
}

/**
 * Perform a request, refreshing the access token once on a 401.
 *
 * The single retry is deliberate: a second 401 after a successful refresh means
 * the session is genuinely gone, and looping would only multiply the load.
 */
async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  try {
    return await rawRequest<T>(path, options);
  } catch (error) {
    if (
      error instanceof ApiError &&
      error.status === 401 &&
      !options.skipAuthRetry
    ) {
      const refreshed = await refreshAccessToken(API_BASE);
      if (refreshed) {
        return rawRequest<T>(path, options);
      }
      // Refresh failed: the session is over. Clear it so the UI shows the
      // sign-in screen instead of retrying against a dead token.
      clearSession();
    }
    throw error;
  }
}

// ─── Auth ────────────────────────────────────────────────────────────

export const authApi = {
  register: (payload: { email: string; password: string; display_name?: string }) =>
    request<TokenPair>("/auth/register", {
      method: "POST",
      body: payload,
      skipAuthRetry: true,
    }),

  login: (payload: { email: string; password: string }) =>
    request<TokenPair>("/auth/login", {
      method: "POST",
      body: payload,
      skipAuthRetry: true,
    }),

  logout: (payload: { refresh_token?: string; all_sessions?: boolean } = {}) =>
    request<{ deleted: boolean; id: string }>("/auth/logout", {
      method: "POST",
      body: payload,
      skipAuthRetry: true,
    }),

  me: () => request<User>("/auth/me"),

  sessions: () => request<Session[]>("/auth/sessions"),

  verify: () => request<void>("/auth/verify"),
};

// ─── Credentials ─────────────────────────────────────────────────────

export const credentialsApi = {
  list: () => request<Credential[]>("/credentials"),

  providers: () => request<ProviderStatus[]>("/credentials/providers"),

  /**
   * Store or replace a key. Omit `api_key` to change only the model or base URL
   * — the server preserves the stored secret, so the browser never has to hold
   * it after the first save.
   */
  save: (payload: {
    provider: ProviderName;
    api_key?: string;
    base_url?: string;
    default_model?: string;
  }) => request<Credential>("/credentials", { method: "PUT", body: payload }),

  remove: (provider: ProviderName) =>
    request<{ deleted: boolean; id: string }>(`/credentials/${provider}`, {
      method: "DELETE",
    }),

  /** Validate a key without storing it. */
  test: (payload: {
    provider: ProviderName;
    api_key?: string;
    model?: string;
    base_url?: string;
  }) =>
    request<CredentialTestResult>("/credentials/test", {
      method: "POST",
      body: payload,
      timeoutMs: LONG_TIMEOUT_MS,
      skipAuthRetry: true,
    }),

  /**
   * Ask the provider what models it currently serves.
   *
   * Providers retire model ids constantly, so a hardcoded list goes stale
   * silently. Omit `api_key` to reuse the stored one — the browser does not
   * need to hold the secret to refresh the catalogue.
   */
  models: (payload: { provider: ProviderName; api_key?: string; base_url?: string }) =>
    request<ModelListResult>("/credentials/models", {
      method: "POST",
      body: payload,
      timeoutMs: LONG_TIMEOUT_MS,
    }),

  validateStored: (provider: ProviderName) =>
    request<Credential>(`/credentials/${provider}/validate`, {
      method: "POST",
      timeoutMs: LONG_TIMEOUT_MS,
    }),
};

// ─── Agents ──────────────────────────────────────────────────────────

export const agentsApi = {
  catalog: () => request<AgentCatalog>("/agents"),

  get: (slug: string) => request<Agent>(`/agents/${slug}`),

  defaults: (slug: string) => request<AgentLLMSettings>(`/agents/${slug}/defaults`),

  create: (payload: AgentCreate) =>
    request<Agent>("/agents", { method: "POST", body: payload }),

  update: (slug: string, payload: Partial<AgentCreate>) =>
    request<Agent>(`/agents/${slug}`, { method: "PATCH", body: payload }),

  setLLM: (slug: string, payload: Partial<AgentLLMSettings>) =>
    request<Agent>(`/agents/${slug}/llm`, { method: "PUT", body: payload }),

  remove: (slug: string) =>
    request<{ deleted: boolean; id: string }>(`/agents/${slug}`, { method: "DELETE" }),
};

// ─── Teams ───────────────────────────────────────────────────────────

export const teamsApi = {
  list: () => request<Team[]>("/teams"),

  get: (id: string) => request<Team>(`/teams/${id}`),

  create: (payload: TeamInput) => request<Team>("/teams", { method: "POST", body: payload }),

  update: (id: string, payload: Partial<TeamInput>) =>
    request<Team>(`/teams/${id}`, { method: "PATCH", body: payload }),

  remove: (id: string) =>
    request<{ deleted: boolean; id: string }>(`/teams/${id}`, { method: "DELETE" }),
};

// ─── Runs ────────────────────────────────────────────────────────────

export const runsApi = {
  submit: (payload: { query: string; team_id?: string | null; options?: RunOptions }) =>
    request<RunAccepted>("/runs", { method: "POST", body: payload }),

  list: (params: { status?: RunStatus; team_id?: string; limit?: number; offset?: number } = {}) =>
    request<Page<Run>>("/runs", { query: params }),

  get: (id: string) => request<RunDetail>(`/runs/${id}`),

  events: (id: string, since = 0) =>
    request<RunEvent[]>(`/runs/${id}/events`, { query: { since } }),

  cancel: (id: string) => request<Run>(`/runs/${id}/cancel`, { method: "POST" }),

  retry: (id: string) => request<RunAccepted>(`/runs/${id}/retry`, { method: "POST" }),

  remove: (id: string) =>
    request<{ deleted: boolean; id: string }>(`/runs/${id}`, { method: "DELETE" }),

  reportMarkdown: (id: string) =>
    request<string>(`/runs/${id}/report.md`, { timeoutMs: LONG_TIMEOUT_MS }),

  /**
   * Path for the SSE endpoint.
   *
   * Deliberately returns a path, not a ready-made `EventSource` URL. The stream
   * needs an `Authorization` header, which `EventSource` cannot send, and the
   * usual workaround — putting the token in the query string — writes it into
   * every access log and proxy trace along the way. The stream is consumed with
   * `fetch` instead; see `hooks/useRunStream.ts`.
   */
  streamPath: (id: string) => `${API_BASE}/runs/${id}/stream`,
};

// ─── Memory ──────────────────────────────────────────────────────────

export const memoryApi = {
  topics: () => request<MemoryTopicsResponse>("/memory/topics"),

  records: (params: { topic?: string; limit?: number; offset?: number } = {}) =>
    request<Page<MemoryRecord>>("/memory/records", { query: params }),

  forgetTopic: (topic: string) =>
    request<{ deleted: boolean; id: string }>(
      `/memory/topics/${encodeURIComponent(topic)}`,
      { method: "DELETE" },
    ),
};

// ─── System ──────────────────────────────────────────────────────────

export const systemApi = {
  health: () => request<Health>("/health"),
  ready: () => request<ReadyResponse>("/ready"),
  metrics: () => request<Metrics>("/metrics"),
  version: () =>
    request<{ version: string; environment: string; api_version: string }>("/version"),
};

export const api = {
  auth: authApi,
  credentials: credentialsApi,
  agents: agentsApi,
  teams: teamsApi,
  runs: runsApi,
  memory: memoryApi,
  system: systemApi,
};

/**
 * Headers for a raw `fetch` outside the client — currently only the SSE
 * stream, which needs to read the response body incrementally.
 */
export function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const token = getAccessToken();
  return {
    Accept: "text/event-stream",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...extra,
  };
}

export type { Claim, RunDetail };
