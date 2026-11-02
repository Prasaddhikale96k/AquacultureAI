import { motion } from "framer-motion";
import type { Sample } from "../../hooks/useLiveCamera";

const clock = (t: number) => new Date(t).toLocaleTimeString([], { minute: "2-digit", second: "2-digit" });

export default function SessionTimeline({ samples, active }: { samples: Sample[]; active: boolean }) {
  const recent = samples.slice(-18);
  const max = Math.max(1, ...recent.map((s) => s.count));

  return (
    <section aria-label="Session analysis timeline" className="rounded-card border border-[var(--border-subtle)] bg-[var(--surface-1)]/70 p-3">
      <header className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">Analysis timeline</h3>
          <p className="text-[11px] text-[var(--text-secondary)]">Last {recent.length || 0} analyses from this camera session · detections per frame, not unique fish</p>
        </div>
        <span className="text-[11px] text-[var(--text-secondary)]">{samples.length} this session</span>
      </header>
      {recent.length === 0 ? (
        <p className="py-6 text-center text-xs text-[var(--text-secondary)]">{active ? "Collecting the first analysis…" : "No live analyses yet. Start the camera to build a session timeline."}</p>
      ) : (
        <ol className="flex items-end gap-1.5 overflow-x-auto pb-1" style={{ scrollbarWidth: "thin" }}>
          {recent.map((sample, index) => {
            const latest = index === recent.length - 1;
            return (
              <motion.li key={`${sample.t}-${index}`} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                transition={{ delay: Math.min(index * 0.035, 0.4), duration: 0.22 }}
                className={`flex w-12 shrink-0 flex-col items-center gap-1 rounded-nested border px-1 pb-1 pt-1.5 ${latest ? "border-[var(--accent)]/50 bg-[var(--accent)]/5" : "border-transparent"}`}
                title={`${clock(sample.t)} · ${sample.count} detections`}>
                <span className="text-[10px] font-semibold tabular-nums text-[var(--text-primary)]">{sample.count}</span>
                <span aria-hidden className={`w-5 rounded-sm ${latest ? "bg-[var(--accent)]" : "bg-[var(--text-secondary)]/35"}`}
                  style={{ height: `${4 + Math.round((sample.count / max) * 28)}px` }} />
                <time className="text-[10px] tabular-nums text-[var(--text-secondary)]" dateTime={new Date(sample.t).toISOString()}>{clock(sample.t)}</time>
              </motion.li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
