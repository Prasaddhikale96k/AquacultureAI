import { AlertTriangle, CheckCircle2, Info, XCircle, type LucideIcon } from "lucide-react";
import type { AnalysisResult, Observation } from "../types";
import { Badge, Panel } from "../components/ui";

const SEVERITY: Record<Observation["severity"], { icon: LucideIcon; color: string; border: string }> = {
  ok: { icon: CheckCircle2, color: "text-ok", border: "border-l-ok" },
  info: { icon: Info, color: "text-cyan", border: "border-l-cyan" },
  warning: { icon: AlertTriangle, color: "text-warn", border: "border-l-warn" },
  error: { icon: XCircle, color: "text-bad", border: "border-l-bad" },
};

/** Observations come from the backend, or are derived strictly from reported quality flags. Nothing is invented. */
function derive(r: AnalysisResult): Observation[] {
  const out: Observation[] = [];
  const d = r.detections;
  if (d?.reliable === false) out.push({ category: "Detection Quality", severity: "warning", kind: "measured", title: "Detections not reliable",
    detail: d.reasons?.[0] ?? "Detections failed quality checks for this video." });
  if (d?.framesWithoutDetection) out.push({ category: "Detection Quality", severity: "info", kind: "measured", title: "Frames without detections",
    detail: `${d.framesWithoutDetection} frames had no detected fish.` });
  if (!r.tracking) out.push({ category: "Tracking Quality", severity: "info", kind: "measured", title: "Tracking not run",
    detail: r.warnings?.[0] ?? "No tracking metrics were reported for this video." });
  if (r.tracking) out.push({ category: "Tracking Quality", severity: r.tracking.reliable ? "ok" : "warning", kind: "measured",
    title: r.tracking.reliable ? "Tracking passed plausibility checks" : "Tracking not reliable",
    detail: r.tracking.reasons?.[0] ?? (r.tracking.reliable ? "No tracking quality flags were reported." : "Individual track speeds should not be interpreted.") });
  if (r.movement) out.push({ category: "Movement Observation", severity: r.movement.reliable ? "ok" : "warning", kind: "measured",
    title: r.movement.reliable ? "Movement metrics passed plausibility checks" : "Movement metrics not reliable",
    detail: r.movement.reasons?.[0] ?? (r.movement.reliable ? "No movement quality flags were reported." : "Camera motion or detection quality limits these values.") });
  return out;
}

export default function Observations({ result }: { result: AnalysisResult | null }) {
  const items = result ? (result.observations?.length ? result.observations : derive(result)) : [];
  return (
    <Panel id="insights" title="AI Observations & Alerts" subtitle="Preliminary — not a health diagnosis">
      {items.length === 0 ? (
        <p className="rounded-xl border border-line/70 bg-surface/40 p-4 text-sm text-mute">Not enough reliable data to generate observations.</p>
      ) : (
        <ul className="space-y-2">
          {items.map((o, i) => {
            const s = SEVERITY[o.severity];
            return (
              <li key={i} className={`flex gap-3 rounded-xl border border-line/70 border-l-4 bg-surface/50 p-3 ${s.border}`}>
                <s.icon className={`mt-0.5 h-4 w-4 shrink-0 ${s.color}`} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-sm font-medium">{o.title}</p>
                    <Badge tone={o.kind === "measured" ? "info" : "warn"}>{o.kind === "measured" ? "Measured" : "Preliminary"}</Badge>
                  </div>
                  <p className="text-xs text-mute">{o.detail}</p>
                  <p className="mt-0.5 text-[10px] text-mute">{o.category}{o.timestamp ? ` · ${o.timestamp}` : ""}{o.reliability !== undefined ? ` · reliability ${Math.round(o.reliability * 100)}%` : ""}</p>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
