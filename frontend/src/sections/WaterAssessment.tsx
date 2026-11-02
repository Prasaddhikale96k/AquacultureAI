import { useCallback, useEffect, useState } from "react";
import { Pencil } from "lucide-react";
import type { CombinedAssessment, InputSource, WaterConfig, WaterPayload, WaterRecord } from "../types";
import { backendConfigured, getCombinedAssessment, getWaterConfig, getWaterHistory, submitWaterReading } from "../services/api";
import { Badge, Panel } from "../components/ui";
import WaterForm from "./WaterForm";
import AssessmentReport from "./AssessmentReport";
import AiAdvisor from "./AiAdvisor";

const SOURCE: Record<InputSource, string> = { manual: "Manual", sensor: "Sensor", imported_historical: "Historical (imported)" };

export default function WaterAssessment({ jobId, notify }: { jobId: string | null; notify: (k: "success" | "error" | "info", m: string) => void }) {
  const [config, setConfig] = useState<WaterConfig | null>(null);
  const [tanks, setTanks] = useState<string[]>([]);
  const [tank, setTank] = useState("");
  const [history, setHistory] = useState<WaterRecord[]>([]);
  const [combined, setCombined] = useState<CombinedAssessment | null>(null);
  const [editing, setEditing] = useState<WaterRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async (t: string) => {
    setLoading(true); setError(null);
    try {
      const h = await getWaterHistory(t || undefined);
      setTanks(h.tanks); setHistory(h.readings);
      setCombined(t ? await getCombinedAssessment(t, jobId) : null);
    } catch (e) { setError(`Could not load the assessment: ${(e as Error).message}`); }
    finally { setLoading(false); }
  }, [jobId]);

  useEffect(() => { if (backendConfigured) getWaterConfig().then(setConfig, (e) => setError(`Backend unavailable: ${(e as Error).message}`)); }, []);
  useEffect(() => { if (backendConfigured) void refresh(tank); }, [refresh, tank]);

  async function onSubmit(p: WaterPayload) {
    const res = await submitWaterReading(p);
    setEditing(null); setTank(res.reading.tankId);
    await refresh(res.reading.tankId);
    notify("success", `Saved and assessed: ${res.assessment.waterRisk.replace(/_/g, " ")}.`);
  }

  return (
    <Panel id="assessment" title="Water Quality Input & Assessment"
      subtitle="Enter measured values to get a rule-based screening with checks and suggested actions"
      action={<Badge tone="warn">Rule-based · not a validated predictive model</Badge>}>
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <div className="space-y-4">
          <WaterForm config={config} tanks={tanks} editing={editing} defaultTank={tank} onSubmit={onSubmit} onCancelEdit={() => setEditing(null)}
            disabledReason={backendConfigured ? undefined : "Backend not connected (demo mode): measurements cannot be saved or assessed. Nothing is calculated in the browser."} />
          <section aria-label="Saved measurements">
            <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-mute">Saved readings{tank ? ` · ${tank}` : ""}</h3>
            {history.length === 0 ? <p className="text-xs text-mute">{tank ? "No readings saved for this tank." : "Select or enter a tank ID, then save a reading."}</p> : (
              <ul className="max-h-48 space-y-1.5 overflow-auto pr-1">
                {history.map((r) => (
                  <li key={r.id} className={`flex items-center gap-2 rounded-lg border border-line/60 bg-surface/40 p-2 text-[11px] ${r.superseded ? "opacity-60" : ""}`}>
                    <div className="min-w-0 flex-1">
                      <p className="truncate">{new Date(r.timestamp).toLocaleString()} · {Object.keys(r.measurements).join(", ")}</p>
                      <p className="text-mute">{SOURCE[r.source]}{r.superseded ? " · superseded by a correction" : ""}</p>
                    </div>
                    {!r.superseded && <button aria-label="Edit this reading" onClick={() => setEditing(r)} className="grid h-7 w-7 place-items-center rounded-md text-mute hover:text-white"><Pencil className="h-3.5 w-3.5" /></button>}
                  </li>
                ))}
              </ul>
            )}
            {tanks.length > 1 && (
              <div className="mt-2 flex flex-wrap gap-1.5" aria-label="Tanks">
                {tanks.map((t) => <button key={t} onClick={() => setTank(t)} className={`rounded-full border px-2 py-0.5 text-[11px] ${t === tank ? "border-cyan text-cyan" : "border-line text-mute"}`}>{t}</button>)}
              </div>
            )}
          </section>
        </div>
        <div aria-live="polite" className="space-y-3">
          {backendConfigured
            ? <AssessmentReport c={combined} loading={loading} error={error} />
            : <p className="rounded-xl border border-line/70 bg-surface/40 p-4 text-sm text-mute">Connect the backend to see assessments. Demo mode shows no assessment, so no result is invented.</p>}
          {backendConfigured && <AiAdvisor tankId={tank} jobId={jobId} />}
        </div>
      </div>
    </Panel>
  );
}
