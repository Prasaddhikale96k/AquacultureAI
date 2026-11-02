import { motion } from "framer-motion";
import { RotateCw } from "lucide-react";
import { useT } from "../../i18n/LanguageProvider";
import { useReducedMotion } from "../../motion/useReducedMotion";

interface ResendControlProps {
  active: boolean;
  remaining: number;
  total: number;
  epoch: number;
  busy?: boolean;
  onResend: () => void;
}

/**
 * Circular resend cooldown. Framer Motion owns the ring: one linear 30000ms
 * (or server-provided) depletion per cooldown, keyed by the cooldown epoch so
 * a manual resend restarts it cleanly.
 */
export function ResendControl({ active, remaining, total, epoch, busy = false, onResend }: ResendControlProps) {
  const t = useT();
  const reduced = useReducedMotion();

  return (
    <div className="flex items-center gap-3">
      <button
        type="button"
        onClick={onResend}
        disabled={active || busy}
        className="inline-flex items-center gap-2 rounded-nested px-2 py-1 text-xs font-medium text-[var(--accent)] transition-colors hover:text-[var(--accent-strong)] disabled:cursor-not-allowed disabled:text-[var(--text-secondary)]"
      >
        {active ? (
          <span className="relative grid h-8 w-8 place-items-center">
            <svg viewBox="0 0 36 36" className="absolute inset-0 h-full w-full -rotate-90 text-[var(--border-subtle)]" aria-hidden>
              <circle cx="18" cy="18" r="15" fill="none" stroke="currentColor" strokeWidth="2.5" />
              {!reduced && (
                <motion.circle
                  key={epoch}
                  cx="18"
                  cy="18"
                  r="15"
                  fill="none"
                  stroke="var(--accent)"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                  initial={{ pathLength: 1 }}
                  animate={{ pathLength: 0 }}
                  transition={{ duration: total, ease: "linear" }}
                />
              )}
              {reduced && (
                <circle cx="18" cy="18" r="15" fill="none" stroke="var(--accent)" strokeWidth="2.5" opacity="0.35" />
              )}
            </svg>
            <span className="nums text-[10px] font-semibold text-[var(--text-secondary)]">{remaining}</span>
          </span>
        ) : (
          <RotateCw className="h-3.5 w-3.5" aria-hidden />
        )}
        <span>{active ? t("auth.resendIn", { seconds: remaining }) : t("auth.resendNow")}</span>
      </button>
      <span aria-live="polite" className="sr-only">
        {active ? t("auth.resendIn", { seconds: remaining }) : ""}
      </span>
    </div>
  );
}
