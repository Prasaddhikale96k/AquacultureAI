import { useSyncExternalStore } from "react";
import type { AuthUser } from "../types";
import { AUTH_EVENT, AUTH_USER_KEY, authLogout, authMe, getAuthStatus } from "../services/api";

/**
 * Minimal auth store.
 *
 * Deliberately stores NO session token in JS: the session lives in an
 * HttpOnly cookie, and the only client-readable credential is the CSRF
 * double-submit cookie (read by services/api.ts and mirrored in the header).
 * We cache the non-sensitive profile only so the shell can render instantly.
 */
export type AuthMode = "full" | "open" | "unknown";

interface AuthState {
  user: AuthUser | null;
  status: "checking" | "ready";
  mode: AuthMode;
}

function readCachedUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem(AUTH_USER_KEY);
    return raw ? (JSON.parse(raw) as AuthUser) : null;
  } catch {
    return null;
  }
}

let state: AuthState = { user: readCachedUser(), status: "checking", mode: "unknown" };
const listeners = new Set<() => void>();

function emit() {
  for (const listener of listeners) listener();
}

function setState(next: Partial<AuthState>) {
  state = { ...state, ...next };
  emit();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot() {
  return state;
}

/** Persist the non-sensitive profile so a reload does not flash the login page. */
export function setAuthUser(user: AuthUser | null, persist = true) {
  setState({ user, status: "ready" });
  try {
    if (user && persist) localStorage.setItem(AUTH_USER_KEY, JSON.stringify(user));
    else localStorage.removeItem(AUTH_USER_KEY);
  } catch {
    /* storage unavailable: session cookie still works */
  }
}

let bootstrapPromise: Promise<void> | null = null;

/**
 * Resolve authentication once per page load.
 * `AQUA_AUTH_MODE=open` is honoured here: the backend reports it on the
 * public /api/auth/status endpoint, and the UI skips the gate entirely so the
 * one-line rollback restores today's no-login behaviour.
 */
export function bootstrapAuth(): Promise<void> {
  if (bootstrapPromise) return bootstrapPromise;
  bootstrapPromise = (async () => {
    let mode: AuthMode = "unknown";
    try {
      const status = await getAuthStatus();
      if (status.auth_mode === "open" || status.auth_mode === "full") mode = status.auth_mode;
    } catch {
      /* status is informational; fall through to a real session check */
    }

    if (mode === "open") {
      setState({ user: { name: "Farmer" }, status: "ready", mode });
      return;
    }

    const current = await authMe();
    if (current) {
      setAuthUser(current);
    } else {
      setAuthUser(null);
    }
    setState({ mode });
  })();
  return bootstrapPromise;
}

export async function logout() {
  await authLogout();
  setAuthUser(null);
}

if (typeof window !== "undefined") {
  // 401 from any API call: drop the local profile immediately.
  window.addEventListener(AUTH_EVENT, () => setAuthUser(null));
}

export function useAuth() {
  const snapshot = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  return {
    ...snapshot,
    isAuthenticated: snapshot.user !== null,
    setUser: setAuthUser,
    logout,
  };
}
