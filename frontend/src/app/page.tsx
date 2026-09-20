"use client";

/**
 * The application.
 *
 * The shell and the navigation are mounted once, at the top, and never
 * unmount. Everything below them — the boot spinner, the sign-in gate, the
 * landing hero, the four workspace tabs — swaps inside `.app-content`.
 *
 * That ordering is the point. Previously each state returned a whole tree of
 * its own, so the landing page and the app were two different shells and
 * moving between them tore down and rebuilt the frame. Here the frame is
 * structurally stable and only the content changes, which is why the border
 * radius, the nav position and the backdrop never flicker.
 *
 * State that outlives a content swap (the session, the active tab, the toast
 * queue, the team list) lives at this level. Everything else lives in the
 * component that renders it.
 */

import { useCallback, useState } from "react";
import { AlertCircle, CheckCircle, Info, Loader2 } from "lucide-react";

import AgentsTab from "../components/AgentsTab";
import AppShell from "../components/AppShell";
import AuthGate from "../components/AuthGate";
import SettingsTab from "../components/SettingsTab";
import TeamsTab from "../components/TeamsTab";
import TopNavigation from "../components/TopNavigation";
import WorkspaceTab from "../components/WorkspaceTab";

import HeroContent from "./hero";

import { useAsyncData } from "../hooks/useAsyncData";
import { useAuth } from "../hooks/useAuth";
import { api } from "../lib/api";
import { DEFAULT_TAB, type Tab } from "../lib/nav";
import type { Team } from "../lib/types";

interface Toast {
  id: number;
  type: "success" | "error" | "info";
  message: string;
}

export default function Home() {
  const { user, isReady, isAuthenticated, logout } = useAuth();
  const [activeTab, setActiveTab] = useState<Tab>(DEFAULT_TAB);
  const [showHero, setShowHero] = useState(true);
  const [toasts, setToasts] = useState<Toast[]>([]);

  const teams = useAsyncData<Team[]>(() => api.teams.list(), { enabled: isAuthenticated });

  const notify = useCallback((type: Toast["type"], message: string) => {
    const id = Date.now() + Math.random();
    setToasts((previous) => [...previous, { id, type, message }]);
    window.setTimeout(() => {
      setToasts((previous) => previous.filter((toast) => toast.id !== id));
    }, 4500);
  }, []);

  const onError = useCallback((message: string) => notify("error", message), [notify]);
  const onSuccess = useCallback((message: string) => notify("success", message), [notify]);

  const signOut = useCallback(() => {
    void logout();
    setActiveTab(DEFAULT_TAB);
    setShowHero(true);
  }, [logout]);

  /** Entering the app from the hero, or switching tabs, both land here. */
  const goTo = useCallback((tab: Tab) => {
    setActiveTab(tab);
    setShowHero(false);
  }, []);

  return (
    <AppShell>
      <TopNavigation
        // Every value here that comes from `useAuth` must be gated on
        // `isReady`. `useAuth` seeds its user from localStorage, which does not
        // exist during SSR — so the server renders the signed-out navigation
        // and the client's first render would otherwise render the signed-in
        // one. `isReady` is false on both sides until the session is checked,
        // which makes the two agree. Without this the whole tree is thrown away
        // and rebuilt on hydration.
        activeTab={!isReady || showHero || !isAuthenticated ? null : activeTab}
        onNavigate={goTo}
        onHome={() => setShowHero(true)}
        tabsDisabled={!isReady || !isAuthenticated}
        userLabel={
          isReady && isAuthenticated
            ? user?.display_name || user?.email || "Account"
            : undefined
        }
        userEmail={user?.email}
        onSignOut={isReady && isAuthenticated ? signOut : undefined}
      />

      <div className="app-content">
        {!isReady ? (
          // Verifying the stored session is a network round trip. Shown inside
          // the shell so the frame never blinks out on a cold load.
          <div className="flex h-full items-center justify-center">
            <Loader2 size={18} className="animate-spin" style={{ color: "var(--text-faint)" }} />
          </div>
        ) : !isAuthenticated ? (
          <AuthGate onAuthenticated={() => setShowHero(false)} />
        ) : showHero ? (
          <HeroContent onEnter={(tab) => (tab ? goTo(tab) : setShowHero(false))} />
        ) : (
          <div className="app-page">
            {activeTab === "agents" && (
              <AgentsTab
                onError={onError}
                onSuccess={onSuccess}
                onChanged={() => void teams.refetch()}
              />
            )}

            {activeTab === "workspace" && (
              <WorkspaceTab teams={teams.data ?? []} onError={onError} onSuccess={onSuccess} />
            )}

            {activeTab === "teams" && (
              <TeamsTab
                onError={onError}
                onSuccess={onSuccess}
                onChanged={() => void teams.refetch()}
              />
            )}

            {activeTab === "settings" && (
              <SettingsTab
                userEmail={user?.email ?? ""}
                isSuperuser={Boolean(user?.is_superuser)}
                onError={onError}
                onSuccess={onSuccess}
                onLogout={signOut}
              />
            )}
          </div>
        )}
      </div>

      {/* Toasts are positioned against the shell surface, not the viewport, so
          they stay inside the rounded frame. */}
      <div className="pointer-events-none absolute right-4 top-20 z-50 flex flex-col gap-2">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            role="status"
            className="glass toast-in pointer-events-auto flex max-w-[calc(100vw-2rem)] items-center gap-2.5 rounded-2xl px-4 py-2.5 text-[12px] font-medium sm:max-w-sm sm:rounded-full"
          >
            {toast.type === "success" && (
              <CheckCircle size={14} style={{ color: "var(--success)" }} />
            )}
            {toast.type === "error" && <AlertCircle size={14} style={{ color: "var(--danger)" }} />}
            {toast.type === "info" && <Info size={14} style={{ color: "var(--info)" }} />}
            <span style={{ color: "var(--text)" }}>{toast.message}</span>
          </div>
        ))}
      </div>
    </AppShell>
  );
}
