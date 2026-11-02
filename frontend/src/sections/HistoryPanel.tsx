import { useCallback, useEffect, useState } from "react";
import type { HistoryRecord } from "../types";
import { backendConfigured, getHistory } from "../services/api";
import { Badge, Panel } from "../components/ui";

const EVENT_LABEL: Record<string, string> = {
  video_analysis: "Video analysis", water_reading: "Water reading",
  explanation: "AI explanation", risk_assessment: "Risk assessment",
};

/** Section F — persistent event history (backend/history.jsonl), newest first. */
export default function HistoryPanel() {
  const [records, setRecords] = useState<HistoryRecord[]>([]);
  const [filter, setFilter] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const h = await getHistory(50, filter || undefined);
      setRecords(h.records);
      setError(null);
    } catch (e) { setError((e as Error).message); }
  }, [filter]);

  useEffect(() => { if (backendConfigured) void refresh(); }, [refresh]);

  const describe = (r: HistoryRecord): string => {
    switch (r.event) {
      case "video_analysis":
        return `${String(r.video_name ?? "video")} · ${String(r.backend ?? "?")} · ${String(r.status ?? "?")}` +
          (r.detections_mean !== undefined ? ` · ${r.detections_mean} detections/frame` : "");
      case "water_reading":
        return `Tank ${String(r.tank_id ?? "?")} · water risk ${String(r.water_risk ?? "?")}`;
      case "explanation":
        return `Tank ${String(r.tank_id ?? "?")} · ${String(r.status ?? "?")} · ${String(r.provider ?? "?")}`;
      case "risk_assessment":
        return `Tank ${String(r.tank_id ?? "?")} · ${String(r.status ?? "?")}`;
      default:
        return String(r.status ?? r.event);
    }
  };

  return (
    <Panel id="event-history" title="Event History" subtitle="Persistent backend records — timestamps, evidence outcome, engine version"
      action={<button onClick={() => void refresh()} className="rounded-lg border border-line px-2 py-1 text-[11px] text-mute hover:text-white">Refresh</button>}>
      {!backendConfigured ? (
        <p className="text-sm text-mute">Connect the backend to see event history.</p>
      ) : error ? (
        <p role="alert" className="text-sm text-bad">{error}{/404/.test(error) &&
          " The running backend may predate the history route: restart it with `python -m uvicorn backend.main:app` from the project root."}</p>
      ) : records.length === 0 ? (
        <p className="text-sm text-mute">No events recorded yet. Analyse a video or save a water reading.</p>
      ) : (
        <>
          <div className="mb-2 flex flex-wrap gap-1.5" aria-label="Filter by event">
            {["", "video_analysis", "water_reading", "explanation", "risk_assessment"].map((e) => (
              <button key={e} onClick={() => setFilter(e)}
                className={`rounded-full border px-2 py-0.5 text-[11px] ${filter === e ? "border-cyan text-cyan" : "border-line text-mute"}`}>
                {e === "" ? "All" : EVENT_LABEL[e] ?? e}
              </button>
            ))}
          </div>
          <ul className="max-h-64 space-y-1.5 overflow-auto pr-1">
            {records.map((r, i) => (
              <li key={`${r.ts}-${i}`} className="flex items-center gap-2 rounded-lg border border-line/60 bg-surface/40 p-2 text-[11px]">
                <div className="min-w-0 flex-1">
                  <p className="truncate">{describe(r)}</p>
                  <p className="text-mute">{new Date(r.ts).toLocaleString()}</p>
                </div>
                <Badge tone={r.status === "failed" ? "bad" : r.status === "completed" || r.status === "generated" ? "ok" : "mute"}>
                  {EVENT_LABEL[String(r.event)] ?? String(r.event)}
                </Badge>
              </li>
            ))}
          </ul>
        </>
      )}
    </Panel>
  );
}
