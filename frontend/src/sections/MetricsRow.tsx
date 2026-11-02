import { motion } from "framer-motion";
import { Activity, Fish, Gauge, Timer, type LucideIcon } from "lucide-react";
import type { AnalysisResult } from "../types";
import type { Phase } from "../hooks/useAnalysis";
import { Badge } from "../components/ui";

interface Card { icon: LucideIcon; label: string; value: string; note: string; tone?: "ok" | "bad" | "mute"; chip?: string }

function build(result: AnalysisResult | null, phase: Phase, progress?: number): Card[] {
  const none = "—";
  const hint = phase === "uploading" || phase === "processing" ? "Analysis in progress" : "Run an analysis to see this";
  const d = result?.detections;
  const t = result?.tracking;
  const m = result?.movement;
  const proc = phase === "uploading" ? `Uploading ${Math.round((progress ?? 0) * 100)}%` : phase === "processing" ? "Processing…" : undefined;
  return [
    { icon: Fish, label: "Fish Detections", value: d ? d.meanPerFrame.toFixed(1) : none, tone: d?.reliable === false ? "bad" : "mute",
      note: d ? (d.reliable === false ? `Not reliable · ${d.reasons?.[0] ?? "failed quality checks"}` : `mean per frame${d.min !== undefined && d.max !== undefined ? ` · range ${d.min}–${d.max}` : ""}`) : hint },
    { icon: Activity, label: "Tracking Quality", value: t ? (t.reliable ? "Reliable" : "Not reliable") : result ? "Not run" : none, tone: t ? (t.reliable ? "ok" : "bad") : "mute",
      note: t ? [t.tracks !== undefined && `${t.tracks} tracks`, t.flaggedForReview !== undefined && `${t.flaggedForReview} flagged`].filter(Boolean).join(" · ") || "No details reported" : result ? "Not part of this analysis" : hint },
    { icon: Gauge, label: "Movement Metrics", value: m ? (m.reliable ? "Reliable" : "Not reliable") : none, tone: m ? (m.reliable ? "ok" : "bad") : "mute",
      note: m ? (m.reasons?.[0] ?? (m.reliable ? "Passed plausibility checks" : "Failed plausibility checks")) : hint },
    { icon: Timer, label: "Video Processing", value: proc ?? (result?.processingSec !== undefined ? `${result.processingSec.toFixed(1)} s` : none),
      note: result?.frames !== undefined ? `${result.frames} frames${result.fps ? ` @ ${result.fps.toFixed(2)} fps` : ""}` : proc ? "Please wait" : hint },
  ];
}

export default function MetricsRow({ result, phase, progress }: { result: AnalysisResult | null; phase: Phase; progress?: number }) {
  const cards = build(result, phase, progress);
  return (
    <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Analysis summary">
      {cards.map(({ icon: Icon, label, value, note, tone }, i) => (
        <motion.li key={label} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 + i * 0.07 }}
          whileHover={{ y: -2 }} className="glass flex items-center gap-3 rounded-2xl p-3.5">
          <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-cyan/10 text-cyan"><Icon className="h-5 w-5" /></span>
          <div className="min-w-0">
            <p className="text-xs text-mute">{label}</p>
            <p className={`truncate text-xl font-semibold leading-tight ${tone === "bad" ? "text-bad" : tone === "ok" ? "text-ok" : ""}`}>{value}</p>
            <p className="truncate text-[11px] text-mute" title={note}>{note}</p>
          </div>
          {(value === "Not reliable" || tone === "bad") && <Badge tone="bad">Check</Badge>}
        </motion.li>
      ))}
    </ul>
  );
}
