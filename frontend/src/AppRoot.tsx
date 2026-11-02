import { Suspense, lazy, useEffect, useState } from "react";
import { ThemeProvider } from "./theme/ThemeProvider";
import { LanguageProvider } from "./i18n/LanguageProvider";
import { ToastProvider } from "./components/ui/Toast";
import App from "./App";

/**
 * Root composition + the VITE_UI_THEME rollback switch (AMENDMENTS A2/A3).
 *
 * - default `v2` renders the rebuilt application tree.
 * - `legacy` lazy-loads the frozen pre-rebuild snapshot in src/legacy/.
 *   Rollback is one env line, and the legacy chunk never ships in the
 *   default bundle because it is behind React.lazy + dynamic import().
 */
const LegacyApp = lazy(() => import("./legacy/LegacyApp"));
const DesignSystem = lazy(() => import("./pages/dev/DesignSystem"));

const UI_THEME = (import.meta.env.VITE_UI_THEME as string | undefined) ?? "v2";

function useHashRoute(): string {
  const [hash, setHash] = useState(() => (typeof window === "undefined" ? "" : window.location.hash));
  useEffect(() => {
    const onChange = () => setHash(window.location.hash);
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return hash.replace(/^#\/?/, "");
}

function RouteFallback() {
  return (
    <div className="grid min-h-screen place-items-center bg-[var(--surface-0)]">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-[var(--border-subtle)] border-t-[var(--accent)]" role="status" aria-label="Loading" />
    </div>
  );
}

export default function AppRoot() {
  const route = useHashRoute();
  const devDesignSystem = import.meta.env.DEV && route === "dev/design-system";

  return (
    <ThemeProvider>
      <LanguageProvider>
        <ToastProvider>
          {devDesignSystem ? (
            <Suspense fallback={<RouteFallback />}>
              <DesignSystem />
            </Suspense>
          ) : UI_THEME === "legacy" ? (
            <Suspense fallback={<RouteFallback />}>
              <LegacyApp />
            </Suspense>
          ) : (
            <App />
          )}
        </ToastProvider>
      </LanguageProvider>
    </ThemeProvider>
  );
}
