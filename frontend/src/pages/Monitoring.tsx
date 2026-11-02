import { useState } from "react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Camera, CameraOff, SlidersHorizontal } from "lucide-react";
import { CROP_PRESETS, cropPresetId, DROIDCAM, type LiveCamera } from "../hooks/useLiveCamera";
import type { useAnalysis } from "../hooks/useAnalysis";
import { backendConfigured } from "../services/api";
import { trackConfEnabled } from "../services/trackQuality";
import { Badge, Panel } from "../components/ui";
import Popover from "../components/ui/Popover";
import CameraStage from "../components/monitoring/CameraStage";
import EngineBadge from "../components/monitoring/EngineBadge";
import SessionTimeline from "../components/monitoring/SessionTimeline";
import { useT } from "../i18n/LanguageProvider";
import MetricsRow from "../sections/MetricsRow";
import VideoAnalysis from "../sections/VideoAnalysis";
import BehaviorPanel from "../sections/BehaviorPanel";
import HistoryPanel from "../sections/HistoryPanel";
import Observations from "../sections/Observations";
import RecentAnalyses from "../sections/RecentAnalyses";

const RECENT_MS = 5000;

const Tile = ({ label, value, note }: { label: string; value: string; note?: string }) => (
  <div className="rounded-nested border border-[var(--border-subtle)] bg-[var(--surface-2)]/60 p-3">
    <p className="text-xs text-[var(--text-secondary)]">{label}</p>
    <p className="mt-1 text-lg font-semibold text-[var(--text-primary)]">{value}</p>
    {note && <p className="text-[11px] text-[var(--text-secondary)]">{note}</p>}
  </div>
);

const engineLabel = (model: string | null | undefined, visionBackend: "api" | "yolo" | null) => {
  if (model) {
    if (/florence/i.test(model)) return "Florence · local";
    if (/world/i.test(model)) return "YOLO World · local";
    if (/yolo/i.test(model)) return "YOLO · local";
    return "Cloud vision";
  }
  return visionBackend === "yolo" ? "YOLO · local" : visionBackend === "api" ? "Cloud vision" : "Engine idle";
};

export default function Monitoring({ cam, a, modelAvailable, backendConnected, visionBackend }: {
  cam: LiveCamera; a: ReturnType<typeof useAnalysis>; modelAvailable: boolean; backendConnected: boolean; visionBackend: "api" | "yolo" | null;
}) {
  const recent = cam.receivedAt !== null && Date.now() - cam.receivedAt < RECENT_MS * 3 && cam.result !== null;
  const o = recent ? cam.result : null;
  const t = useT();
  const qualityPercent = cam.trackQuality ? Math.round(cam.trackQuality.score * 100) : null;
  const confs = o?.detections.map((d) => d.confidence) ?? [];
  const trackConf = trackConfEnabled(import.meta.env.VITE_TRACK_CONF);
  const qualityValue = trackConf
    ? cam.trackQuality ? `${qualityPercent}% ${cam.trackQuality.band}` : "-"
    : confs.length ? `${Math.max(...confs).toFixed(2)} max` : "-";
  const qualityNote = trackConf
    ? cam.trackQuality ? `mean q over ${cam.trackQuality.tracks} confirmed track${cam.trackQuality.tracks === 1 ? "" : "s"} - motion proxy, not accuracy` : "No confirmed tracks yet"
    : confs.length ? `${(confs.reduce((x, y) => x + y, 0) / confs.length).toFixed(2)} mean: legacy raw model scores` : "No detections";
  const detector = o?.vision?.model ? `${o.vision.provider ?? "local"} ${o.vision.model}`
    : visionBackend === "yolo" ? "YOLO weights" : "API vision (Groq/Gemini)";
  const cadenceS = cam.cadenceMs !== null ? (cam.cadenceMs / 1000).toFixed(1) : null;
  const [customOpen, setCustomOpen] = useState(false);
  const [customText, setCustomText] = useState(cam.crop);
  const [cropError, setCropError] = useState<string | null>(null);
  const preset = cropPresetId(cam.crop);
  const truth: { tone: "ok" | "warn" | "bad" | "info" | "mute"; text: string } = (() => {
    if (!o) return cam.status === "on" ? { tone: "mute", text: "Waiting for first analysis" } : { tone: "mute", text: "Camera off" };
    const vb = o.visionBackend ?? visionBackend;
    if (o.degraded) {
      const why = (o.degradedReason ?? "cloud vision error").slice(0, 60);
      return { tone: "warn", text: `API DOWN — ${why}${o.visionBackend?.includes("yolo-fallback") ? " · local YOLO fallback" : ""}` };
    }
    const displayCount = Math.min(2, o.count);
    if (o.vision?.model === "florence") return { tone: "ok", text: `LIVE: local florence · ${displayCount} fish (max 2)` };
    if (o.vision?.model === "world") return { tone: "ok", text: `LIVE: local world · ${displayCount} fish (max 2)` };
    if (vb === "yolo" || o.visionBackend?.includes("yolo-fallback")) return { tone: "ok", text: `LIVE: local YOLO · ${displayCount} fish (max 2)` };
    return displayCount > 0 ? { tone: "info", text: `LIVE: API vision · ${displayCount} fish (max 2)` } : { tone: "bad", text: "LIVE: API vision · no detections" };
  })();
  const pending = !backendConfigured ? "Model integration pending: no backend is configured."
    : !backendConnected ? "Backend offline: start it to run detection." : !modelAvailable ? (visionBackend === "yolo" ? "Model weights not found on the backend." : "No LLM API key on the backend: set GROQ_API_KEY and/or GEMINI_API_KEY.")
      : cam.inferError ? `Detection failed: ${cam.inferError}` : null;
  const data = cam.history.map((h) => ({ t: h.t, count: h.count }));
  const tracks = o?.tracks ?? [];
  const mv = o?.movement;
  const confirmedCount = tracks.filter((t) => t.confirmed && !t.static).length;
  const staticCount = tracks.filter((t) => t.static).length;
  const trackNote = !o ? undefined
    : tracks.length === 0 ? (o.count === 0 ? "No detections to track in this frame" : "Detections present but no track continued (new session or fragmented)")
    : `Session-local ids · ${confirmedCount} fish confirmed (dashed = tentative)${staticCount ? ` · ${staticCount} static ignored` : ""} · camera ${mv?.camera.state ?? "unknown"}`;
  const moveValue = !o ? "—" : mv && mv.mean_speed_px_sec !== null
    ? `${mv.mean_speed_px_sec.toFixed(1)} px/s mean`
    : (mv && mv.valid_speed_intervals === 0 ? "Collecting…" : "—");
  const behavior = o?.behavior;
  const behTone = behavior?.status_tone ?? "mute";
  const behColor = behTone === "bad" ? "text-red-500" : behTone === "warn" ? "text-amber-500" : behTone === "info" ? "text-cyan-400" : behTone === "ok" ? "text-green-500" : "text-[var(--text-secondary)]";
  const moveNote = !o || !mv ? "Needs tracked motion across frames" :
    mv.speeds_approximate ? `Approximate at ~1 fps · camera ${mv.camera.state} · stationary frac ${mv.stationary_frac ?? "—"} (experimental)` :
    `Stationary frac ${mv.stationary_frac ?? "—"} · ${mv.valid_speed_intervals} intervals (experimental)`;
  const presetLabel = CROP_PRESETS.find((p) => p.id === preset)?.label ?? "Custom crop";

  return (
    <div className="flex flex-col gap-4">
      <header className="glass rounded-2xl p-4 sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="max-w-2xl">
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[var(--accent)]">Live monitoring</p>
            <h1 className="mt-1 font-display text-xl font-semibold leading-tight text-[var(--text-primary)]">Camera and fish activity</h1>
            <p className="mt-1 text-xs text-[var(--text-secondary)]">Browser preview with live overlays. Detection quality is not validated for every camera, tank or light level — check overlays against the picture.</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <EngineBadge engine={engineLabel(o?.vision?.model, visionBackend)} detail={o ? `${o.count} in last frame` : "waiting for analysis"} live={o !== null} />
            <span className="group relative inline-flex" tabIndex={0} aria-describedby="track-quality-tip">
              <Badge tone="info">{t("monitoring.trackQuality")} · {cam.trackQuality && qualityPercent !== null ? t("monitoring.trackQualityValue", { score: qualityPercent, band: cam.trackQuality.band }) : t("monitoring.trackQualityPending")}</Badge>
              <span id="track-quality-tip" role="tooltip"
                className="pointer-events-none absolute left-0 top-full z-50 mt-2 w-[min(20rem,calc(100vw-2rem))] rounded-nested border border-[var(--border-subtle)] bg-[var(--surface-1)] p-2 text-[11px] font-normal leading-relaxed text-[var(--text-secondary)] opacity-0 shadow-xl transition-opacity group-hover:opacity-100 group-focus:opacity-100">
                {t("monitoring.trackQualityTooltip")}
              </span>
            </span>
            <Badge tone={cam.status === "on" ? "ok" : "mute"}>{cam.status === "on" ? "Camera on" : "Camera off"}</Badge>
            <Badge tone={truth.tone}>{truth.text}</Badge>
          </div>
        </div>
      </header>

      <Panel title="Live camera" subtitle={`Browser camera preview (live); ${cadenceS ? `measured ${cadenceS} s between analyses` : `1 frame per ${(cam.analyzeEveryMs / 1000).toFixed(0)} s`} sent to ${detector}`}>
        <div className="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <div className="min-w-0">
            <CameraStage videoRef={cam.videoRef} previewRef={cam.previewRef} overlayRef={cam.overlayRef}
              status={cam.status} detail={cam.detail} />
            <div className="mt-3 flex flex-wrap items-center gap-2">
              {cam.status === "on"
                ? <button onClick={cam.stop} className="inline-flex h-10 items-center gap-2 rounded-nested border border-[var(--border-subtle)] bg-[var(--surface-1)] px-4 text-sm text-[var(--text-primary)] hover:bg-[var(--surface-2)]"><CameraOff className="h-4 w-4" />Stop camera</button>
                : <button onClick={() => void cam.start()} disabled={cam.status === "starting"} className="inline-flex h-10 items-center gap-2 rounded-nested bg-[var(--accent)] px-4 text-sm font-medium text-[var(--accent-contrast)] disabled:opacity-50"><Camera className="h-4 w-4" />Start camera</button>}
              {cam.status === "on" && (
                <>
                  <button onClick={() => cam.analyzeNow()} className="inline-flex h-10 items-center gap-2 rounded-nested border border-[var(--accent)]/40 bg-[var(--surface-1)] px-4 text-sm font-medium text-[var(--accent)] hover:bg-[var(--surface-2)]">Analyze now</button>
                  <Popover label="Camera setup" trigger={<><SlidersHorizontal className="h-4 w-4" />Camera setup<span className="text-[11px] text-[var(--text-secondary)]">{cam.rotate}° · {presetLabel}</span></>}>
                    <div className="space-y-3">
                      <div>
                        <p className="text-sm font-semibold text-[var(--text-primary)]">Camera setup</p>
                        <p className="text-[11px] text-[var(--text-secondary)]">Rotate and crop apply to the preview and the analysed frame, so boxes always match what you see.</p>
                      </div>
                      <label className="block text-xs text-[var(--text-secondary)]">Rotate
                        <select aria-label="Rotate preview and analysed frames" value={cam.rotate} onChange={(e) => cam.setRotate(Number(e.target.value))}
                          className="mt-1 h-9 w-full rounded-nested border border-[var(--border-subtle)] bg-[var(--surface-1)] px-2 text-sm text-[var(--text-primary)]">
                          {[0, 90, 180, 270].map((d) => <option key={d} value={d}>{d}°</option>)}
                        </select>
                      </label>
                      <label className="block text-xs text-[var(--text-secondary)]">Crop
                        <select aria-label="Crop preset for preview and analysed frames" value={preset === "custom" ? "custom" : preset}
                          onChange={(e) => {
                            const id = e.target.value;
                            if (id === "custom") { setCustomOpen(true); setCustomText(cam.crop); setCropError(null); return; }
                            setCustomOpen(false); setCropError(null);
                            cam.setCrop(CROP_PRESETS.find((p) => p.id === id)?.crop ?? "");
                          }}
                          className="mt-1 h-9 w-full rounded-nested border border-[var(--border-subtle)] bg-[var(--surface-1)] px-2 text-sm text-[var(--text-primary)]">
                          {CROP_PRESETS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
                          <option value="custom">Custom…</option>
                        </select>
                      </label>
                      {(customOpen || preset === "custom") && (
                        <div>
                          <label className="block text-xs text-[var(--text-secondary)]">Custom crop box
                            <input value={customText} onChange={(e) => setCustomText(e.target.value)} placeholder="x1,y1,x2,y2"
                              aria-label="Custom crop box x1,y1,x2,y2 (0 to 1)" className="mt-1 h-9 w-full rounded-nested border border-[var(--border-subtle)] bg-[var(--surface-1)] px-2 text-sm text-[var(--text-primary)]" />
                          </label>
                          <button onClick={() => {
                            const ok = cam.setCrop(customText);
                            setCropError(ok ? null : "Use x1,y1,x2,y2 with values 0–1 and at least 5% width and height.");
                          }} className="mt-2 inline-flex h-9 items-center rounded-nested border border-[var(--border-subtle)] bg-[var(--surface-1)] px-3 text-sm text-[var(--text-primary)] hover:bg-[var(--surface-2)]">Apply crop</button>
                          {cropError && <p role="alert" className="mt-1 text-[11px] text-[var(--warn)]">{cropError}</p>}
                        </div>
                      )}
                    </div>
                  </Popover>
                </>
              )}
              <p className="text-xs text-[var(--text-secondary)]">The camera starts automatically when this app opens and stays on while you switch pages, until you stop it.</p>
            </div>
            {cam.status === "on" && cam.cooldownUntil !== null && cam.cooldownUntil > Date.now() && (
              <p role="status" className="mt-2 text-xs text-[var(--warn)]">Quota cooling down — automatic analysis resumes at {new Date(cam.cooldownUntil).toLocaleTimeString()}. “Analyze now” still tries immediately.</p>
            )}
            {cam.devices.length > 0 && (
              <label className="mt-3 flex flex-wrap items-center gap-2 text-xs text-[var(--text-secondary)]">Camera
                <select aria-label="Choose camera" value={cam.active.id ?? ""} onChange={(e) => void cam.choose(e.target.value)}
                  className="h-9 min-w-0 max-w-full rounded-nested border border-[var(--border-subtle)] bg-[var(--surface-1)] px-2 text-sm text-[var(--text-primary)]">
                  {cam.active.id === null && <option value="">Default</option>}
                  {cam.devices.map((d) => <option key={d.id} value={d.id}>{d.label}</option>)}
                </select>
              </label>
            )}
            {cam.status === "on" && DROIDCAM.test(cam.active.label) && (
              <p role="status" className="mt-2 text-xs text-[var(--text-secondary)]">Using DroidCam. If the picture says "Start DroidCam", open the DroidCam Client on this PC, choose USB, press Start, and keep the phone app running. If the picture does not change after it connects, press Stop camera, then Start camera.</p>
            )}
            {cam.status === "on" && (
              <p className="mt-2 text-[11px] text-[var(--text-secondary)]">Live loop: boxes redrawn at {cam.drawFps ?? "—"} fps (interpolated between analyses) · motion trigger {cam.motionOn ? "on" : "off"} · confirmed tracks held 2 cycles if briefly missed.</p>
            )}
            {cam.status === "on" && <p className="mt-1 text-[11px] text-[var(--text-secondary)]">{t("monitoring.trackQualityLegend")}</p>}
            {cam.status === "on" && pending && <p role="status" className="mt-2 text-sm text-[var(--warn)]">{pending}</p>}
            <div className="mt-3">
              <SessionTimeline samples={cam.history} active={cam.status === "on"} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 self-start xl:grid-cols-1" aria-label="Detection summary">
            <Tile label="Detections in this frame" value={o ? String(Math.min(2, o.count)) : "—"} note="Max 2 fish monitored (tank maximum)" />
            <Tile label="Track quality" value={qualityValue} note={qualityNote} />
            <Tile label="Segmentation" value={o ? (o.detections.some((d) => d.outline) ? "Outlines shown" : "Boxes only") : "No recent inference"} note="Drawn from model output" />
            <Tile label="Last inference" value={cam.receivedAt && o ? new Date(cam.receivedAt).toLocaleTimeString() : "—"} note={o ? `${o.inferenceMs} ms on the backend${cam.procFps !== null ? ` · ${cam.procFps.toFixed(1)} fps processed` : ""}` : undefined} />
            <Tile label="Tracking (fish)" value={!o ? "—" : tracks.length ? `${confirmedCount}${staticCount ? ` (+${staticCount} static)` : ""}` : "None"} note={trackNote ?? "Start the camera to track"} />
            <Tile label="Movement (live)" value={moveValue} note={moveNote} />
            {behavior && (
              <div className="rounded-nested border border-[var(--border-subtle)] bg-[var(--surface-2)]/60 p-3">
                <p className="text-xs text-[var(--text-secondary)]">Fish behaviour</p>
                <p className={`mt-1 text-lg font-semibold ${behColor}`}>{behavior.overall_label ?? "—"}</p>
                <p className="text-[11px] text-[var(--text-secondary)]">{behavior.detail}</p>
                <p className="text-[10px] text-[var(--text-secondary)] mt-1">Surface {behavior.surface_proxy_pct ?? "—"}% · {behavior.activity_level ?? "—"}</p>
              </div>
            )}
          </div>
        </div>
        {o?.review && <p role="status" className="mt-3 rounded-nested border border-[var(--warn)]/40 bg-[var(--warn)]/10 p-2 text-[11px] text-[var(--warn)]">Review: {o.review}</p>}
        <p className="mt-3 text-[11px] text-[var(--text-secondary)]">{o?.note ?? "Detection quality is not validated for this camera, tank or lighting. Treat overlays as unverified model output and check them against the picture."}</p>
      </Panel>

      <Panel title="Fish activity" subtitle="Detection history from this session">
        {data.length < 2 ? <p className="text-sm text-[var(--text-secondary)]">{cam.status === "on" ? "Collecting detections…" : "No live detections yet. Turn the camera on."}</p> : (
          <div className="h-40" aria-label="Detections per frame this session">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                <XAxis dataKey="t" type="number" scale="time" domain={["dataMin", "dataMax"]} tick={{ fontSize: 10, fill: "var(--text-secondary)" }} tickFormatter={(t: number) => new Date(t).toLocaleTimeString([], { minute: "2-digit", second: "2-digit" })} />
                <YAxis width={28} allowDecimals={false} tick={{ fontSize: 10, fill: "var(--text-secondary)" }} />
                <Tooltip contentStyle={{ background: "var(--surface-2)", border: "1px solid var(--border-subtle)", borderRadius: 8, fontSize: 12, color: "var(--text-primary)" }} labelFormatter={(t) => new Date(Number(t)).toLocaleTimeString()} formatter={(v) => [String(v), "Detections"]} />
                <Line type="stepAfter" dataKey="count" stroke="var(--accent)" strokeWidth={1.75} dot={false} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
        <p className="mt-2 text-[11px] text-[var(--text-secondary)]">The chart counts detections per frame and says nothing about behaviour or health. Per-track speeds appear in the Movement tile above (approximate, experimental).</p>
      </Panel>

      <MetricsRow result={a.result} phase={a.phase} progress={a.progress} />
      <VideoAnalysis a={a} />
      <BehaviorPanel backendConnected={backendConnected} />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Observations result={a.result} />
        <RecentAnalyses session={a.history} onRemove={a.removeEntry} />
      </div>
      <HistoryPanel />
    </div>
  );
}
