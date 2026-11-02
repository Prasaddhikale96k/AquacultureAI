import { createContext, useCallback, useContext, type ReactNode } from "react";
import { getTranslation } from "./index";

interface LanguageContextValue {
  t: (key: string, params?: Record<string, string | number>) => string;
}

const LanguageContext = createContext<LanguageContextValue | undefined>(undefined);

/**
 * English-only UI (owner decision, P2). The provider remains so copy stays
 * centralised in en.json and a future locale can be added without touching
 * call sites. There is deliberately no language switch in the product.
 */
export function LanguageProvider({ children }: { children: ReactNode }) {
  const t = useCallback(
    (key: string, params?: Record<string, string | number>) => getTranslation(key, params),
    []
  );

  return <LanguageContext.Provider value={{ t }}>{children}</LanguageContext.Provider>;
}

export function useT() {
  const ctx = useContext(LanguageContext);
  if (!ctx) {
    throw new Error("useT must be used within a LanguageProvider");
  }
  return ctx.t;
}
