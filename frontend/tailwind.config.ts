import type { Config } from "tailwindcss";

export default {
  darkMode: ["class", '[data-theme="dark"]'],
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: {
          0: "var(--surface-0)",
          1: "var(--surface-1)",
          2: "var(--surface-2)",
          3: "var(--surface-3)",
        },
        border: {
          subtle: "var(--border-subtle)",
          glass: "var(--border-glass)",
        },
        text: {
          primary: "var(--text-primary)",
          secondary: "var(--text-secondary)",
        },
        accent: {
          DEFAULT: "var(--accent)",
          strong: "var(--accent-strong)",
          highlight: "var(--accent-highlight)",
        },
        severity: {
          success: "var(--success)",
          warn: "var(--warn)",
          critical: "var(--critical)",
          info: "var(--info)",
        },
      },
      borderRadius: {
        card: "12px",
        nested: "8px",
        pill: "999px",
      },
      fontFamily: {
        sans: ["Inter Variable", "Inter", "system-ui", "sans-serif"],
        display: ["Manrope Variable", "Manrope", "system-ui", "sans-serif"],
      },
    },
  },
} satisfies Config;
