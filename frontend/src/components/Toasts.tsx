import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, Info, X } from "lucide-react";

export interface ToastItem { id: number; kind: "success" | "error" | "info"; message: string }
const ICON = { success: CheckCircle2, error: AlertTriangle, info: Info };
const COLOR = { success: "text-ok", error: "text-bad", info: "text-cyan" };

export default function Toasts({ items, dismiss }: { items: ToastItem[]; dismiss: (id: number) => void }) {
  return (
    <div className="fixed bottom-4 right-4 z-50 flex w-[min(92vw,380px)] flex-col gap-2" role="status" aria-live="polite">
      <AnimatePresence>
        {items.map((t) => {
          const Icon = ICON[t.kind];
          return (
            <motion.div key={t.id} layout initial={{ opacity: 0, x: 40 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 40 }}
              className="glass flex items-start gap-2 rounded-xl p-3 text-sm">
              <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${COLOR[t.kind]}`} />
              <p className="flex-1">{t.message}</p>
              <button aria-label="Dismiss notification" onClick={() => dismiss(t.id)} className="text-mute hover:text-white"><X className="h-4 w-4" /></button>
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}
