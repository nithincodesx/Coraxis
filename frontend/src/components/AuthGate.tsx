"use client";

/**
 * Sign-in / registration gate.
 *
 * Identity is handled by Firebase: GitHub OAuth and email/password. After a
 * successful sign-in the Firebase ID token is sent as the bearer token on
 * every API request, and the backend maps the Firebase account to a Coraxis
 * user by email.
 */

import { FormEvent, useState } from "react";
import { AlertCircle, ArrowRight, Loader2, Mail } from "lucide-react";

import { Button, Field, Input, Rule } from "./ui";
import { ApiError } from "../lib/api";
import { useAuth } from "../hooks/useAuth";

type Mode = "login" | "register";

const MIN_PASSWORD_LENGTH = 12;

interface Props {
  onAuthenticated?: () => void;
}

export default function AuthGate({ onAuthenticated }: Props) {
  const { login, loginWithGitHub, register } = useAuth();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  const isRegister = mode === "register";

  const handleProviderSignIn = async () => {
    setError(null);
    setFieldErrors({});
    setBusy(true);
    try {
      await loginWithGitHub();
      onAuthenticated?.();
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Could not sign in with GitHub. Try again."
      );
    } finally {
      setBusy(false);
    }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setFieldErrors({});
    setBusy(true);

    try {
      if (isRegister) {
        await register(email.trim(), password, displayName.trim());
      } else {
        await login(email.trim(), password);
      }
      onAuthenticated?.();
    } catch (caught) {
      if (caught instanceof ApiError) {
        setError(caught.message);
        if (caught.problem?.errors) {
          const mapped: Record<string, string> = {};
          for (const entry of caught.problem.errors) {
            const field = (entry as { field?: string }).field;
            if (field) mapped[field] = entry.message;
          }
          setFieldErrors(mapped);
        }
      } else {
        setError("Something went wrong. Try again.");
      }
    } finally {
      setBusy(false);
    }
  };

  const switchMode = () => {
    setMode(isRegister ? "login" : "register");
    setError(null);
    setFieldErrors({});
  };

  return (
    <div className="flex min-h-full w-full items-center justify-center px-6 py-16">
      <div className="w-full max-w-[400px] fade-in">
        <div className="mb-10 flex flex-col items-center text-center">
          <p className="t-label">Autonomous Research Laboratory</p>
          <h1
            className="font-display mt-3 text-[26px] font-bold tracking-[0.2em]"
            style={{ color: "var(--text)" }}
          >
            CORAXIS
          </h1>
        </div>

        <Rule />

        <div className="pt-8">
          <h2 className="t-h1">{isRegister ? "Create your account" : "Sign in"}</h2>
          <p className="t-body mt-2" style={{ color: "var(--text-muted)", fontSize: "0.8125rem" }}>
            {isRegister
              ? "The first account created on an instance becomes its administrator."
              : "Sign in with GitHub, or with your email and password."}
          </p>

          {error && (
            <div
              role="alert"
              className="mt-6 flex items-start gap-2.5 rounded-xl px-3.5 py-3 text-[12px]"
              style={{
                border: "1px solid color-mix(in srgb, var(--danger) 30%, transparent)",
                background: "color-mix(in srgb, var(--danger) 8%, transparent)",
                color: "var(--danger)",
              }}
            >
              <AlertCircle size={14} className="mt-0.5 shrink-0" />
              <span style={{ lineHeight: 1.6 }}>{error}</span>
            </div>
          )}

          {/* ── Social sign-in ── */}
          <div className="mt-6">
            <Button
              onClick={handleProviderSignIn}
              disabled={busy}
              className="w-full"
            >
              {busy ? "Working…" : "Sign in with GitHub"}
            </Button>
          </div>

          <div className="mt-5 relative">
            <Rule className="absolute inset-0 flex-1" />
            <span className="absolute -top-px left-1/2 -translate-x-1/2 flex items-center gap-2 px-2" style={{ color: "var(--text-faint)", fontSize: "0.75rem" }}>
              <Mail size={12} />
              or continue with email
            </span>
          </div>

          <form onSubmit={submit} className="mt-6 flex flex-col gap-5">
            {isRegister && (
              <Field label="Display name" htmlFor="display_name" error={fieldErrors.display_name}>
                <Input
                  id="display_name"
                  name="display_name"
                  value={displayName}
                  onChange={(event) => setDisplayName(event.target.value)}
                  placeholder="Ada Lovelace"
                  autoComplete="name"
                />
              </Field>
            )}

            <Field label="Email" htmlFor="email" error={fieldErrors.email}>
              <Input
                id="email"
                name="email"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@example.com"
                autoComplete="email"
                required
              />
            </Field>

            <Field
              label="Password"
              htmlFor="password"
              error={fieldErrors.password}
              hint={isRegister ? `At least ${MIN_PASSWORD_LENGTH} characters.` : undefined}
            >
              <Input
                id="password"
                name="password"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="••••••••••••"
                autoComplete={isRegister ? "new-password" : "current-password"}
                required
              />
            </Field>

            <Button
              type="submit"
              variant="primary"
              disabled={busy}
              className="mt-1 w-full"
              icon={busy ? <Loader2 size={14} className="animate-spin" /> : <ArrowRight size={14} />}
            >
              {busy ? "Working…" : isRegister ? "Create account" : "Sign in"}
            </Button>
          </form>

          <div className="mt-8 flex items-center gap-3">
            <Rule className="flex-1" />
            <button
              type="button"
              onClick={switchMode}
              className="t-meta transition-colors hover:opacity-70"
              style={{ color: "var(--text-secondary)", whiteSpace: "nowrap" }}
            >
              {isRegister ? "Have an account? Sign in" : "Create one"}
            </button>
            <Rule className="flex-1" />
          </div>
        </div>
      </div>
    </div>
  );
}
