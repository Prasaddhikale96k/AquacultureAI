import { useEffect, useState, type ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, Fish, ImageOff, Loader2, Maximize2, X } from "lucide-react";
import type { AnalysisResult, VideoMeta } from "../types";
import type { Phase } from "../hooks/useAnalysis";
import { assetUrl } from "../services/api";
import { Badge, Skeleton } from "../components/ui";

type Tab = "original" | "ai";

const Empty = ({ icon, title, hint }: { icon: ReactNode; title: string; hint?: string }) => (
  <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center">
    {icon}<p className="text-sm font-medium text-[var(--text-primary)]">{title}</p>{hint && <p className="max-w-xs text-xs text-[var(--text-secondary)]">{hint}</p>}
  </div>
);

export default function ResultsPanel({ meta, hasFile, phase, result, error }: {
  meta: VideoMeta | null; hasFile: boolean; phase: Phase; result: AnalysisResult | null; error: string | null;
}) {
  const [tab, setTab] = useState<Tab>("original");
  const [zoom, setZoom] = useState(false);
  const busy = phase === "uploading" || phase === "processing";
  const apiMode = result?.visionBackend?.backend === "api";
  const tabs: { id: Tab; label: string }[] = [{ id: "original", label: "Original frame" }, { id: "ai", label: apiMode ? "AI detection (boxes)" : "AI detection & segmentation" }];
  const original = assetUrl(result?.preview?.originalUrl) ?? meta?.posterUrl;
  const annotated = assetUrl(result?.preview?.annotatedUrl);
  const src = tab === "original" ? original : annotated;

  useEffect(() => {
    if (!zoom) return;
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setZoom(false);
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [zoom]);

  let body: ReactNode;
  if (src) body = <img src={src} alt={tab === "original" ? "Original video frame" : "AI-annotated frame returned by the backend"} className="h-full w-full object-contain" />;
  else if (tab === "ai" && busy) body = <div className="relative h-full"><Skeleton className="h-full w-full rounded-none" /><Loader2 className="absolute left-1/2 top-1/2 h-6 w-6 -translate-x-1/2 -translate-y-1/2 animate-spin text-[var(--accent)]" /></div>;
  else if (tab === "ai" && phase === "error") body = <Empty icon={<AlertTriangle className="h-8 w-8 text-[var(--critical)]" />} title="Analysis failed" hint={error ?? undefined} />;
  else if (tab === "ai" && phase === "done") body = <Empty icon={<ImageOff className="h-8 w-8 text-[var(--text-secondary)]" />} title="No annotated frame returned" hint="The backend did not provide a segmentation preview for this video." />;
  else if (tab === "ai" && hasFile) body = <Empty icon={<Fish className="h-8 w-8 text-[var(--accent)]" />} title="No AI detections yet" hint="Run “Analyze video”. Annotated frames appear here only when returned by the backend." />;
  else if (hasFile) body = <Empty icon={<ImageOff className="h-8 w-8 text-[var(--text-secondary)]" />} title="Preview unavailable" hint="This browser cannot decode the selected format to show a frame." />;
  else body = <Empty icon={<Fish className="h-10 w-10 text-[var(--accent)]/60" />} title="No video analyzed yet" hint="Upload a video to see the original frame and the AI detection &amp; segmentation view." />;

  const q = result?.preview;
  const unreliable = [result?.detections, result?.tracking, result?.movement].some((x) => x && x.reliable === false);
  const reasons = [...new Set([...(result?.detections?.reasons ?? []), ...(result?.tracking?.reasons ?? []), ...(result?.movement?.reasons ?? [])])];

  return (
    <div className="flex h-full min-w-0 flex-col">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-[15px] font-semibold text-[var(--text-primary)]">Analysis results</h3>
        <div className="flex flex-wrap items-center gap-2">
          {result?.visionBackend && (
            <Badge tone={result.visionBackend.backend === "api" ? "info" : "mute"}>
              {result.visionBackend.backend === "api"
                ? `API vision · ${result.visionBackend.providers?.[0] ?? "Groq/Gemini"} · boxes only`
                : "YOLO weights"}
            </Badge>
          )}
          <div role="tablist" aria-label="Frame view" className="inline-flex rounded-nested border border-[var(--border-subtle)] bg-[var(--surface-2)] p-0.5 text-xs">
            {tabs.map((t) => (
              <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}
                className={`rounded-md px-3 py-1.5 transition-colors ${tab === t.id ? "bg-[var(--accent)] text-[var(--accent-contrast)]" : "text-[var(--text-secondary)] hover:text-[var(--text-primary)]"}`}>{t.label}</button>
            ))}
          </div>
        </div>
      </div>

      <div className="relative h-[clamp(240px,34vh,340px)] overflow-hidden rounded-card border border-[var(--border-subtle)] bg-[var(--surface-0)]">
        <AnimatePresence mode="wait">
          <motion.div key={tab + String(Boolean(src)) + phase} className="h-full" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }}>
            {body}
          </motion.div>
        </AnimatePresence>
        {src && (
          <button aria-label="Expand preview" onClick={() => setZoom(true)}
            className="absolute right-2 top-2 grid h-8 w-8 place-items-center rounded-nested bg-black/60 text-white hover:bg-black/80"><Maximize2 className="h-4 w-4" /></button>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-[var(--text-secondary)]">
        <span>Timestamp: <b className="text-[var(--text-primary)]">{q?.timestampSec !== undefined ? `${q.timestampSec.toFixed(2)} s` : tab === "original" && meta?.posterUrl ? "≈0.5 s" : "—"}</b></span>
        <span>Detections: <b className="text-[var(--text-primary)]">{q?.detections ?? "—"}</b></span>
        {q?.quality && <Badge tone="info">{q.quality}</Badge>}
        {result && (unreliable ? <Badge tone="bad">Not reliable</Badge> : <Badge tone="ok">Passed plausibility checks</Badge>)}
      </div>
      {result?.processing && (
        <div className="mt-2 space-y-1 text-[11px] text-[var(--text-secondary)]">
          <p>Processed <b className="text-[var(--text-primary)]">{result.processing.framesProcessed}</b> of <b className="text-[var(--text-primary)]">{result.processing.framesTotal}</b> frames ({result.processing.sampling}). {result.processing.previewNote}</p>
          <p>Detections are frame-level counts of detected regions, not unique fish{q?.confidences?.length ? `; preview model scores: ${q.confidences.join(", ")} (a score is not proof a detection is correct)` : ""}.</p>
          {result.reliability && <p>Reliability: {(["detections", "movement", "tracking"] as const).map((k) => `${k} ${(result.reliability?.[k] ?? "unavailable").replace("_", " ")}`).join(" · ")}</p>}
        </div>
      )}
      {unreliable && (
        <p role="status" className="mt-2 flex gap-2 rounded-nested border border-[var(--warn)]/30 bg-[var(--warn)]/10 p-2 text-[11px] text-[var(--warn)]">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{reasons.length ? reasons.join("; ") : "Tracking or movement results failed quality checks; treat them as unreliable."}
        </p>
      )}

      <AnimatePresence>
        {zoom && src && (
          <motion.div className="fixed inset-0 z-50 grid place-items-center bg-black/85 p-4" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            role="dialog" aria-modal="true" aria-label="Expanded preview" onClick={() => setZoom(false)}>
            <button aria-label="Close preview" className="absolute right-4 top-4 grid h-9 w-9 place-items-center rounded-nested bg-[var(--surface-1)] text-[var(--text-primary)]" onClick={() => setZoom(false)}><X className="h-4 w-4" /></button>
            <img src={src} alt="Expanded frame" className="max-h-full max-w-full rounded-card object-contain" onClick={(e) => e.stopPropagation()} />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
