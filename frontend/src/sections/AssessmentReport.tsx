import { AlertTriangle, Info } from "lucide-react";
import type { CombinedAssessment, InputSource, Level, MeasurementAssessment, VideoState } from "../types";
import { Badge } from "../components/ui";

type Tone = "ok" | "warn" | "bad" | "info" | "mute";
const LEVEL: Record<Level, [string, Tone]> = {
  normal: ["Normal", "ok"], warning: ["Warning", "warn"], high_concern: ["High concern", "bad"], critical_concern: ["Critical concern", "bad"],
  insufficient_data: ["Insufficient data", "mute"], not_assessed: ["Not assessed", "mute"],
};
const OVERALL: Record<CombinedAssessment["overallStatus"], [string, Tone]> = {
  action_recommended: ["Action recommended", "bad"], review_recommended: ["Review recommended", "warn"],
  no_rule_triggered: ["No rule triggered (not a safety guarantee)", "info"], insufficient_data: ["Insufficient data", "mute"],
};
const VIDEO: Record<VideoState, [string, Tone]> = {
  reliable: ["Reliable", "ok"], needs_review: ["Needs review", "warn"], unreliable: ["Unreliable", "bad"], unavailable: ["Unavailable", "mute"],
};
const SOURCE: Record<InputSource, string> = { manual: "Manual", sensor: "Sensor", imported_historical: "Historical (imported)" };
const DQ: Record<string, string> = { ok: "", missing: "Not measured", stale: "Stale", invalid: "Invalid", contradictory: "Contradictory" };

function Row({ m }: { m: MeasurementAssessment }) {
  const [lvl, tone] = LEVEL[m.level];
  return (
    <li className="rounded-lg border border-line/60 bg-surface/40 p-2 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{m.label}</span>
        {m.value !== null && <span>{m.enteredValue} {m.enteredUnit === "C" ? "°C" : m.enteredUnit === "F" ? "°F" : m.enteredUnit === "pH" ? "" : m.enteredUnit}</span>}
        <Badge tone={tone}>{lvl}</Badge>
        {DQ[m.dataQuality] && <Badge tone="mute">{DQ[m.dataQuality]}</Badge>}
        {m.source && <Badge tone="info">{SOURCE[m.source]}</Badge>}
        {m.method && <Badge tone="mute">{m.method.replace(/_/g, " ")}</Badge>}
      </div>
      <p className="mt-1 text-mute">{m.message}</p>
      {m.timestamp && <p className="text-[10px] text-mute">Measured {new Date(m.timestamp).toLocaleString()}</p>}
    </li>
  );
}

export default function AssessmentReport({ c, loading, error }: { c: CombinedAssessment | null; loading: boolean; error: string | null }) {
  if (error) return <p role="alert" className="flex items-center gap-2 text-sm text-bad"><AlertTriangle className="h-4 w-4" />{error}</p>;
  if (loading && !c) return <p className="text-sm text-mute">Loading assessment…</p>;
  if (!c || (!c.water && !c.video.available)) {
    return <p className="rounded-xl border border-line/70 bg-surface/40 p-4 text-sm text-mute">No assessment yet. Save water measurements for a tank to see a rule-based screening. Missing measurements are never treated as safe.</p>;
  }
  const w = c.water;
  const [ovText, ovTone] = OVERALL[c.overallStatus];
  const measured = w?.measurements.filter((m) => m.dataQuality !== "missing") ?? [];
  const missing = w?.measurements.filter((m) => m.dataQuality === "missing").map((m) => m.label) ?? [];
  return (
    <div className="space-y-4 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={ovTone}>{ovText}</Badge>
        {w && <Badge tone={w.waterRisk === "no_rule_triggered" ? "info" : w.waterRisk === "insufficient_data" ? "mute" : LEVEL[w.waterRisk][1]}>Water: {w.waterRisk.replace(/_/g, " ")}</Badge>}
        <Badge tone="mute">Data: {w?.dataQuality.status ?? "no water data"}</Badge>
        <Badge tone="warn">Rule-based screening, not a diagnosis</Badge>
      </div>
      {w && <p className="text-xs text-mute">{w.summary}</p>}
      {w?.profile && <p className="text-[11px] text-mute">Rules: {w.profile} · system {w.system.replace(/_/g, " ")}. {w.lifeStageNote}</p>}

      {w && (
        <section aria-label="Observed measurements">
          <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-mute">Observed measurements</h3>
          <ul className="space-y-1.5">{measured.map((m) => <Row key={m.parameter} m={m} />)}</ul>
          {missing.length > 0 && <p className="mt-1.5 text-[11px] text-warn">Not measured: {missing.join(", ")}. Missing data is not evidence of safe conditions.</p>}
        </section>
      )}

      {w && w.concerns.length > 0 && (
        <section aria-label="Potential concerns">
          <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-mute">Potential concerns, checks and actions</h3>
          <ul className="space-y-2">
            {w.concerns.map((m) => (
              <li key={m.parameter} className="rounded-lg border border-warn/30 bg-warn/5 p-2 text-xs">
                <p className="font-medium">{m.label}: {LEVEL[m.level][0]}{m.confirmed === false ? " (single reading, unconfirmed)" : m.confirmed ? ` (repeated ×${m.persistence + 1})` : ""}</p>
                {m.rule && <p className="text-[10px] text-mute">Rule {m.rule.id} · provisional threshold {m.rule.threshold}</p>}
                <p className="mt-1 text-[11px] font-medium text-cyan">Check next</p>
                <ul className="ml-4 list-disc text-mute">{m.check.map((x) => <li key={x}>{x}</li>)}</ul>
                <p className="mt-1 text-[11px] font-medium text-cyan">Suggested action</p>
                <ul className="ml-4 list-disc text-mute">{m.actions.map((x) => <li key={x}>{x}</li>)}</ul>
              </li>
            ))}
          </ul>
          {w.notes.map((n) => <p key={n} className="mt-1.5 text-[11px] text-mute"><Info className="mr-1 inline h-3 w-3" />{n}</p>)}
        </section>
      )}

      <section aria-label="Video evidence">
        <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-mute">Video evidence (reported separately; not used in the water risk)</h3>
        {c.video.available ? (
          <>
            <div className="mb-1.5 flex flex-wrap gap-2">
              {(["detections", "movement", "tracking"] as const).map((k) => { const s = c.video.reliability?.[k] ?? "unavailable"; return <Badge key={k} tone={VIDEO[s][1]}>{k}: {VIDEO[s][0]}</Badge>; })}
            </div>
            <ul className="ml-4 list-disc text-xs text-mute">{c.video.observations?.map((o) => <li key={o}>{o}</li>)}</ul>
          </>
        ) : <p className="text-xs text-mute">{c.video.reason ?? "No analysed video attached."}</p>}
      </section>

      <section aria-label="Uncertainty">
        <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-mute">Uncertainty and limits</h3>
        <ul className="ml-4 list-disc text-xs text-mute">{[...c.crossNotes, ...c.uncertainty].map((u) => <li key={u}>{u}</li>)}</ul>
        {w && <p className="mt-1.5 text-[10px] text-mute">{w.rulesStatus}</p>}
      </section>
    </div>
  );
}
