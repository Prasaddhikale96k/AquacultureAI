import { useRef, useState, type DragEvent } from "react";
import { motion } from "framer-motion";
import { CloudUpload, Info, RefreshCw, Trash2, X } from "lucide-react";
import type { VideoMeta } from "../types";
import type { Phase, Stage } from "../hooks/useAnalysis";
import { Badge } from "../components/ui";
import { ACCEPTED_EXT, MAX_UPLOAD_MB, backendConfigured } from "../services/api";
import { fmtDuration, fmtSize } from "../services/video";

const STAGES: Record<Stage, [string, "ok" | "warn" | "bad" | "info" | "mute"] | null> = {
  idle: null, uploading: ["Uploading video", "info"], uploaded: ["Video uploaded", "ok"], queued: ["Analysis queued", "info"],
  running: ["Analysis running", "info"], completed: ["Analysis completed", "ok"], completed_unreliable: ["Completed with unreliable results", "warn"], failed: ["Failed", "bad"],
};

interface Props {
  meta: VideoMeta | null; hasFile: boolean; phase: Phase; stage: Stage; progress?: number; error: string | null;
  onSelect: (f: File) => void; onClear: () => void; onAnalyze: () => void; onCancel: () => void;
}

export default function UploadPanel({ meta, hasFile, phase, stage, progress, error, onSelect, onClear, onAnalyze, onCancel }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const busy = phase === "uploading" || phase === "processing";
  const ready = !backendConfigured || phase === "uploaded" || phase === "done" || (phase === "error" && !!error);
  const chip = STAGES[stage];
  const pick = () => input.current?.click();
  const drop = (e: DragEvent) => {
    e.preventDefault(); setOver(false);
    const f = e.dataTransfer.files[0];
    if (f && !busy) onSelect(f);
  };

  return (
    <div className="flex h-full min-w-0 flex-col">
      <div className="mb-3">
        <h3 className="text-[15px] font-semibold text-[var(--text-primary)]">Video analysis</h3>
        <p className="text-xs text-[var(--text-secondary)]">Upload a video to detect, segment and analyze fish movement</p>
      </div>

      <input ref={input} type="file" accept={ACCEPTED_EXT.join(",") + ",video/*"} className="sr-only" tabIndex={-1} aria-label="Choose a video file"
        onChange={(e) => { const f = e.target.files?.[0]; if (f) onSelect(f); e.target.value = ""; }} />

      {!hasFile ? (
        <motion.div role="button" tabIndex={0} aria-label="Upload a video: drag and drop or press Enter to browse"
          onClick={pick} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), pick())}
          onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)} onDrop={drop}
          animate={{ scale: over ? 1.015 : 1 }}
          className={`flex min-h-[210px] flex-1 cursor-pointer flex-col items-center justify-center rounded-card border-2 border-dashed p-6 text-center transition-colors ${over ? "border-[var(--accent)] bg-[var(--accent)]/10" : "border-[var(--border-subtle)] bg-[var(--surface-2)]/60 hover:border-[var(--accent)]/60"}`}>
          <CloudUpload className="mb-2 h-10 w-10 text-[var(--accent)]" />
          <p className="text-sm font-medium text-[var(--text-primary)]">Drag &amp; drop your video here</p>
          <p className="my-1 text-xs text-[var(--text-secondary)]">or</p>
          <span className="rounded-nested bg-[var(--accent)] px-4 py-1.5 text-sm font-semibold text-[var(--accent-contrast)]">Browse files</span>
          <p className="mt-3 text-[11px] text-[var(--text-secondary)]">{ACCEPTED_EXT.map((e) => e.slice(1).toUpperCase()).join(", ")} · up to {MAX_UPLOAD_MB} MB</p>
        </motion.div>
      ) : (
        <div className="flex min-w-0 flex-1 flex-col rounded-card border border-[var(--border-subtle)] bg-[var(--surface-2)]/60 p-3">
          <div className="flex gap-3">
            <div className="grid h-20 w-32 shrink-0 place-items-center overflow-hidden rounded-nested bg-[var(--surface-0)]">
              {meta?.posterUrl ? <img src={meta.posterUrl} alt="First frame of the selected video" className="h-full w-full object-cover" />
                : <span className="px-2 text-center text-[10px] text-[var(--text-secondary)]">{meta ? "No preview for this format" : "Reading file…"}</span>}
            </div>
            <dl className="min-w-0 flex-1 text-xs">
              <dt className="sr-only">File name</dt><dd className="truncate text-sm font-medium text-[var(--text-primary)]" title={meta?.name}>{meta?.name ?? "…"}</dd>
              <div className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[var(--text-secondary)]">
                <dt>Duration</dt><dd className="text-[var(--text-primary)]">{fmtDuration(meta?.durationSec)}</dd>
                <dt>Resolution</dt><dd className="text-[var(--text-primary)]">{meta?.width ? `${meta.width}×${meta.height}` : "—"}</dd>
                <dt>Size</dt><dd className="text-[var(--text-primary)]">{meta ? fmtSize(meta.sizeBytes) : "—"}</dd>
              </div>
            </dl>
          </div>
          <div className="mt-3 flex gap-2">
            <button onClick={pick} disabled={busy} className="inline-flex items-center gap-1.5 rounded-nested border border-[var(--border-subtle)] px-3 py-1.5 text-xs text-[var(--text-primary)] hover:border-[var(--accent)]/60 disabled:opacity-40"><RefreshCw className="h-3.5 w-3.5" />Replace</button>
            <button onClick={onClear} disabled={busy} className="inline-flex items-center gap-1.5 rounded-nested border border-[var(--border-subtle)] px-3 py-1.5 text-xs text-[var(--text-primary)] hover:border-[var(--critical)]/60 disabled:opacity-40"><Trash2 className="h-3.5 w-3.5" />Remove</button>
          </div>
        </div>
      )}

      {!backendConfigured && (
        <p className="mt-3 flex gap-2 rounded-nested border border-[var(--warn)]/30 bg-[var(--warn)]/10 p-2 text-[11px] text-[var(--warn)]">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />Demo mode: backend not connected. You can load and preview a video locally; AI analysis requires the Python backend.
        </p>
      )}
      {chip && <div className="mt-2" aria-live="polite"><Badge tone={chip[1]}>{chip[0]}</Badge></div>}
      {error && <p role="alert" className="mt-2 rounded-nested border border-[var(--critical)]/30 bg-[var(--critical)]/10 p-2 text-xs text-[var(--critical)]">{error}</p>}

      {busy && (
        <div className="mt-3" aria-live="polite">
          <div className="mb-1 flex justify-between text-xs text-[var(--text-secondary)]">
            <span>{phase === "uploading" ? "Uploading video…" : stage === "queued" ? "Queued — waiting for the server…" : "Analyzing video… (progress is not reported by the server)"}</span>
            {progress !== undefined && <span>{Math.round(progress * 100)}%</span>}
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-[var(--surface-3)]" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress !== undefined ? Math.round(progress * 100) : undefined}>
            {progress !== undefined
              ? <motion.div className="h-full bg-gradient-to-r from-[var(--accent)] to-[var(--accent-strong)]" animate={{ width: `${progress * 100}%` }} />
              : <motion.div className="h-full w-1/3 bg-gradient-to-r from-[var(--accent)] to-[var(--accent-strong)]" animate={{ x: ["-100%", "300%"] }} transition={{ repeat: Infinity, duration: 1.4, ease: "linear" }} />}
          </div>
        </div>
      )}

      {busy ? (
        <button onClick={onCancel} className="mt-3 inline-flex items-center justify-center gap-2 rounded-card border border-[var(--critical)]/40 py-2.5 text-sm font-medium text-[var(--critical)] hover:bg-[var(--critical)]/10">
          <X className="h-4 w-4" />{phase === "uploading" ? "Cancel upload" : "Stop waiting"}
        </button>
      ) : (
        <button onClick={onAnalyze} disabled={!hasFile || !ready}
          className="mt-3 inline-flex items-center justify-center gap-2 rounded-card bg-[var(--accent)] py-2.5 text-sm font-semibold text-[var(--accent-contrast)] transition hover:bg-[var(--accent-strong)] hover:text-white disabled:cursor-not-allowed disabled:opacity-40">
          {phase === "error" && backendConfigured ? "Retry" : "Analyze video"}
        </button>
      )}
    </div>
  );
}
