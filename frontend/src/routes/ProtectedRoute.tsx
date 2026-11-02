import type { ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { useAuth } from "../state/authStore";
import { useT } from "../i18n/LanguageProvider";

export function SessionLoader() {
  const t = useT();
  return (
    <div className="grid min-h-screen place-items-center bg-[var(--surface-0)]">
      <p className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        {t("auth.sessionChecking")}
      </p>
    </div>
  );
}

/**
 * Client-side gate. The server is still the source of truth: every /api/*
 * call is CSRF-protected and returns 401 without a session cookie.
 */
export function ProtectedRoute({ children, fallback = null }: { children: ReactNode; fallback?: ReactNode }) {
  const { user, status } = useAuth();
  if (status === "checking") return <SessionLoader />;
  if (!user) return <>{fallback}</>;
  return <>{children}</>;
}
