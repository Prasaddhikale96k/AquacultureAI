import { useEffect, useRef, useState } from "react";
import { Film, MoreVertical } from "lucide-react";
import type { AnalysisStatus, RecentAnalysis } from "../types";
import { DEMO_RECENT } from "../services/demo";
import { fmtDuration } from "../services/video";
import { Badge, Panel } from "../components/ui";

const STATUS: Record<AnalysisStatus, [string, "ok" | "info" | "bad" | "warn" | "mute"]> = {
  completed: ["Completed", "ok"], processing: ["Processing", "info"], failed: ["Failed", "bad"], needs_review: ["Needs Review", "warn"], not_analyzed: ["Not analyzed", "mute"],
};

function Menu({ row, onOpen, onRemove }: { row: RecentAnalysis; onOpen: () => void; onRemove: () => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  return (
    <div ref={ref} className="relative">
      <button aria-label={`Actions for ${row.filename}`} aria-expanded={open} onClick={() => setOpen((o) => !o)} className="grid h-7 w-7 place-items-center rounded-md text-mute hover:text-white"><MoreVertical className="h-4 w-4" /></button>
      {open && (
        <div role="menu" className="glass absolute right-0 z-10 mt-1 w-40 rounded-lg p-1 text-xs">
          <button role="menuitem" className="block w-full rounded-md px-2 py-1.5 text-left hover:bg-surface" onClick={() => { setOpen(false); onOpen(); }}>
            Go to workspace
          </button>
          <button role="menuitem" className="block w-full rounded-md px-2 py-1.5 text-left hover:bg-surface" onClick={() => { setOpen(false); onRemove(); }}>Remove from list</button>
        </div>
      )}
    </div>
  );
}

export default function RecentAnalyses({ session, onRemove }: {
  session: RecentAnalysis[]; onRemove: (id: string) => void;
}) {
  const showDemo = session.length === 0;
  const rows = showDemo ? DEMO_RECENT : session;

  const open = () => document.getElementById("video-analysis")?.scrollIntoView({ behavior: "smooth" });

  return (
    <Panel id="history" title="Recent Analyses" subtitle={showDemo ? "Sample entries — no history yet" : "Videos loaded in this session"}
      action={showDemo ? <Badge tone="warn">Demo</Badge> : undefined}>
      <ul className="space-y-2">
        {rows.map((r) => {
          const [label, tone] = STATUS[r.status];
          return (
            <li key={r.id} className="flex items-center gap-3 rounded-xl border border-line/70 bg-surface/50 p-2.5">
              <span className="grid h-10 w-14 shrink-0 place-items-center overflow-hidden rounded-md bg-abyss text-mute">
                {r.thumbnailUrl ? <img src={r.thumbnailUrl} alt="" className="h-full w-full object-cover" /> : <Film className="h-4 w-4" />}
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium" title={r.filename}>{r.filename}</p>
                <p className="truncate text-[11px] text-mute">{r.at}{r.durationSec !== undefined ? ` · ${fmtDuration(r.durationSec)}` : ""}</p>
              </div>
              <Badge tone={tone}>{label}</Badge>
              {!showDemo && <Menu row={r} onOpen={open} onRemove={() => onRemove(r.id)} />}
            </li>
          );
        })}
      </ul>
      {showDemo && <p className="mt-3 text-[11px] text-mute">These rows are illustrative only. Videos you load will appear here.</p>}
    </Panel>
  );
}
