import { Moon, Sun } from "lucide-react";
import { useTheme } from "../../theme/ThemeProvider";
import { useT } from "../../i18n/LanguageProvider";

/**
 * Theme switch. English-only product: there is no language toggle.
 * A real <button> with aria-pressed keeps it keyboard and screen-reader safe.
 */
export function AppearanceControls({ compact = false }: { compact?: boolean }) {
  const { theme, toggleTheme } = useTheme();
  const t = useT();

  const nextThemeLabel = theme === "dark" ? t("theme.light") : t("theme.dark");

  return (
    <div className="flex items-center gap-2" role="group" aria-label={t("appearance.group")}>
      <button
        type="button"
        onClick={toggleTheme}
        aria-pressed={theme === "light"}
        aria-label={`${t("theme.toggle")} — ${nextThemeLabel}`}
        title={`${t("theme.toggle")} — ${nextThemeLabel}`}
        className="inline-flex h-9 items-center gap-2 rounded-nested border border-[var(--border-subtle)] bg-[var(--surface-2)] px-2.5 text-xs font-medium text-[var(--text-secondary)] transition-colors hover:bg-[var(--surface-3)] hover:text-[var(--text-primary)]"
      >
        {theme === "dark" ? <Moon className="h-4 w-4" aria-hidden /> : <Sun className="h-4 w-4" aria-hidden />}
        {!compact && <span>{theme === "dark" ? t("theme.dark") : t("theme.light")}</span>}
      </button>
    </div>
  );
}
