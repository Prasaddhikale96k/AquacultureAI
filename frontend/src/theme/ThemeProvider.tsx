import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

export type Theme = "dark" | "light";

interface ThemeContextValue {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
}

const THEME_STORAGE_KEY = "aqua:theme";

function resolveInitial(): Theme {
  if (typeof window === "undefined") return defaultTheme();
  // Dev-only QA override so headless screenshot runs can pin a theme
  // without touching the owner's persisted preference.
  if (import.meta.env.DEV) {
    const q = new URLSearchParams(window.location.search).get("theme");
    if (q === "dark" || q === "light") return q;
  }
  // Explicit build-time override (VITE_UI_THEME=legacy) wins over everything.
  const buildOverride = (import.meta.env.VITE_UI_THEME as string | undefined)?.toLowerCase();
  if (buildOverride === "dark" || buildOverride === "light") return buildOverride as Theme;
  // Then the owner's persisted choice.
  const saved = localStorage.getItem(THEME_STORAGE_KEY) as Theme | null;
  if (saved === "dark" || saved === "light") return saved;
  // Then VITE_UI_THEME_DEFAULT, then the OS preference.
  return defaultTheme();
}

function defaultTheme(): Theme {
  const envDefault = (import.meta.env.VITE_UI_THEME_DEFAULT as string | undefined)?.toLowerCase();
  if (envDefault === "dark" || envDefault === "light") return envDefault as Theme;
  if (typeof window !== "undefined" && window.matchMedia) {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  return "light";
}

const ThemeContext = createContext<ThemeContextValue | undefined>(undefined);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(resolveInitial);

  const setTheme = (next: Theme) => {
    setThemeState(next);
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // ignore storage errors
    }
  };

  const toggleTheme = () => {
    setTheme(theme === "dark" ? "light" : "dark");
  };

  useEffect(() => {
    const root = document.documentElement;
    root.setAttribute("data-theme", theme);
    if (theme === "dark") {
      root.classList.add("dark");
      root.classList.remove("light");
    } else {
      root.classList.add("light");
      root.classList.remove("dark");
    }
  }, [theme]);

  return (
    <ThemeContext.Provider value={{ theme, setTheme, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    throw new Error("useTheme must be used within a ThemeProvider");
  }
  return ctx;
}
