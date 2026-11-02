import { createContext, useContext, useState, useCallback, type ReactNode } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { CheckCircle2, AlertTriangle, XCircle, Info, X } from "lucide-react";
import { springSoft } from "../../motion/variants";

export type ToastKind = "ok" | "warn" | "error" | "info";

export interface ToastItem {
  id: string | number;
  kind: ToastKind;
  message: string;
}

interface ToastContextValue {
  toast: (kind: ToastKind, message: string) => void;
  dismiss: (id: string | number) => void;
}

const ToastContext = createContext<ToastContextValue | undefined>(undefined);

const icons = {
  ok: <CheckCircle2 className="h-4 w-4 shrink-0 text-[var(--success)]" />,
  warn: <AlertTriangle className="h-4 w-4 shrink-0 text-[var(--warn)]" />,
  error: <XCircle className="h-4 w-4 shrink-0 text-[var(--critical)]" />,
  info: <Info className="h-4 w-4 shrink-0 text-[var(--info)]" />,
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const dismiss = useCallback((id: string | number) => {
    setItems((prev) => prev.filter((item) => item.id !== id));
  }, []);

  const toast = useCallback((kind: ToastKind, message: string) => {
    const id = `${Date.now()}-${Math.random()}`;
    setItems((prev) => [...prev, { id, kind, message }]);
    setTimeout(() => {
      dismiss(id);
    }, 4500);
  }, [dismiss]);

  return (
    <ToastContext.Provider value={{ toast, dismiss }}>
      {children}
      <div
        aria-live="polite"
        className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm w-full pointer-events-none px-4 sm:px-0"
      >
        <AnimatePresence mode="popLayout">
          {items.map((item) => (
            <motion.div
              key={item.id}
              layout
              initial={{ opacity: 0, y: 16, scale: 0.95 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 10, scale: 0.95 }}
              transition={springSoft}
              className="pointer-events-auto flex items-center justify-between gap-3 p-3 rounded-card bg-[var(--surface-1)] border border-[var(--border-subtle)] shadow-lg text-[var(--text-primary)] text-sm"
            >
              <div className="flex items-center gap-2.5 min-w-0">
                {icons[item.kind]}
                <span className="truncate">{item.message}</span>
              </div>
              <button
                onClick={() => dismiss(item.id)}
                className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] p-1 rounded hover:bg-[var(--surface-2)] transition-colors"
                aria-label="Close notification"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used within a ToastProvider");
  }
  return ctx;
}
