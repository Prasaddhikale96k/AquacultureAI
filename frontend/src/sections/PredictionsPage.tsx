import { useCallback, useEffect, useState } from "react";
import { RefreshCw, Thermometer, TrendingUp, TriangleAlert, Waves } from "lucide-react";
import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { backendConfigured, getPredictions } from "../services/api";
import type { ForecastPoint, Predictions } from "../types";
import { Badge } from "../components/ui";

const LEVEL_EN = (v?: string | null) => ((v ?? "").toUpperCase() === "HIGH" ? "High" : (v ?? "").toUpperCase() === "MEDIUM" ? "Medium" : (v ?? "").toUpperCase() === "LOW" ? "Low" : "Insufficient data");
const TONE = (v?: string | null): "ok" | "warn" | "bad" | "mute" => {
  const x = (v ?? "").toUpperCase();
  return x === "HIGH" ? "bad" : x === "MEDIUM" ? "warn" : x === "LOW" ? "ok" : "mute";
};

function ForecastCard({ kind, title, unit, status, points, last, mae, n, note, totalEntries }: {
  kind: "temperature" | "turbidity"; title: string; unit: string; status: string; points: ForecastPoint[];
  last?: { t: number; iso: string; value: number }; mae: number | null; n: number; note: string;
  totalEntries?: number;
}) {
  const end = points.at(-1);
  return (
    <section aria-label={`${title} forecast`} className="rounded-2xl border border-line bg-[var(--surface-1)] p-4 shadow-sm">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h2 className="flex items-center gap-1.5 text-[15px] font-semibold text-ink">
            {kind === "temperature" ? <Thermometer className="h-4 w-4 text-cyan" /> : <Waves className="h-4 w-4 text-cyan" />}{title}
          </h2>
          <p className="mt-0.5 text-[11px] text-mute">
            Next 6 hours · PROVISIONAL · {totalEntries ? `analyzed all ${totalEntries} ThingSpeak entries` : "not a guaranteed value"}
          </p>
        </div>
        <Badge tone={status === "ok" ? "info" : "mute"}>{status === "ok" ? "Forecast ready" : "Insufficient data"}</Badge>
      </div>
      {status === "ok" && end ? (
        <>
          <div className="mt-3 flex flex-wrap items-end justify-between gap-2">
            <p className="text-3xl font-bold text-ink">
              {kind === "temperature" ? end.value.toFixed(1) : Math.round(end.value)}
              <span className="ml-1 text-xs font-medium text-mute">{unit}</span>
            </p>
            <p className="text-[11px] text-mute">range {kind === "temperature" ? `${end.low.toFixed(1)}–${end.high.toFixed(1)}` : `${Math.round(end.low)}–${Math.round(end.high)}`} {unit} · backtest MAE {mae ?? "—"} (n={n})</p>
          </div>
          <div className="mt-2 h-36" aria-label={`${title} forecast chart`}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={points} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                <XAxis dataKey="t" type="number" scale="time" domain={["dataMin", "dataMax"]} tick={{ fontSize: 10, fill: "#566f83" }} tickFormatter={(t: number) => new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} />
                <YAxis width={38} domain={["auto", "auto"]} tick={{ fontSize: 10, fill: "#566f83" }} />
                <Tooltip contentStyle={{ background: "#09253a", border: "none", borderRadius: 8, fontSize: 12, color: "#fff" }} labelFormatter={(t) => new Date(Number(t) * 1000).toLocaleString()} formatter={(v, name) => [typeof v === "number" ? (kind === "temperature" ? v.toFixed(2) : Math.round(v)) : "—", name === "value" ? "Forecast" : name === "low" ? "Low" : "High"]} />
                <Area type="monotone" dataKey="high" stroke="none" fill="#4a9be3" fillOpacity={0.12} isAnimationActive={false} />
                <Area type="monotone" dataKey="low" stroke="none" fill="#ffffff" fillOpacity={1} isAnimationActive={false} />
                <Area type="monotone" dataKey="value" stroke="#0e8aa8" fill="none" strokeWidth={2} isAnimationActive={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-1 flex flex-wrap items-center justify-between gap-1 text-[11px] text-mute">
            <span>{note}</span>
            {totalEntries ? <span className="font-medium text-cyan">{totalEntries} entries synced</span> : null}
          </div>
        </>
      ) : (
        <p className="mt-3 text-sm text-mute">{note}</p>
      )}
      {last && <p className="mt-1 text-[11px] text-mute">Last measured: {new Date(last.t * 1000).toLocaleString()}</p>}
    </section>
  );
}

export default function PredictionsPage() {
  const [p, setP] = useState<Predictions | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    if (!backendConfigured) { setErr("Backend not configured (VITE_API_BASE_URL)."); return; }
    setBusy(true);
    try { setP(await getPredictions()); setErr(null); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  const dawn = p?.dawn_risk;

  return (
    <div className="flex flex-col gap-4">
      {err && <p role="status" className="rounded-xl border border-warn/40 bg-warn/10 p-3 text-sm text-warn">{err}</p>}
      <div className="flex flex-wrap items-center gap-2">
        <button onClick={() => void load()} disabled={busy} className="inline-flex h-9 items-center gap-2 rounded-lg border border-line bg-[var(--surface-1)] px-3 text-sm text-ink hover:bg-surface disabled:opacity-50">
          <RefreshCw className={`h-4 w-4 ${busy ? "animate-spin" : ""}`} />Refresh forecasts
        </button>
        <Badge tone="warn">EXPERIMENTAL</Badge>
        <Badge tone="mute">Refuses to forecast when data is insufficient</Badge>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {p ? (
          <>
            <ForecastCard kind="temperature" title="Temperature forecast" unit="°C" status={p.temperature.status}
              points={p.temperature.points} last={p.temperature.last} mae={p.temperature.backtest.mae} n={p.temperature.backtest.n} note={p.temperature.note}
              totalEntries={p.temperature.total_entries_analyzed} />
            <ForecastCard kind="turbidity" title="Turbidity forecast (raw ADC)" unit="RAW" status={p.turbidity.status}
              points={p.turbidity.points} last={p.turbidity.last} mae={p.turbidity.backtest.mae} n={p.turbidity.backtest.n} note={p.turbidity.note}
              totalEntries={p.turbidity.total_entries_analyzed} />
          </>
        ) : <p className="text-sm text-mute">Loading forecasts…</p>}
      </div>

      <section aria-label="Dawn oxygen risk" className="rounded-2xl border border-line bg-[var(--surface-1)] p-4 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="flex items-center gap-1.5 text-[15px] font-semibold text-ink"><TriangleAlert className="h-4 w-4 text-warn" />Dawn oxygen risk</h2>
            <p className="mt-0.5 text-[11px] text-mute">Daily peak-risk window near 04:30 · proxy from temperature and turbidity, no DO sensor</p>
          </div>
          <Badge tone={TONE(dawn?.level)}>{LEVEL_EN(dawn?.level)}</Badge>
        </div>
        <p className="mt-3 text-sm text-ink">{dawn?.score != null ? `Score ${dawn.score.toFixed(2)} / 1.00` : "Cannot compute yet — needs 7 days of continuous sensor data."}</p>
        {dawn?.components && (
          <ul className="mt-2 grid grid-cols-1 gap-2 text-[11px] text-mute sm:grid-cols-3">
            <li className="rounded-lg border border-line bg-surface/50 p-2">Temperature saturation drop: <b className="text-ink">{dawn.components.temperature_saturation_drop?.toFixed(2) ?? "—"}</b></li>
            <li className="rounded-lg border border-line bg-surface/50 p-2">Turbidity diurnal swing: <b className="text-ink">{dawn.components.turbidity_diurnal_swing?.toFixed(2) ?? "—"}</b></li>
            <li className="rounded-lg border border-line bg-surface/50 p-2">Turbidity 24 h rise: <b className="text-ink">{dawn.components.turbidity_24h_rise?.toFixed(2) ?? "—"}</b></li>
          </ul>
        )}
        <p className="mt-2 text-[11px] text-mute">{dawn?.disclaimer ?? "Experimental proxy only. It cannot replace a dissolved-oxygen meter."}</p>
      </section>

      <section aria-label="Robust anomalies" className="rounded-2xl border border-line bg-[var(--surface-1)] p-4 shadow-sm">
        <h2 className="flex items-center gap-1.5 text-[15px] font-semibold text-ink"><TrendingUp className="h-4 w-4 text-cyan" />Recent anomalies</h2>
        <p className="mt-0.5 text-[11px] text-mute">Robust z-score flags on hourly sensor values · PROVISIONAL</p>
        {!p ? <p className="mt-3 text-sm text-mute">Loading…</p> : p.anomalies.fields.every((f) => f.flags.length === 0) ? (
          <p className="mt-3 text-sm text-mute">No robust anomalies in the current window.</p>
        ) : (
          <ul className="mt-3 space-y-1.5 text-xs">
            {p.anomalies.fields.flatMap((f) => f.flags.map((fl, i) => (
              <li key={`${f.field}-${i}`} className="rounded-lg border border-warn/30 bg-warn/5 p-2 text-ink">
                <b>{f.field}</b> · {fl.kind} · value {fl.value} {fl.z != null && <>· z={fl.z.toFixed(2)}</>} {fl.iso && <span className="text-mute">· {new Date(fl.iso).toLocaleString()}</span>}
              </li>
            )))}
          </ul>
        )}
        <p className="mt-2 text-[11px] text-mute">{p?.note ?? ""}</p>
      </section>
    </div>
  );
}
