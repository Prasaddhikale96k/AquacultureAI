import { type ReactNode } from "react";
import { motion } from "framer-motion";

interface AuthCardProps {
  children: ReactNode;
  className?: string;
  /** When true (default), Framer animates card height/width across step switches. */
  layout?: boolean;
}

/**
 * Glassmorphic auth container (THEME OVERRIDE v2 rationed glass).
 *
 * LIGHT: backdrop-blur(12px) over rgba(255,255,255,0.72) + 1px rgba(255,255,255,0.4) border,
 * solid #FFFFFF fallback when backdrop-filter is unsupported.
 * DARK: rgba(16,24,39,0.6) + rgba(255,255,255,0.08) border, solid #101827 fallback.
 * Mobile: solid --surface-1, no glass blur, no ambient shadow (perf + legibility in bright
 * farm-side light). Desktop: single soft ambient shadow (≤8 px blur, ≤8 % opacity).
 */
export function AuthCard({ children, className = "", layout = true }: AuthCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      layout={layout}
      className={[
        "relative z-10 w-full max-w-lg rounded-card border border-[var(--border-subtle)] p-6 sm:p-7",
        "bg-[var(--surface-1)] lg:bg-transparent lg:glass-auth lg:shadow-sm",
        className,
      ].filter(Boolean).join(" ").trim()}
    >
      {children}
    </motion.div>
  );
}
