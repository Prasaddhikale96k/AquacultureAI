import type { ReactNode } from "react";
import { Fish } from "lucide-react";
import { AuthHeroPanel } from "./AuthHeroPanel";
import { AppearanceControls } from "../shared/AppearanceControls";
import { useT } from "../../i18n/LanguageProvider";

/** Split-screen shell shared by Login and Register. */
export function AuthLayout({ children }: { children: ReactNode }) {
  const t = useT();

  return (
    <div className="min-h-screen bg-[var(--surface-0)] lg:grid lg:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)]">
      <div className="hidden lg:sticky lg:top-0 lg:block lg:h-screen">
        <AuthHeroPanel />
      </div>

      <div className="relative flex min-h-screen flex-col">
        <header className="flex items-center justify-between gap-3 px-5 py-5 sm:px-8">
          <a href="#/overview" className="flex items-center gap-2.5 text-[var(--text-primary)]">
            <span className="grid h-9 w-9 place-items-center rounded-xl bg-[var(--accent)]/12 text-[var(--accent)]">
              <Fish className="h-5 w-5" aria-hidden />
            </span>
            <span className="font-display text-base font-semibold tracking-tight">
              Aquaculture<span className="text-[var(--accent)]">AI</span>
            </span>
          </a>
          <AppearanceControls compact />
        </header>

        <main className="flex flex-1 items-center justify-center px-4 pb-8 sm:px-8">{children}</main>

        <footer className="px-6 pb-6 text-center text-[11px] leading-relaxed text-[var(--text-secondary)]">
          {t("auth.terms")}
        </footer>
      </div>
    </div>
  );
}
