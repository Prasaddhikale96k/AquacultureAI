import type { Sensors } from "../hooks/useSensors";
import { HistoryCards, MetricCards, PipelineCard } from "./LiveSensors";
import WaterQuality from "./WaterQuality";

export default function SensorsPage({ s }: { s: Sensors }) {
  return (
    <div className="flex flex-col gap-4">
      <p className="rounded-xl border border-line bg-[var(--surface-1)] p-3 text-[11px] text-mute">
        Read-only sensor mirror. Turbidity is raw ADC (not NTU). Staleness uses the newest valid measurement, never the last fetch attempt.
      </p>
      <MetricCards s={s} />
      <PipelineCard s={s} />
      <WaterQuality />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <HistoryCards s={s} />
      </div>
    </div>
  );
}
