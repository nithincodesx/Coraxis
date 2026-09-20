"use client";

/**
 * The shared component vocabulary.
 *
 * Every surface in the app is built from these, so the landing page's
 * restraint carries through instead of each page inventing its own card. The
 * guiding rule: prefer a hairline rule and whitespace over a box, and reach
 * for a panel only when content genuinely needs containment.
 */

import type { ReactNode } from "react";

export type Tone = "neutral" | "success" | "warning" | "danger" | "info";

/* ── Buttons ───────────────────────────────────────────────────────── */

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
  icon?: ReactNode;
  children?: ReactNode;
}

export function Button({
  variant = "secondary",
  size = "md",
  icon,
  children,
  className = "",
  type = "button",
  ...rest
}: ButtonProps) {
  const classes = [
    "btn",
    `btn-${variant}`,
    size === "sm" ? "btn-sm" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <button type={type} className={classes} {...rest}>
      {icon}
      {children}
    </button>
  );
}

export function IconButton({
  icon,
  label,
  className = "",
  type = "button",
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { icon: ReactNode; label: string }) {
  return (
    <button
      type={type}
      aria-label={label}
      title={label}
      className={`btn btn-ghost btn-icon ${className}`}
      {...rest}
    >
      {icon}
    </button>
  );
}

/* ── Form controls ─────────────────────────────────────────────────── */

interface FieldProps {
  label: string;
  htmlFor?: string;
  hint?: string;
  error?: string;
  children: ReactNode;
}

export function Field({ label, htmlFor, hint, error, children }: FieldProps) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="t-label">
        {label}
      </label>
      {children}
      {error ? (
        <span className="text-[11px] font-medium" style={{ color: "var(--danger)" }}>
          {error}
        </span>
      ) : hint ? (
        <span className="t-meta" style={{ color: "var(--text-faint)" }}>
          {hint}
        </span>
      ) : null}
    </div>
  );
}

export function Input({
  mono,
  className = "",
  ...rest
}: React.InputHTMLAttributes<HTMLInputElement> & { mono?: boolean }) {
  return <input className={`input ${mono ? "input-mono" : ""} ${className}`} {...rest} />;
}

export function Textarea({
  className = "",
  ...rest
}: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={`input ${className}`} {...rest} />;
}

export function Select({
  className = "",
  children,
  ...rest
}: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={`input ${className}`} {...rest}>
      {children}
    </select>
  );
}

/* ── Status ────────────────────────────────────────────────────────── */

export function StatusDot({ tone = "neutral", pulse = false }: { tone?: Tone; pulse?: boolean }) {
  const map: Record<Tone, string> = {
    neutral: "dot",
    success: "dot dot-live",
    warning: "dot dot-warn",
    danger: "dot dot-error",
    info: "dot dot-active",
  };
  const cls = pulse ? (tone === "neutral" ? "dot dot-active" : map[tone]) : map[tone];
  return <span className={cls} aria-hidden />;
}

export function Chip({
  tone = "neutral",
  children,
  className = "",
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
}) {
  const toneClass = tone === "neutral" ? "" : `chip-${tone}`;
  return <span className={`chip ${toneClass} ${className}`}>{children}</span>;
}

/* ── Structure ─────────────────────────────────────────────────────── */

export function Panel({
  children,
  className = "",
  quiet = false,
  ...rest
}: React.HTMLAttributes<HTMLDivElement> & { quiet?: boolean }) {
  return (
    <div className={`${quiet ? "panel-quiet" : "panel"} ${className}`} {...rest}>
      {children}
    </div>
  );
}

export function Rule({ strong = false, className = "" }: { strong?: boolean; className?: string }) {
  return <div className={`${strong ? "rule-strong" : "rule"} ${className}`} role="separator" />;
}

/**
 * Page header: a small technical label above a large title, with optional
 * right-aligned actions. Mirrors the landing page's label-over-display
 * hierarchy rather than a dashboard toolbar.
 */
export function PageHeader({
  label,
  title,
  description,
  actions,
}: {
  label: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="flex flex-col gap-4 pb-6 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <p className="t-label">{label}</p>
        <h1 className="t-display mt-2">{title}</h1>
        {description && (
          <p className="t-body mt-2 max-w-2xl" style={{ color: "var(--text-muted)" }}>
            {description}
          </p>
        )}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </header>
  );
}

/**
 * A titled section separated by a rule. This is the app's main structural
 * device — it replaces the "everything in a rounded card" pattern.
 */
export function Section({
  label,
  title,
  actions,
  children,
  className = "",
}: {
  label?: string;
  title?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={className}>
      {(label || title || actions) && (
        <>
          <div className="flex items-center justify-between gap-4 pb-3">
            <div className="min-w-0">
              {label && <p className="t-label">{label}</p>}
              {title && <h2 className={`t-h2 ${label ? "mt-1" : ""}`}>{title}</h2>}
            </div>
            {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
          </div>
          <Rule />
        </>
      )}
      <div className="pt-4">{children}</div>
    </section>
  );
}

export function EmptyState({
  title,
  body,
  icon,
  action,
}: {
  title: string;
  body?: string;
  icon?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-14 text-center">
      {icon && <span style={{ color: "var(--text-faint)" }}>{icon}</span>}
      <p className="t-h3" style={{ color: "var(--text-secondary)" }}>
        {title}
      </p>
      {body && (
        <p className="t-meta max-w-xs" style={{ lineHeight: 1.7 }}>
          {body}
        </p>
      )}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

/** A single figure with a technical label, used in report and run summaries. */
export function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1">
      <span
        className="font-display text-xl font-semibold tabular-nums"
        style={{ color: "var(--text)", letterSpacing: "-0.02em" }}
      >
        {value}
      </span>
      <span className="t-label">{label}</span>
    </div>
  );
}

/** Inline key/value metadata row, monospace values. */
export function MetaRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5">
      <span className="t-meta">{label}</span>
      <span className="t-meta" style={{ color: "var(--text-secondary)" }}>
        {value}
      </span>
    </div>
  );
}

/** A monospace reference number: "01", "02" … */
export function Index({ n }: { n: number }) {
  return <span className="t-index">{String(n).padStart(2, "0")}</span>;
}

/**
 * On/off switch.
 *
 * A real `role="switch"` with `aria-checked` rather than a styled checkbox, so
 * screen readers announce the state instead of just "checkbox".
 */
export function Switch({
  checked,
  onChange,
  label,
  disabled = false,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className="relative shrink-0 rounded-full transition-colors disabled:opacity-40"
      style={{
        width: 38,
        height: 22,
        background: checked ? "var(--accent)" : "var(--surface-hover)",
        border: `1px solid ${checked ? "var(--accent)" : "var(--border-strong)"}`,
        transition: "background-color var(--dur) var(--ease), border-color var(--dur) var(--ease)",
      }}
    >
      <span
        aria-hidden
        className="absolute rounded-full"
        style={{
          width: 16,
          height: 16,
          top: 2,
          left: checked ? 19 : 2,
          background: checked ? "var(--accent-contrast)" : "var(--text-muted)",
          transition: "left var(--dur) var(--ease), background-color var(--dur) var(--ease)",
        }}
      />
    </button>
  );
}
