"use client";

/**
 * Settings: appearance, provider credentials, and the account.
 *
 * Deliberately only real controls. The brief listed plausible-looking sections
 * (research depth, citation behaviour, notifications) but none of them map to
 * a server-side setting, and a settings screen full of switches that do
 * nothing is worse than a shorter honest one.
 *
 * Two credential behaviours are load-bearing:
 * * A saved key is never displayed. The server returns only a four-character
 *   hint, and the field stays empty unless the user is replacing it — so the
 *   browser does not hold the secret after the first save.
 * * Validation is available *before* saving, so a typo is caught while the key
 *   is still in the input rather than after it has been stored.
 */

import { useState } from "react";
import {
  AlertCircle,
  CheckCircle,
  KeyRound,
  Loader2,
  LogOut,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trash2,
} from "lucide-react";

import ThemeToggle from "./ThemeToggle";
import {
  Button,
  Chip,
  EmptyState,
  Field,
  IconButton,
  Input,
  PageHeader,
  Rule,
  Section,
  Select,
  Switch,
} from "./ui";
import { ApiError, api } from "../lib/api";
import { useAnimations } from "../hooks/useAnimations";
import { useAsyncData } from "../hooks/useAsyncData";
import { useTheme } from "../hooks/useTheme";
import { formatTimestamp } from "../lib/derive";
import type { Credential, ProviderName, ProviderStatus, Session } from "../lib/types";

interface Props {
  userEmail: string;
  isSuperuser: boolean;
  onError: (message: string) => void;
  onSuccess: (message: string) => void;
  onLogout: () => void;
}

export default function SettingsTab({
  userEmail,
  isSuperuser,
  onError,
  onSuccess,
  onLogout,
}: Props) {
  const providers = useAsyncData<ProviderStatus[]>(() => api.credentials.providers());
  const credentials = useAsyncData<Credential[]>(() => api.credentials.list());
  const sessions = useAsyncData<Session[]>(() => api.auth.sessions());
  const { theme } = useTheme();
  const { animationsEnabled, setAnimations } = useAnimations();

  const [editing, setEditing] = useState<ProviderName | null>(null);
  const [keyInput, setKeyInput] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [modelInput, setModelInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [detecting, setDetecting] = useState(false);
  // Discovered catalogues, keyed by provider. Cleared when the editor closes so
  // a stale list from another provider is never shown.
  const [models, setModels] = useState<Record<string, string[]>>({});
  const [modelError, setModelError] = useState<Record<string, string>>({});
  const [testResult, setTestResult] = useState<
    Record<string, { valid: boolean; error: string; latency_ms: number }>
  >({});

  const refreshAll = async () => {
    await Promise.all([providers.refetch(), credentials.refetch(), sessions.refetch()]);
  };

  const beginEdit = (provider: ProviderStatus) => {
    const stored = credentials.data?.find((item) => item.provider === provider.provider);
    setEditing(provider.provider);
    setKeyInput("");
    setBaseUrl(stored?.base_url ?? "");
    // Seed from the pinned model so re-opening the editor does not silently
    // reset a deliberate choice back to the provider default.
    setModelInput(stored?.default_model || provider.default_model || "");
    setModelError({});
  };

  /**
   * Ask the provider what it serves right now.
   *
   * This is the fix for the "model issue" class of failure: providers retire
   * ids without warning, so a hardcoded default only fails at run time with an
   * opaque error. Detection happens before saving, while the key is still in
   * the input, so a bad model is caught rather than stored.
   */
  const detectModels = async (provider: ProviderName) => {
    setDetecting(true);
    setModelError((previous) => ({ ...previous, [provider]: "" }));
    try {
      const result = await api.credentials.models({
        provider,
        api_key: keyInput,
        base_url: baseUrl,
      });

      if (result.error) {
        setModelError((previous) => ({ ...previous, [provider]: result.error }));
        setModels((previous) => ({ ...previous, [provider]: [] }));
        return;
      }

      setModels((previous) => ({ ...previous, [provider]: result.models }));
      // Only auto-select when nothing is chosen, so detection never overwrites
      // a model the user picked on purpose.
      setModelInput((current) => current || result.models[0] || "");
    } catch (caught) {
      setModelError((previous) => ({
        ...previous,
        [provider]: caught instanceof ApiError ? caught.message : "Could not list models.",
      }));
    } finally {
      setDetecting(false);
    }
  };

  const save = async (provider: ProviderName) => {
    setBusy(true);
    try {
      await api.credentials.save({
        provider,
        // Empty means "keep the stored key" — sending it is what lets a user
        // change the model or base URL without re-entering the secret.
        api_key: keyInput,
        base_url: baseUrl,
        default_model: modelInput,
      });
      onSuccess(keyInput ? "Key saved." : "Settings updated.");
      setEditing(null);
      setKeyInput("");
      setModels((previous) => ({ ...previous, [provider]: [] }));
      await refreshAll();
    } catch (caught) {
      onError(caught instanceof ApiError ? caught.message : "Could not save the credential.");
    } finally {
      setBusy(false);
    }
  };

  const test = async (provider: ProviderName, stored: boolean) => {
    setBusy(true);
    try {
      const result = stored
        ? await api.credentials.validateStored(provider)
        : await api.credentials.test({
            provider,
            api_key: keyInput,
            model: modelInput,
            base_url: baseUrl,
          });
      const valid = "valid" in result ? result.valid : true;
      setTestResult((previous) => ({
        ...previous,
        [provider]: {
          valid,
          error: "error" in result ? result.error : "",
          latency_ms: "latency_ms" in result ? result.latency_ms : 0,
        },
      }));
      if (stored) await credentials.refetch();
    } catch (caught) {
      setTestResult((previous) => ({
        ...previous,
        [provider]: {
          valid: false,
          error: caught instanceof ApiError ? caught.message : "Validation failed.",
          latency_ms: 0,
        },
      }));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (provider: ProviderName) => {
    setBusy(true);
    try {
      await api.credentials.remove(provider);
      onSuccess("Credential removed.");
      await refreshAll();
    } catch (caught) {
      onError(caught instanceof ApiError ? caught.message : "Could not remove the credential.");
    } finally {
      setBusy(false);
    }
  };

  const storedFor = (provider: ProviderName) =>
    credentials.data?.find((item) => item.provider === provider);

  return (
    <div className="fade-in">
      <PageHeader
        label="Configuration"
        title="Settings"
        description="Appearance, provider credentials and account access."
      />

      {/* ── Appearance ────────────────────────────────────────────────── */}
      <Section label="Interface" title="Appearance">
        <div className="flex flex-col gap-6">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="max-w-lg">
              <p className="t-h3">Theme</p>
              <p className="t-meta mt-1">
                Currently using the {theme} theme. Dark is the default.
              </p>
            </div>
            <ThemeToggle />
          </div>

          <Rule />

          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="max-w-lg">
              <p className="t-h3">Background animations</p>
              <p className="t-meta mt-1">
                The drifting particle field and ambient light behind every page.
                Turning this off freezes the backdrop rather than hiding it, and
                stops the entrance and hover transitions too.
              </p>
            </div>
            <Switch
              checked={animationsEnabled}
              onChange={setAnimations}
              label="Background animations"
            />
          </div>
        </div>
      </Section>

      {/* ── Credentials ───────────────────────────────────────────────── */}
      <Section
        label="Providers"
        title="API Credentials"
        className="mt-14"
        actions={
          <span className="t-meta" style={{ color: "var(--text-faint)" }}>
            encrypted at rest · never returned
          </span>
        }
      >
        <p className="t-body mb-6 max-w-2xl" style={{ fontSize: "0.8125rem", color: "var(--text-muted)" }}>
          Keys are encrypted with a server-derived key before they touch the database, and the API
          only ever returns the last four characters. Leave the key field empty when saving to keep
          the stored key.
        </p>
        <p className="t-body mb-6 max-w-2xl" style={{ fontSize: "0.8125rem", color: "var(--text-muted)" }}>
          Use <strong style={{ color: "var(--text-secondary)" }}>Custom</strong> for any
          OpenAI-compatible platform — Inception, Together, OpenRouter, DeepSeek, a local vLLM.
          Paste its API root (usually ending in <code className="t-meta">/v1</code>) and the key,
          then <strong style={{ color: "var(--text-secondary)" }}>Detect models</strong> to list
          what it serves right now and pick one. Providers retire model ids without warning, so
          detecting beats trusting a default.
        </p>

        {providers.isInitialLoading ? (
          <div className="flex items-center gap-2 py-10">
            <Loader2 size={14} className="animate-spin" style={{ color: "var(--text-faint)" }} />
            <span className="t-meta">Loading providers…</span>
          </div>
        ) : (
          <div>
            {(providers.data ?? []).map((provider, i, all) => {
              const stored = storedFor(provider.provider);
              const isEditing = editing === provider.provider;
              const result = testResult[provider.provider];

              return (
                <div key={provider.provider}>
                  <div className="py-5">
                    <div className="flex flex-wrap items-start justify-between gap-4">
                      <div className="flex items-start gap-4">
                        <span
                          className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"
                          style={{
                            background: "var(--surface-hover)",
                            border: "1px solid var(--border-subtle)",
                            color: "var(--text-muted)",
                          }}
                        >
                          <KeyRound size={13} />
                        </span>
                        <div>
                          <div className="flex flex-wrap items-center gap-2.5">
                            <h3 className="t-h3 uppercase tracking-wider">{provider.provider}</h3>
                            {provider.configured ? (
                              <Chip tone="success">
                                <CheckCircle size={9} />
                                {provider.source === "environment" ? "from env" : "configured"}
                              </Chip>
                            ) : (
                              <Chip>
                                {provider.requires_key ? "not configured" : "no key needed"}
                              </Chip>
                            )}
                          </div>
                          <p className="t-meta mt-1.5" style={{ color: "var(--text-faint)" }}>
                            {/* Show what a run will actually use, and say which
                                one that is — a pinned model that silently did
                                nothing was the confusing part before. */}
                            {stored?.default_model
                              ? `${stored.default_model} · pinned`
                              : provider.default_model}
                            {stored?.key_hint ? ` · ····${stored.key_hint}` : ""}
                          </p>
                        </div>
                      </div>

                      <div className="flex flex-wrap items-center gap-2">
                        {stored?.has_key && (
                          <Button
                            size="sm"
                            variant="ghost"
                            disabled={busy}
                            onClick={() => void test(provider.provider, true)}
                          >
                            Test
                          </Button>
                        )}
                        <Button
                          size="sm"
                          variant={isEditing ? "ghost" : "secondary"}
                          disabled={busy}
                          onClick={() => (isEditing ? setEditing(null) : beginEdit(provider))}
                          icon={isEditing ? undefined : <Plus size={11} />}
                        >
                          {isEditing ? "Cancel" : stored?.has_key ? "Replace" : "Add key"}
                        </Button>
                        {stored?.has_key && (
                          <IconButton
                            label={`Remove ${provider.provider} credential`}
                            icon={<Trash2 size={12} />}
                            disabled={busy}
                            onClick={() => void remove(provider.provider)}
                            style={{ color: "var(--danger)" }}
                          />
                        )}
                      </div>
                    </div>

                    {result && (
                      <div
                        className="mt-4 flex items-start gap-2 rounded-lg px-3 py-2.5 text-[11.5px]"
                        style={{
                          background: result.valid
                            ? "color-mix(in srgb, var(--success) 8%, transparent)"
                            : "color-mix(in srgb, var(--danger) 8%, transparent)",
                          color: result.valid ? "var(--success)" : "var(--danger)",
                        }}
                      >
                        {result.valid ? <CheckCircle size={12} /> : <AlertCircle size={12} />}
                        <span>
                          {result.valid
                            ? `Key accepted${result.latency_ms ? ` in ${result.latency_ms}ms` : ""}.`
                            : result.error || "The provider rejected this key."}
                        </span>
                      </div>
                    )}

                    {isEditing && (
                      <div className="mt-5 flex flex-col gap-4 rounded-xl p-4" style={{ background: "var(--surface-hover)" }}>
                        <Field label="API key" htmlFor={`key-${provider.provider}`}>
                          <Input
                            id={`key-${provider.provider}`}
                            mono
                            type="password"
                            value={keyInput}
                            onChange={(event) => setKeyInput(event.target.value)}
                            placeholder={
                              stored?.has_key
                                ? "Leave empty to keep the current key"
                                : `Paste your ${provider.provider} key`
                            }
                          />
                        </Field>

                        <Field
                          label="Base URL"
                          htmlFor={`url-${provider.provider}`}
                          hint={
                            provider.requires_base_url
                              ? "Required. The OpenAI-compatible API root, e.g. https://api.inceptionlabs.ai/v1"
                              : "Optional. Only needed for a self-hosted or proxy endpoint."
                          }
                        >
                          <Input
                            id={`url-${provider.provider}`}
                            mono
                            value={baseUrl}
                            onChange={(event) => setBaseUrl(event.target.value)}
                            placeholder={provider.requires_base_url ? "https://…/v1" : ""}
                          />
                        </Field>

                        {/* Model picker. Detection is the point: it asks the
                            provider what it actually serves, so a retired id
                            is caught here rather than mid-run. */}
                        <div className="flex flex-col gap-1.5">
                          <div className="flex items-center justify-between gap-3">
                            <label className="t-label" htmlFor={`model-${provider.provider}`}>
                              Model
                            </label>
                            <button
                              type="button"
                              disabled={detecting}
                              onClick={() => void detectModels(provider.provider)}
                              className="t-meta flex items-center gap-1.5 transition-opacity hover:opacity-70 disabled:opacity-50"
                              style={{ color: "var(--text-secondary)" }}
                            >
                              {detecting ? (
                                <Loader2 size={10} className="animate-spin" />
                              ) : (
                                <RefreshCw size={10} />
                              )}
                              {detecting ? "Checking…" : "Detect models"}
                            </button>
                          </div>

                          {models[provider.provider]?.length ? (
                            <Select
                              id={`model-${provider.provider}`}
                              value={modelInput}
                              onChange={(event) => setModelInput(event.target.value)}
                            >
                              {models[provider.provider].map((model) => (
                                <option key={model} value={model}>
                                  {model}
                                </option>
                              ))}
                            </Select>
                          ) : (
                            <Input
                              id={`model-${provider.provider}`}
                              mono
                              value={modelInput}
                              onChange={(event) => setModelInput(event.target.value)}
                              placeholder={provider.default_model || "model id"}
                            />
                          )}

                          {modelError[provider.provider] ? (
                            <span className="t-meta" style={{ color: "var(--warning)" }}>
                              {modelError[provider.provider]}
                            </span>
                          ) : models[provider.provider]?.length ? (
                            <span className="t-meta" style={{ color: "var(--success)" }}>
                              {models[provider.provider].length} models found — pick one above.
                            </span>
                          ) : (
                            <span className="t-meta" style={{ color: "var(--text-faint)" }}>
                              Default: {provider.default_model || "none"}. Detect models to list
                              what this provider serves now.
                            </span>
                          )}
                        </div>

                        <div className="flex items-center gap-2">
                          <Button
                            variant="primary"
                            size="sm"
                            disabled={busy}
                            onClick={() => void save(provider.provider)}
                            icon={busy ? <Loader2 size={11} className="animate-spin" /> : undefined}
                          >
                            Save
                          </Button>
                          {keyInput && (
                            <Button
                              size="sm"
                              variant="ghost"
                              disabled={busy}
                              onClick={() => void test(provider.provider, false)}
                            >
                              Test before saving
                            </Button>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                  {i < all.length - 1 && <Rule />}
                </div>
              );
            })}
          </div>
        )}
      </Section>

      {/* ── Account ───────────────────────────────────────────────────── */}
      <Section label="Account" title="Access" className="mt-14">
        <div className="flex flex-wrap items-center justify-between gap-4 pb-6">
          <div>
            <p className="t-h3">{userEmail}</p>
            <p className="t-meta mt-1">{isSuperuser ? "Administrator" : "Member"}</p>
          </div>
          <Button variant="secondary" onClick={onLogout} icon={<LogOut size={13} />}>
            Sign out
          </Button>
        </div>

        <Rule />

        <div className="pt-5">
          <p className="t-label mb-3">Active sessions</p>
          {sessions.data?.length ? (
            <div>
              {sessions.data.map((session) => (
                <div
                  key={session.id}
                  className="flex items-center justify-between gap-4 py-3"
                  style={{ borderBottom: "1px solid var(--border-subtle)" }}
                >
                  <div className="min-w-0">
                    <p className="t-meta truncate" style={{ color: "var(--text-secondary)" }}>
                      {session.user_agent || "unknown client"}
                    </p>
                    <p className="t-meta mt-0.5" style={{ color: "var(--text-faint)" }}>
                      {session.client_ip || "—"} · expires {formatTimestamp(session.expires_at)}
                    </p>
                  </div>
                  {session.is_current && <Chip>this device</Chip>}
                </div>
              ))}
            </div>
          ) : (
            <EmptyState
              icon={<ShieldCheck size={18} />}
              title={sessions.isLoading ? "Loading…" : "No active sessions"}
            />
          )}
        </div>
      </Section>
    </div>
  );
}
