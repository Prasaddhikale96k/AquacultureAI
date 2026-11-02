import { useCallback, useEffect, useState } from "react";
import { ShieldAlert } from "lucide-react";
import type { RiskDocument, RiskStatus } from "../types";
import { backendConfigured, getRisk, getWaterHistory } from "../services/api";
import { Badge, Panel } from "../components/ui";

const TONE: Record<RiskStatus, "ok" | "warn" | "bad" | "info" | "mute"> = {
  NORMAL: "ok", WATCH: "warn", WARNING: "warn", CRITICAL: "bad", INSUFFICIENT_DATA: "mute",
};
const LABEL: Record<RiskStatus, string> = {
  NORMAL: "Normal", WATCH: "Watch", WARNING: "Warning", CRITICAL: "Critical", INSUFFICIENT_DATA: "Insufficient data",
};

/** Section D — deterministic 5-level operational risk. Domains stay separate; video never drives the level. */
export default function RiskPanel({ jobId }: { jobId: string | null }) {
  const [tanks, setTanks] = useState<string[]>([]);
  const [tank, setTank] = useState("");
  const [doc, setDoc] = useState<RiskDocument | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (backendConfigured) getWaterHistory().then((h) => {
      setTanks(h.tanks);
      if (h.tanks.length && !tank) setTank(h.tanks[0]);
    }, () => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const refresh = useCallback(async () => {
    if (!tank) { setDoc(null); return; }
    try {
      setDoc(await getRisk(tank, jobId));
      setError(null);
    } catch (e) { setError((e as Error).message); }
  }, [tank, jobId]);

  useEffect(() => { if (backendConfigured && tank) void refresh(); }, [refresh, tank]);

  return (
    <Panel id="risk" title="Operational Risk" subtitle="Deterministic 5-level assessment — rule-based, never an LLM label"
      action={doc ? <Badge tone={TONE[doc.status]}>{LABEL[doc.status]}</Badge> : <Badge tone="mute">No assessment</Badge>}>
      {!backendConfigured ? (
        <p className="text-sm text-mute">Connect the backend to compute risk.</p>
      ) : !tank ? (
        <p className="text-sm text-mute">Save water measurements for a tank to compute operational risk.</p>
      ) : error ? (
        <p role="alert" className="text-sm text-bad">{error}</p>
      ) : !doc ? (
        <p className="text-sm text-mute">Loading risk…</p>
      ) : (
        <div className="space-y-3 text-xs">
          {tanks.length > 1 && (
            <div className="flex flex-wrap gap-1.5" aria-label="Tanks">
              {tanks.map((t) => <button key={t} onClick={() => setTank(t)} className={`rounded-full border px-2 py-0.5 text-[11px] ${t === tank ? "border-cyan text-cyan" : "border-line text-mute"}`}>{t}</button>)}
            </div>
          )}
          <div className="flex flex-wrap gap-1.5">
            <Badge tone={doc.domains.water.level ? TONE[doc.domains.water.level] : "mute"}>Water: {doc.domains.water.level ?? "—"} · rule-based</Badge>
            <Badge tone="mute">Behaviour: experimental · not risk-driving</Badge>
            <Badge tone={doc.domains.data_quality.level ? TONE[doc.domains.data_quality.level] : "mute"}>Data: {doc.domains.data_quality.detail}</Badge>
            <Badge tone="mute">Video: {doc.domains.video.available ? "reported separately" : "none attached"}</Badge>
          </div>
          {doc.triggered_rules.length > 0 && (
            <ul className="space-y-1">
              {doc.triggered_rules.map((t, i) => (
                <li key={i} className="rounded-lg border border-line/60 bg-surface/40 p-2">
                  <span className="font-medium">{t.parameter}</span> · {t.level?.replace(/_/g, " ")}
                  {t.confirmed === true ? " · confirmed by repeat reading" : t.confirmed === false ? " · single reading, unconfirmed" : ""}
                  <span className="text-mute"> · rule {t.rule_id} (provisional)</span>
                </li>
              ))}
            </ul>
          )}
          {doc.recommended_checks.length > 0 && (
            <div><p className="mb-1 font-medium text-cyan">Recommended next checks</p>
              <ul className="ml-4 list-disc text-mute">{doc.recommended_checks.map((c) => <li key={c}>{c}</li>)}</ul></div>
          )}
          <ul className="ml-4 list-disc text-mute">{doc.uncertainty.map((u) => <li key={u}>{u}</li>)}</ul>
          <p className="flex items-center gap-1.5 text-[10px] text-mute"><ShieldAlert className="h-3 w-3" />{doc.engine} · evaluated {new Date(doc.evaluated_at).toLocaleString()}</p>
        </div>
      )}
    </Panel>
  );
}
