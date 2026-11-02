import { useCallback, useEffect, useRef, useState } from "react";
import type { AnalysisResult, AnalysisStatus, RecentAnalysis, VideoMeta } from "../types";
import * as api from "../services/api";
import { readVideoMeta } from "../services/video";

export type Phase = "idle" | "selected" | "uploading" | "uploaded" | "processing" | "done" | "error";
export type Stage = "idle" | "uploading" | "uploaded" | "queued" | "running" | "completed" | "completed_unreliable" | "failed";
export type Notify = (kind: "success" | "error" | "info", message: string) => void;

const unreliable = (r: AnalysisResult) => [r.detections, r.tracking, r.movement].some((x) => x?.reliable === false);

export function useAnalysis(notify: Notify) {
  const [file, setFile] = useState<File | null>(null);
  const [meta, setMeta] = useState<VideoMeta | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [progress, setProgress] = useState<number | undefined>();
  const [jobState, setJobState] = useState<"queued" | "processing">("queued");
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<RecentAnalysis[]>([]);
  const [doneJob, setDoneJob] = useState<string | null>(null);   // id of the job whose results are on screen
  const abort = useRef<AbortController | null>(null);
  const jobId = useRef<string | null>(null);
  const entryId = useRef<string | null>(null);

  useEffect(() => () => abort.current?.abort(), []);

  const setStatus = (status: AnalysisStatus) =>
    setHistory((h) => h.map((e) => (e.id === entryId.current ? { ...e, status } : e)));

  const upload = useCallback(async (f: File) => {
    const ctl = new AbortController();
    abort.current = ctl;
    setError(null); setProgress(0); setPhase("uploading");
    try {
      jobId.current = (await api.uploadVideo(f, setProgress, ctl.signal)).videoId;
      setProgress(undefined); setPhase("uploaded");
      notify("success", "Video uploaded. Press Analyze Video to start.");
    } catch (e) {
      if (abort.current !== ctl) return;   // superseded by a new selection or Remove
      setProgress(undefined);
      if ((e as Error).name === "AbortError") { setError("Upload cancelled."); setPhase("error"); return; }
      const msg = (e as Error).message.includes("network error") ? "Backend unavailable: the upload could not reach the server." : (e as Error).message;
      setError(msg); setPhase("error"); notify("error", msg);
    }
  }, [notify]);

  const select = useCallback(async (f: File) => {
    const problem = api.validateVideo(f);
    if (problem) { notify("error", problem); return; }
    abort.current?.abort();
    abort.current = null;
    jobId.current = null;
    setFile(f); setResult(null); setDoneJob(null); setError(null); setProgress(undefined); setPhase("selected");
    const m = await readVideoMeta(f);
    setMeta(m);
    const id = `${Date.now()}-${f.name}`;
    entryId.current = id;
    setHistory((h) => [{ id, filename: f.name, at: new Date().toLocaleString(), durationSec: m.durationSec, status: "not_analyzed", thumbnailUrl: m.posterUrl, source: "session" } satisfies RecentAnalysis, ...h].slice(0, 6));
    if (api.backendConfigured) void upload(f);
  }, [notify, upload]);

  const clear = useCallback(() => {
    abort.current?.abort();
    abort.current = null;
    jobId.current = null;
    setFile(null); setMeta(null); setResult(null); setDoneJob(null); setError(null); setProgress(undefined); setPhase("idle");
  }, []);

  const analyze = useCallback(async () => {
    if (!file) return;
    if (!api.backendConfigured) {
      const msg = "Backend not connected (demo mode): analysis is unavailable. Set VITE_API_BASE_URL to enable it.";
      setError(msg); notify("info", msg); return;
    }
    if (!jobId.current) { await upload(file); if (!jobId.current) return; }
    const id = jobId.current;
    const ctl = new AbortController();
    abort.current = ctl;
    setError(null); setResult(null); setDoneJob(null); setProgress(undefined); setJobState("queued"); setPhase("processing"); setStatus("processing");
    try {
      let s = await api.getJobStatus(id);
      if (s.state === "uploaded" || s.state === "failed") { await api.startAnalysis(id); s = { state: "queued" }; }   // already queued/running/completed: just follow it
      while (s.state !== "completed") {
        if (s.state === "failed") throw new Error(s.error ?? "The backend reported a failed analysis.");
        setJobState(s.state === "processing" ? "processing" : "queued");
        await new Promise((r) => setTimeout(r, 1000));
        if (ctl.signal.aborted) throw new DOMException("Stopped", "AbortError");
        s = await api.getJobStatus(id);
      }
      const res = await api.getAnalysisResult(id);
      setResult(res); setDoneJob(id); setPhase("done");
      setStatus(unreliable(res) ? "needs_review" : "completed");
      notify("success", unreliable(res) ? "Analysis complete, but some results are not reliable." : "Analysis complete.");
    } catch (e) {
      if (abort.current !== ctl) return;
      if ((e as Error).name === "AbortError") { setPhase("uploaded"); setStatus("not_analyzed"); return; }
      const msg = (e as Error).message === "Failed to fetch" ? "Backend unavailable: could not reach the server." : (e as Error).message;
      setError(msg); setPhase("error"); setStatus("failed"); notify("error", msg);
    }
  }, [file, notify, upload]);

  /** Stops uploading or waiting. There is no server-side cancel, so a started analysis may still finish on the server. */
  const cancel = useCallback(() => {
    abort.current?.abort();
    notify("info", phase === "processing" ? "Stopped waiting. The server may still finish this analysis; press Analyze Video to check it." : "Upload cancelled.");
  }, [notify, phase]);

  const removeEntry = useCallback((id: string) => setHistory((h) => h.filter((e) => e.id !== id)), []);

  const stage: Stage =
    phase === "uploading" ? "uploading"
    : phase === "uploaded" ? "uploaded"
    : phase === "processing" ? (jobState === "queued" ? "queued" : "running")
    : phase === "done" ? (result && unreliable(result) ? "completed_unreliable" : "completed")
    : phase === "error" ? "failed" : "idle";

  return { file, meta, phase, stage, progress, result, jobId: doneJob, error, history, select, clear, analyze, cancel, removeEntry };
}
