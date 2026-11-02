import { useEffect, useState } from "react";
import { Area, AreaChart, ResponsiveContainer, Tooltip, YAxis } from "recharts";
import { AlertTriangle, Droplets, FlaskConical, Thermometer, Waves, Wind, type LucideIcon } from "lucide-react";
import type { WaterReading } from "../types";
import { getWaterQuality } from "../services/api";
import { Panel, Skeleton, SourceBadge } from "../components/ui";

const ICONS: Record<WaterReading["key"], LucideIcon> = { temperature: Thermometer, turbidity: Waves, pH: FlaskConical, do: Wind };

function rangeText(r: WaterReading) {
  if (!r.range || (r.range.min === null && r.range.max === null)) return null;
  const { min, max } = r.range;
  const body = min !== null && max !== null ? `${min}–${max}` : min !== null ? `≥ ${min}` : `≤ ${max}`;
  return `Reference ${body} ${r.unit} (provisional)`;
}

function Card({ r }: { r: WaterReading }) {
  const Icon = ICONS[r.key];
  const measured = r.value !== undefined && r.source !== "unavailable";
  return (
    <li className="rounded-xl border border-line/70 bg-surface/50 p-3">
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1.5 text-xs text-mute"><Icon className="h-3.5 w-3.5 text-cyan" />{r.label}</span>
        <SourceBadge source={r.source} />
      </div>
      <p className="mt-1 text-xl font-semibold">
        {measured ? r.value : <span className="text-base text-mute">Not measured</span>}
        {measured && r.unit && <span className="ml-1 text-xs font-normal text-mute">{r.unit}</span>}
      </p>
      {r.series.length > 1 && (
        <div className="h-10" aria-label={`${r.label} trend`}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={r.series} margin={{ top: 2, bottom: 0, left: 0, right: 0 }}>
              <YAxis hide domain={["dataMin", "dataMax"]} />
              <Tooltip contentStyle={{ background: "#09253a", border: "1px solid #15476a", borderRadius: 8, fontSize: 11 }} labelStyle={{ color: "#8fb0c9" }}
                formatter={(v) => [`${v} ${r.unit}`, r.label]} />
              <Area type="monotone" dataKey="v" stroke="#19c8f2" fill="#19c8f2" fillOpacity={0.15} strokeWidth={1.5} isAnimationActive={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
      <p className="mt-1 truncate text-[10px] text-mute" title={r.timestamp}>{r.timestamp ? `${r.timestamp}` : "No timestamp"}</p>
      {rangeText(r) && <p className="truncate text-[10px] text-mute">{rangeText(r)}</p>}
    </li>
  );
}

export default function WaterQuality() {
  const [state, setState] = useState<{ readings: WaterReading[]; live: boolean } | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => { getWaterQuality().then(setState, () => setError(true)); }, []);

  return (
    <Panel id="water-quality" title="Water Quality Monitoring" subtitle={state?.live ? "Live sensor readings" : "No live sensor connected"}
      action={<Droplets className="h-4 w-4 text-cyan" />}>
      {error ? (
        <p role="alert" className="flex items-center gap-2 text-sm text-bad"><AlertTriangle className="h-4 w-4" />Could not load water-quality data.</p>
      ) : !state ? (
        <div className="grid grid-cols-2 gap-3">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-28" />)}</div>
      ) : (
        <>
          <ul className="grid grid-cols-2 gap-3">{state.readings.map((r) => <Card key={r.key} r={r} />)}</ul>
          {!state.live && (
            <p className="mt-3 text-[11px] text-mute">
              Values are from the project's historical Tilapia-RAS metadata (latest record shown), not live readings.
              Reference ranges are provisional screening thresholds; no safe/unsafe judgement is made here.
            </p>
          )}
        </>
      )}
    </Panel>
  );
}
