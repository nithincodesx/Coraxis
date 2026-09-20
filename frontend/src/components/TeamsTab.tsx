"use client";

/**
 * Team composition.
 *
 * Structured as a configuration document — Team, Members, Workflow — rather
 * than a form of labelled inputs. A team is an ordered list of agents plus an
 * optional coordinator and an explicit step list; the server validates that
 * every referenced slug exists and that the coordinator is itself a member, so
 * the form does the same up front and reports the problem before a failed save.
 *
 * The editor is a separate component keyed by team id, which lets it seed its
 * state from props directly. The alternative — watching the selected team in
 * an effect and copying it into state — costs an extra render per selection
 * and can lose edits mid-flight.
 */

import { useState } from "react";
import { Loader2, Plus, Save, Trash2, Users } from "lucide-react";

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
  Textarea,
} from "./ui";
import { ApiError, api } from "../lib/api";
import { useAsyncData } from "../hooks/useAsyncData";
import type { AgentCatalog, Team, TeamStepInput } from "../lib/types";

interface Props {
  onError: (message: string) => void;
  onSuccess: (message: string) => void;
  onChanged: () => void;
}

export default function TeamsTab({ onError, onSuccess, onChanged }: Props) {
  const catalog = useAsyncData<AgentCatalog>(() => api.agents.catalog());
  const teams = useAsyncData<Team[]>(() => api.teams.list());
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const agents = catalog.data?.agents ?? [];
  const selected = teams.data?.find((team) => team.id === selectedId) ?? null;

  return (
    <div className="fade-in">
      <PageHeader
        label="AI Teams"
        title="Build a Team"
        description="Compose a set of agents into a reusable research team, with an optional coordinator and an explicit workflow."
        actions={
          <Button
            size="sm"
            variant={selectedId === null ? "primary" : "secondary"}
            icon={<Plus size={12} />}
            onClick={() => setSelectedId(null)}
          >
            New team
          </Button>
        }
      />

      <div className="grid grid-cols-1 gap-12 lg:grid-cols-[260px_minmax(0,1fr)]">
        {/* ── Team archive ─────────────────────────────────────────────── */}
        <aside>
          <p className="t-label pb-3">Saved teams</p>
          <Rule />
          {teams.data?.length ? (
            <div>
              {teams.data.map((team, i) => {
                const active = team.id === selectedId;
                return (
                  <button
                    key={team.id}
                    type="button"
                    onClick={() => setSelectedId(team.id)}
                    aria-current={active ? "true" : undefined}
                    className="relative block w-full py-3.5 text-left transition-opacity hover:opacity-80"
                    style={{ borderBottom: "1px solid var(--border-subtle)" }}
                  >
                    <div className="flex items-baseline gap-3">
                      <Index n={i + 1} />
                      <div className="min-w-0">
                        <p
                          className="truncate text-[12px] font-medium"
                          style={{ color: active ? "var(--text)" : "var(--text-secondary)" }}
                        >
                          {team.name}
                        </p>
                        <p className="t-meta mt-1" style={{ color: "var(--text-faint)" }}>
                          {team.agent_slugs.length} agents
                          {team.coordinator_slug ? ` · ${team.coordinator_slug}` : ""}
                        </p>
                      </div>
                    </div>
                    {active && (
                      <span
                        aria-hidden
                        className="absolute left-0 top-0 h-full w-[2px]"
                        style={{ background: "var(--accent)" }}
                      />
                    )}
                  </button>
                );
              })}
            </div>
          ) : (
            <EmptyState
              title={teams.isInitialLoading ? "Loading…" : "No teams yet"}
              body={teams.isInitialLoading ? undefined : "Create one to run it from the workspace."}
            />
          )}
        </aside>

        {/* Keyed so selecting a different team remounts with fresh state. */}
        <TeamEditor
          key={selected?.id ?? "new"}
          team={selected}
          agents={agents}
          onError={onError}
          onSuccess={onSuccess}
          onSaved={async (savedId) => {
            setSelectedId(savedId);
            await teams.refetch();
            onChanged();
          }}
          onDeleted={async () => {
            setSelectedId(null);
            await teams.refetch();
            onChanged();
          }}
        />
      </div>
    </div>
  );
}

/* ── Editor ────────────────────────────────────────────────────────── */

interface EditorProps {
  team: Team | null;
  agents: AgentCatalog["agents"];
  onError: (message: string) => void;
  onSuccess: (message: string) => void;
  onSaved: (teamId: string) => Promise<void>;
  onDeleted: () => Promise<void>;
}

function TeamEditor({ team, agents, onError, onSuccess, onSaved, onDeleted }: EditorProps) {
  const [name, setName] = useState(team?.name ?? "");
  const [description, setDescription] = useState(team?.description ?? "");
  const [members, setMembers] = useState<string[]>(team?.agent_slugs ?? []);
  const [coordinator, setCoordinator] = useState(team?.coordinator_slug ?? "");
  const [instructions, setInstructions] = useState(team?.coordinator_instructions ?? "");
  const [steps, setSteps] = useState<TeamStepInput[]>(
    (team?.steps ?? []).map((step) => ({
      agent_slug: step.agent_slug,
      description: step.description,
      expected_output: step.expected_output,
    })),
  );
  const [busy, setBusy] = useState(false);

  const toggleMember = (slug: string) => {
    setMembers((previous) => {
      const next = previous.includes(slug)
        ? previous.filter((item) => item !== slug)
        : [...previous, slug];
      // Dropping the coordinator's membership must clear the coordinator too,
      // or the save fails server-side validation.
      if (!next.includes(coordinator)) setCoordinator("");
      return next;
    });
  };

  const save = async () => {
    if (!name.trim()) {
      onError("Give the team a name.");
      return;
    }
    if (members.length === 0) {
      onError("Add at least one agent.");
      return;
    }
    if (coordinator && !members.includes(coordinator)) {
      onError("The coordinator must also be a member of the team.");
      return;
    }

    const payload = {
      name: name.trim(),
      description: description.trim(),
      agent_slugs: members,
      coordinator_slug: coordinator || null,
      coordinator_instructions: instructions,
      steps: steps.filter((step) => step.agent_slug && step.description.trim()),
    };

    setBusy(true);
    try {
      if (team) {
        await api.teams.update(team.id, payload);
        onSuccess(`Updated "${payload.name}".`);
        await onSaved(team.id);
      } else {
        const created = await api.teams.create(payload);
        onSuccess(`Created "${created.name}".`);
        await onSaved(created.id);
      }
    } catch (caught) {
      onError(caught instanceof ApiError ? caught.message : "Could not save the team.");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!team) return;
    setBusy(true);
    try {
      await api.teams.remove(team.id);
      onSuccess("Team deleted.");
      await onDeleted();
    } catch (caught) {
      onError(caught instanceof ApiError ? caught.message : "Could not delete the team.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      {/* ── Identity ─────────────────────────────────────────────────── */}
      <Section label="Team" title={team ? "Edit" : "New"}>
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
          <Field label="Name" htmlFor="team-name">
            <Input
              id="team-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Market research squad"
            />
          </Field>
          <Field
            label="Coordinator"
            htmlFor="team-coordinator"
            hint="Optional. Runs the steps in order without one."
          >
            <Select
              id="team-coordinator"
              value={coordinator}
              onChange={(event) => setCoordinator(event.target.value)}
            >
              <option value="">None — sequential</option>
              {members.map((slug) => (
                <option key={slug} value={slug}>
                  {slug}
                </option>
              ))}
            </Select>
          </Field>
        </div>

        <div className="mt-5">
          <Field label="Purpose" htmlFor="team-description">
            <Input
              id="team-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="What this team is for"
            />
          </Field>
        </div>
      </Section>

      {/* ── Members ──────────────────────────────────────────────────── */}
      <Section
        label="Members"
        title="Agents"
        className="mt-12"
        actions={
          <span className="t-meta" style={{ color: "var(--text-faint)" }}>
            {members.length} selected
          </span>
        }
      >
        {agents.length === 0 ? (
          <EmptyState icon={<Users size={18} />} title="No agents available" />
        ) : (
          <div>
            {agents.map((agent, i, all) => {
              const active = members.includes(agent.slug);
              return (
                <div key={agent.id}>
                  <button
                    type="button"
                    onClick={() => toggleMember(agent.slug)}
                    aria-pressed={active}
                    className="flex w-full items-center gap-4 py-3.5 text-left transition-opacity hover:opacity-80"
                  >
                    <Index n={i + 1} />
                    <div className="min-w-0 flex-1">
                      <p
                        className="text-[12.5px] font-medium"
                        style={{ color: active ? "var(--text)" : "var(--text-muted)" }}
                      >
                        {agent.name}
                      </p>
                      <p className="t-meta mt-0.5" style={{ color: "var(--text-faint)" }}>
                        {agent.role}
                      </p>
                    </div>
                    <span
                      className="shrink-0 rounded-full transition-all"
                      style={{
                        width: 16,
                        height: 16,
                        border: `1px solid ${active ? "var(--accent)" : "var(--border-strong)"}`,
                        background: active ? "var(--accent)" : "transparent",
                      }}
                      aria-hidden
                    />
                  </button>
                  {i < all.length - 1 && <Rule />}
                </div>
              );
            })}
          </div>
        )}
      </Section>

      {/* ── Coordinator instructions ─────────────────────────────────── */}
      <Section label="Orchestration" title="Coordinator Instructions" className="mt-12">
        <Textarea
          value={instructions}
          onChange={(event) => setInstructions(event.target.value)}
          rows={3}
          placeholder="How the coordinator should sequence and gate the work."
        />
      </Section>

      {/* ── Workflow ─────────────────────────────────────────────────── */}
      <Section
        label="Workflow"
        title="Steps"
        className="mt-12"
        actions={
          <Button
            size="sm"
            variant="ghost"
            icon={<Plus size={11} />}
            onClick={() =>
              setSteps((previous) => [
                ...previous,
                { agent_slug: members[0] ?? "", description: "", expected_output: "" },
              ])
            }
          >
            Add step
          </Button>
        }
      >
        {steps.length === 0 ? (
          <p className="t-meta py-4">
            No explicit steps. Agents run in the order listed above.
          </p>
        ) : (
          <div>
            {steps.map((step, index) => (
              <div key={index}>
                <div className="flex flex-col gap-3 py-4 sm:flex-row sm:items-start">
                  <div className="pt-2.5">
                    <Index n={index + 1} />
                  </div>
                  <Select
                    value={step.agent_slug}
                    aria-label={`Step ${index + 1} agent`}
                    onChange={(event) =>
                      setSteps((previous) =>
                        previous.map((item, i) =>
                          i === index ? { ...item, agent_slug: event.target.value } : item,
                        ),
                      )
                    }
                    style={{ width: "auto", minWidth: 140 }}
                  >
                    <option value="">pick agent</option>
                    {members.map((slug) => (
                      <option key={slug} value={slug}>
                        {slug}
                      </option>
                    ))}
                  </Select>
                  <Input
                    value={step.description}
                    aria-label={`Step ${index + 1} description`}
                    onChange={(event) =>
                      setSteps((previous) =>
                        previous.map((item, i) =>
                          i === index ? { ...item, description: event.target.value } : item,
                        ),
                      )
                    }
                    placeholder="What this step does"
                    className="flex-1"
                  />
                  <IconButton
                    label={`Remove step ${index + 1}`}
                    icon={<Trash2 size={12} />}
                    onClick={() => setSteps((previous) => previous.filter((_, i) => i !== index))}
                    style={{ color: "var(--danger)" }}
                  />
                </div>
                {index < steps.length - 1 && <Rule />}
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* ── Actions ──────────────────────────────────────────────────── */}
      <div className="mt-10 flex items-center gap-2">
        <Button
          variant="primary"
          disabled={busy}
          onClick={() => void save()}
          icon={busy ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
        >
          {team ? "Save changes" : "Create team"}
        </Button>
        {team && (
          <Button
            variant="danger"
            disabled={busy}
            onClick={() => void remove()}
            icon={<Trash2 size={12} />}
          >
            Delete
          </Button>
        )}
        {team && <Chip>{team.agent_slugs.length} agents</Chip>}
      </div>
    </div>
  );
}
