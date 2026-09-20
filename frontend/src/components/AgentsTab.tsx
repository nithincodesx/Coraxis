"use client";

/**
 * The agent roster and the tool registry.
 *
 * Presented as an indexed editorial list rather than a card grid: each agent
 * is a row separated by a hairline, with its identity given room and its
 * technical metadata set in mono. Built-ins cannot be edited in place — the
 * server rejects it and says to clone — so the UI mirrors that, offering
 * "Duplicate" for structural changes and per-agent model settings.
 */

import { useMemo, useState } from "react";
import { Bot, Copy, Loader2, Sliders, Trash2 } from "lucide-react";

import {
  Button,
  Chip,
  EmptyState,
  Field,
  IconButton,
  Index,
  Input,
  PageHeader,
  Rule,
  Section,
  Select,
  StatusDot,
} from "./ui";
import { ApiError, api } from "../lib/api";
import { useAsyncData } from "../hooks/useAsyncData";
import type { Agent, AgentCatalog, AgentLLMSettings, ProviderName } from "../lib/types";

interface Props {
  onError: (message: string) => void;
  onSuccess: (message: string) => void;
  onChanged: () => void;
}

// Must match the backend's ProviderName. `anthropic` was listed here and never
// supported by the server, so picking it produced a validation error.
const PROVIDERS: ProviderName[] = ["groq", "gemini", "openai", "ollama", "custom"];

export default function AgentsTab({ onError, onSuccess, onChanged }: Props) {
  const catalog = useAsyncData<AgentCatalog>(() => api.agents.catalog());
  const [editing, setEditing] = useState<Agent | null>(null);
  const [busy, setBusy] = useState(false);

  const agents = catalog.data?.agents ?? [];
  const tools = catalog.data?.tools ?? [];

  const ordered = useMemo(() => {
    const list = catalog.data?.agents ?? [];
    return [...list].sort((a, b) => {
      if (a.is_builtin !== b.is_builtin) return a.is_builtin ? -1 : 1;
      return a.position - b.position;
    });
  }, [catalog.data]);

  const saveLLM = async (slug: string, settings: Partial<AgentLLMSettings>) => {
    setBusy(true);
    try {
      await api.agents.setLLM(slug, settings);
      onSuccess("Model settings saved.");
      setEditing(null);
      await catalog.refetch();
      onChanged();
    } catch (caught) {
      onError(caught instanceof ApiError ? caught.message : "Could not save the settings.");
    } finally {
      setBusy(false);
    }
  };

  /**
   * Derive a free slug rather than appending a random suffix. Predictable names
   * (`researcher-copy-1`) are easier to work with, and generating a random
   * value during render is not pure.
   */
  const freeSlugFor = (agent: Agent): string => {
    const taken = new Set(agents.map((item) => item.slug));
    let suffix = 1;
    while (taken.has(`${agent.slug}-copy-${suffix}`)) suffix += 1;
    return `${agent.slug}-copy-${suffix}`;
  };

  const duplicate = async (agent: Agent) => {
    const slug = freeSlugFor(agent);
    setBusy(true);
    try {
      await api.agents.create({
        slug,
        name: `${agent.name} (copy)`,
        role: agent.role,
        goal: agent.goal,
        backstory: agent.backstory,
        tools: agent.tools,
        llm: agent.llm,
      });
      onSuccess(`Created "${slug}".`);
      await catalog.refetch();
      onChanged();
    } catch (caught) {
      onError(caught instanceof ApiError ? caught.message : "Could not duplicate the agent.");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (agent: Agent) => {
    setBusy(true);
    try {
      await api.agents.remove(agent.slug);
      onSuccess(`Removed "${agent.name}".`);
      await catalog.refetch();
      onChanged();
    } catch (caught) {
      onError(caught instanceof ApiError ? caught.message : "Could not remove the agent.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fade-in">
      <PageHeader
        label="Research System"
        title="Agent Roster"
        description="The specialists that make up a research run. Each carries its own role, tools and model."
        actions={
          <span className="t-meta">
            {ordered.filter((a) => a.is_builtin).length} built-in ·{" "}
            {ordered.filter((a) => !a.is_builtin).length} custom
          </span>
        }
      />

      {catalog.isInitialLoading ? (
        <div className="flex items-center justify-center gap-2 py-20">
          <Loader2 size={15} className="animate-spin" style={{ color: "var(--text-faint)" }} />
          <span className="t-meta">Loading roster…</span>
        </div>
      ) : catalog.error ? (
        <EmptyState
          title="Could not load the roster"
          body={catalog.error}
          action={<Button onClick={() => void catalog.refetch()}>Retry</Button>}
        />
      ) : (
        <div className="fade-in-stagger">
          {ordered.map((agent, i) => (
            <article key={agent.id}>
              <div className="group flex items-start gap-5 py-5 transition-colors sm:gap-7">
                {/* Index + identity */}
                <div className="flex w-8 shrink-0 justify-end pt-1">
                  <Index n={i + 1} />
                </div>

                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                    <h2 className="t-h1" style={{ fontSize: "1.0625rem" }}>
                      {agent.name}
                    </h2>
                    {agent.is_builtin ? (
                      <Chip>built-in</Chip>
                    ) : (
                      <Chip tone="info">custom</Chip>
                    )}
                  </div>

                  <p
                    className="t-body mt-1.5"
                    style={{ fontSize: "0.8125rem", color: "var(--text-secondary)" }}
                  >
                    {agent.role}
                  </p>

                  {/* Technical metadata */}
                  <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5">
                    <span className="t-meta">{agent.slug}</span>
                    <span className="t-meta" style={{ color: "var(--text-faint)" }}>
                      {agent.llm.provider}
                      {agent.llm.model ? `/${agent.llm.model}` : "/default"}
                    </span>
                    <span className="t-meta" style={{ color: "var(--text-faint)" }}>
                      {agent.tools.length} tools
                    </span>
                  </div>
                </div>

                {/* Actions — quiet until hover, always reachable by keyboard */}
                <div className="flex shrink-0 items-center gap-1 opacity-60 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                  <Button
                    size="sm"
                    variant="ghost"
                    icon={<Sliders size={12} />}
                    onClick={() => setEditing(agent)}
                    disabled={busy}
                  >
                    Model
                  </Button>
                  <IconButton
                    label={`Duplicate ${agent.name}`}
                    icon={<Copy size={12} />}
                    onClick={() => void duplicate(agent)}
                    disabled={busy}
                  />
                  {!agent.is_builtin && (
                    <IconButton
                      label={`Delete ${agent.name}`}
                      icon={<Trash2 size={12} />}
                      onClick={() => void remove(agent)}
                      disabled={busy}
                      style={{ color: "var(--danger)" }}
                    />
                  )}
                </div>
              </div>
              <Rule />
            </article>
          ))}
        </div>
      )}

      {/* ── Tools ─────────────────────────────────────────────────────── */}
      {tools.length > 0 && (
        <Section
          label="Capabilities"
          title="Available Tools"
          className="mt-14"
          actions={<span className="t-meta">{tools.length}</span>}
        >
          <div className="fade-in-stagger grid grid-cols-1 gap-x-10 sm:grid-cols-2">
            {tools.map((tool, i) => (
              <div key={tool.id} className="group py-3.5">
                <div className="flex items-baseline justify-between gap-3">
                  <h3 className="t-h3">{tool.label}</h3>
                  <span className="t-index shrink-0">{String(i + 1).padStart(2, "0")}</span>
                </div>
                <p
                  className="t-body mt-1"
                  style={{ fontSize: "0.75rem", color: "var(--text-muted)", lineHeight: 1.65 }}
                >
                  {tool.description}
                </p>
                <div className="mt-2 flex items-center gap-3">
                  <span className="t-meta" style={{ color: "var(--text-faint)" }}>
                    {tool.id}
                  </span>
                  {tool.requires_tracker && (
                    <span className="flex items-center gap-1.5">
                      <StatusDot />
                      <span className="t-meta" style={{ color: "var(--text-faint)" }}>
                        cites sources
                      </span>
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </Section>
      )}

      {editing && (
        <LLMEditor
          agent={editing}
          busy={busy}
          onClose={() => setEditing(null)}
          onSave={(settings) => saveLLM(editing.slug, settings)}
        />
      )}
    </div>
  );
}

/* ── Model editor ──────────────────────────────────────────────────── */

function LLMEditor({
  agent,
  busy,
  onClose,
  onSave,
}: {
  agent: Agent;
  busy: boolean;
  onClose: () => void;
  onSave: (settings: Partial<AgentLLMSettings>) => void;
}) {
  const [provider, setProvider] = useState<ProviderName>(agent.llm.provider);
  const [model, setModel] = useState(agent.llm.model);
  const [temperature, setTemperature] = useState(agent.llm.temperature);
  const [maxTokens, setMaxTokens] = useState(agent.llm.max_tokens);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "color-mix(in srgb, var(--bg) 72%, transparent)" }}
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Model settings for ${agent.name}`}
        className="panel w-full max-w-md p-6 fade-in"
        style={{ background: "var(--surface-raised)", boxShadow: "var(--shadow-lg)" }}
        onClick={(event) => event.stopPropagation()}
      >
        <p className="t-label">Model</p>
        <h3 className="t-h1 mt-1.5" style={{ fontSize: "1.125rem" }}>
          {agent.name}
        </h3>
        <p className="t-meta mt-1.5">
          Which provider and model this agent uses. Keys are configured in Settings.
        </p>

        <Rule className="my-5" />

        <div className="flex flex-col gap-4">
          <Field label="Provider" htmlFor="provider">
            <Select
              id="provider"
              value={provider}
              onChange={(event) => setProvider(event.target.value as ProviderName)}
            >
              {PROVIDERS.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </Select>
          </Field>

          <Field label="Model" htmlFor="model" hint="Leave empty for the provider default.">
            <Input
              id="model"
              mono
              value={model}
              onChange={(event) => setModel(event.target.value)}
            />
          </Field>

          <div className="grid grid-cols-2 gap-4">
            <Field label="Temperature" htmlFor="temperature">
              <Input
                id="temperature"
                mono
                type="number"
                step="0.1"
                min="0"
                max="2"
                value={temperature}
                onChange={(event) => setTemperature(Number(event.target.value))}
              />
            </Field>
            <Field label="Max tokens" htmlFor="max_tokens">
              <Input
                id="max_tokens"
                mono
                type="number"
                min="256"
                step="256"
                value={maxTokens}
                onChange={(event) => setMaxTokens(Number(event.target.value))}
              />
            </Field>
          </div>
        </div>

        <div className="mt-6 flex items-center justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            disabled={busy}
            onClick={() => onSave({ provider, model, temperature, max_tokens: maxTokens })}
            icon={busy ? <Loader2 size={13} className="animate-spin" /> : <Bot size={13} />}
          >
            Save
          </Button>
        </div>
      </div>
    </div>
  );
}
