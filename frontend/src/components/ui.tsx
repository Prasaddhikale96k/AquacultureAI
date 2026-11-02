import type { ReactNode } from "react";
import { motion } from "framer-motion";
import type { DataSource } from "../types";

type Tone = "ok" | "warn" | "bad" | "info" | "mute";
const TONES: Record<Tone, string> = {
  ok: "bg-ok/15 text-ok border-ok/30",
  warn: "bg-warn/15 text-warn border-warn/30",
  bad: "bg-bad/15 text-bad border-bad/30",
  info: "bg-[var(--info)]/15 text-[var(--info)] border-[var(--info)]/30",
  mute: "bg-surface text-mute border-line",
};

export const Badge = ({ tone = "mute", children }: { tone?: Tone; children: ReactNode }) => (
  <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-medium ${TONES[tone]}`}>{children}</span>
);

const SOURCES: Record<DataSource, [string, Tone]> = {
  live: ["Live", "ok"], historical: ["Historical", "info"], demo: ["Demo", "warn"], unavailable: ["Unavailable", "mute"],
};
export const SourceBadge = ({ source }: { source: DataSource }) => <Badge tone={SOURCES[source][1]}>{SOURCES[source][0]}</Badge>;

export const Panel = ({ id, title, subtitle, action, className = "", children }: {
  id?: string; title: string; subtitle?: string; action?: ReactNode; className?: string; children: ReactNode;
}) => (
  <motion.section id={id} aria-label={title} className={`glass rounded-2xl p-4 ${className}`}
    initial={{ opacity: 0, y: 14 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: "-40px" }} transition={{ duration: 0.4 }}>
    <header className="mb-3 flex items-start justify-between gap-3">
      <div>
        <h2 className="text-[15px] font-semibold leading-tight">{title}</h2>
        {subtitle && <p className="mt-0.5 text-xs text-mute">{subtitle}</p>}
      </div>
      {action}
    </header>
    {children}
  </motion.section>
);

export const Skeleton = ({ className = "" }: { className?: string }) => <div aria-hidden className={`skeleton rounded-lg ${className}`} />;
