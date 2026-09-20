"use client";

/**
 * Sign-in / registration gate.
 *
 * The rebuilt backend requires a bearer token on every route, so the app needs
 * an entry point that did not exist before. Styled as a quiet editorial page
 * rather than a boxed login card: display title, hairline form, one off-white
 * primary action.
 */

import { FormEvent, useState } from "react";
import { AlertCircle, ArrowRight, Loader2 } from "lucide-react";

import { Button, Field, Input, Rule } from "./ui";
import { ApiError } from "../lib/api";
import { useAuth } from "../hooks/useAuth";

type Mode = "login" | "register";

const MIN_PASSWORD_LENGTH = 12;

interface Props {
  /**
   * Called after a successful sign-in or registration. The shell uses this to
   * skip the landing page for someone who has just authenticated, rather than
   * watching the auth state from an effect.
   */
  onAuthenticated?: () => void;
}

export default function AuthGate({ onAuthenticated }: Props) {
  const { login, register } = useAuth();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  const isRegister = mode === "register";

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
        // 422s carry per-field detail; surface it against the right input
        // instead of dumping it all into one banner.
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
    // Fills the shell's content area rather than the viewport — the shared
    // frame and navigation are already above it.
    <div className="flex min-h-full w-full items-center justify-center px-6 py-16">
      <div className="w-full max-w-[400px] fade-in">
        {/* Brand */}
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
              : "Provider keys stay encrypted on the server and are never returned to the browser."}
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
