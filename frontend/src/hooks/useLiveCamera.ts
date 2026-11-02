import { useCallback, useEffect, useRef, useState } from "react";
import { backendConfigured, trackFrame, type LiveResult } from "../services/api";
import { createTrackQuality, formatQualityLabel, trackConfEnabled, type FrameQuality, type TrackQuality, type TrackQualityTracker } from "../services/trackQuality";
import type { CameraStatus } from "../config/alerts";

const MAX_RETRIES = 5, RETRY_MS = 3000;   // reconnect attempts after the camera drops
const INTERVAL_MS = 1000;      // preview tick; analysis itself is quota-gated below
// Quota-safe cadence: free LLM tiers cannot sustain 1 vision call/sec (~60/min).
// Analyse one frame every ANALYZE_EVERY_MS instead; the preview stays live.
// Floor 3000ms protects quotas even if misconfigured.
const ANALYZE_EVERY_MS = Math.max(3000, Number(import.meta.env.VITE_LIVE_ANALYZE_MS ?? 4000) || 4000);
const QUOTA_PAUSE_MS = 60000;  // automatic pause after a quota/rate-limit error, then resume
const MAX_WIDTH = 640;
const OFF_KEY = "aqua.camera.off";
const FPS_WINDOW = 6;          // measured processing rate over the last N completions
// A4 motion trigger (client-side spend gate): with a local engine a frame every
// 4 s costs nothing, but on cloud vision this skips unchanged scenes. A 15 s
// keepalive still refreshes detection/tracking so server sessions never idle out.
const MOTION_ON = import.meta.env.VITE_MOTION_TRIGGER !== "0";
const MOTION_THRESH = Math.max(2, Number(import.meta.env.VITE_MOTION_THRESH ?? 10) || 10);
const MOTION_FRAC = Math.max(0.005, Number(import.meta.env.VITE_MOTION_FRAC ?? 0.02) || 0.02);
const MOTION_KEEPALIVE_MS = Math.max(ANALYZE_EVERY_MS, (Number(import.meta.env.VITE_MOTION_KEEPALIVE_S ?? 15) || 15) * 1000);
const MOTION_SMALL = [64, 36] as const;
// A3 grace: keep drawing a confirmed track for this many analysis cycles after
// the backend stops reporting it (the tracker itself already tolerates 3 misses).
const GRACE_CYCLES = 2;
// CONF-C rollback: 0 restores the legacy constant Florence score display.
const TRACK_CONF = trackConfEnabled(import.meta.env.VITE_TRACK_CONF);
export interface Sample { t: number; count: number }
type Box = [number, number, number, number];
interface Snap { t: number; result: LiveResult }
interface Ghost { box: Box; t: number; misses: number; confidence: number }

const lerp = (a: number, b: number, k: number) => a + (b - a) * k;
const lerpBox = (a: Box, b: Box, k: number): Box => [lerp(a[0], b[0], k), lerp(a[1], b[1], k), lerp(a[2], b[2], k), lerp(a[3], b[3], k)];
const center = (b: Box) => [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2] as const;
const near = (a: Box, b: Box, tol = 0.04) => {
  const [ax, ay] = center(a), [bx, by] = center(b);
  return Math.abs(ax - bx) < tol && Math.abs(ay - by) < tol;
};

const newSession = () =>
  (typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`).replace(/[^A-Za-z0-9_-]/g, "").slice(0, 32) || `s${Date.now()}`;

const DEVICE_KEY = "aqua.camera.device";
export const DROIDCAM = /droidcam/i;

/** Map raw backend/provider errors to actionable user-facing messages (values never leak; text only). */
function friendlyLiveError(msg: string): string {
  if (/401|403|error code: 1010|invalid.*key|key.*rejected|blocked/i.test(msg))
    return `${msg} — the Groq key was rejected. Regenerate it at console.groq.com, or rely on Gemini meanwhile.`;
  if (/429|quota|rate limit|exhausted/i.test(msg))
    return `${msg} — quota exhausted. Automatic analysis paused briefly; press Analyze now to retry, or lower the rate via VITE_LIVE_ANALYZE_MS.`;
  return msg;
}
const savedDevice = () => { try { return localStorage.getItem(DEVICE_KEY); } catch { return null; } };
const saveDevice = (id: string | null) => { try { id ? localStorage.setItem(DEVICE_KEY, id) : localStorage.removeItem(DEVICE_KEY); } catch { /* storage unavailable */ } };
const wasSwitchedOff =() => { try { return localStorage.getItem(OFF_KEY) === "1"; } catch { return false; } };
const remember = (off: boolean) => { try { off ? localStorage.setItem(OFF_KEY, "1") : localStorage.removeItem(OFF_KEY); } catch { /* storage unavailable */ } };

// ---- processed input (A): rotate + crop happen in the browser, before the frame
// is sent AND in the preview, so what the model sees is what the user sees.
const ROTATE_KEY = "aqua.live.rotate";
const CROP_KEY = "aqua.live.crop";
export const CROP_PRESETS = [
  { id: "full", label: "Full frame", crop: "" },
  { id: "tb12", label: "Trim top 12%", crop: "0,0.12,1,0.88" },
  { id: "tb20", label: "Trim top 20%", crop: "0,0.2,1,0.8" },
] as const;
export type CropPresetId = (typeof CROP_PRESETS)[number]["id"] | "custom";

/** "" = no crop; "x1,y1,x2,y2" (0-1 fractions) = crop box; null = invalid input. */
export function normalizeCrop(raw: string): string | null {
  const s = raw.trim();
  if (s === "") return "";
  const parts = s.split(",").map((p) => Number(p.trim()));
  if (parts.length !== 4 || parts.some((n) => !Number.isFinite(n))) return null;
  const [x1, y1, x2, y2] = parts;
  if (!(x1 >= 0 && y1 >= 0 && x2 <= 1 && y2 <= 1 && x2 - x1 >= 0.05 && y2 - y1 >= 0.05)) return null;
  const r = (n: number) => Math.round(n * 1000) / 1000;
  return [r(x1), r(y1), r(x2), r(y2)].join(",");
}
const parseCrop = (raw: string): [number, number, number, number] | null => {
  const s = normalizeCrop(raw);
  if (!s) return null;
  const [x1, y1, x2, y2] = s.split(",").map(Number);
  return [x1, y1, x2, y2];
};
export const cropPresetId = (crop: string): CropPresetId =>
  !crop ? "full" : CROP_PRESETS.find((p) => p.crop === crop)?.id ?? "custom";

// C0 rotation oracle (eval_ab/STATS.md): the phone feed arrives ~90° off; this
// camera's frame is upright at Rotate = 90 (verified visually on real captures).
// First-run default only: any value the user picks (incl. 0) is stored and wins.
const DEFAULT_ROTATE = 90;
const savedRotate = () => {
  try {
    const raw = localStorage.getItem(ROTATE_KEY);
    if (raw !== null) {
      const v = Number(raw);
      if ([0, 90, 180, 270].includes(v)) return v;
    }
  } catch { /* storage unavailable */ }
  return DEFAULT_ROTATE;
};
const savedCrop = () => { try { return normalizeCrop(localStorage.getItem(CROP_KEY) ?? "") ?? ""; } catch { return ""; } };

/** Draw the video through the live transform (rotate, then crop), scaled to MAX_WIDTH, into `dest`. */
function drawProcessed(v: HTMLVideoElement, dest: HTMLCanvasElement, rotateDeg: number, cropStr: string, scratch: HTMLCanvasElement): boolean {
  const vw = v.videoWidth, vh = v.videoHeight;
  if (vw <= 0 || vh <= 0) return false;
  const rot = ((rotateDeg % 360) + 360) % 360;
  const swapped = rot === 90 || rot === 270;
  const rw = swapped ? vh : vw, rh = swapped ? vw : vh;
  scratch.width = rw; scratch.height = rh;
  const sg = scratch.getContext("2d");
  if (!sg) return false;
  if (rot === 90) { sg.translate(rw, 0); sg.rotate(Math.PI / 2); }
  else if (rot === 180) { sg.translate(rw, rh); sg.rotate(Math.PI); }
  else if (rot === 270) { sg.translate(0, rh); sg.rotate(-Math.PI / 2); }
  sg.drawImage(v, 0, 0);
  const [x1, y1, x2, y2] = parseCrop(cropStr) ?? [0, 0, 1, 1];
  const cw = Math.max(1, (x2 - x1) * rw), ch = Math.max(1, (y2 - y1) * rh);
  const scale = Math.min(1, MAX_WIDTH / cw);
  dest.width = Math.max(1, Math.round(cw * scale));
  dest.height = Math.max(1, Math.round(ch * scale));
  const dg = dest.getContext("2d");
  if (!dg) return false;
  dg.drawImage(scratch, x1 * rw, y1 * rh, cw, ch, 0, 0, dest.width, dest.height);
  return true;
}

/**
 * Always-on browser camera with per-second frame-level detection through the backend.
 * Starts automatically (the browser still asks for permission) unless the user switched it off.
 * Results are model outputs for single frames: no tracking, no unique-fish count.
 */
export function useLiveCamera() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const previewRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const want = useRef(false);                                 // true while the camera should be on
  const pending = useRef<Promise<MediaStream> | null>(null);  // the single in-flight permission request
  const [status, setStatus] = useState<CameraStatus>("off");
  const [detail, setDetail] = useState<string | null>(null);
  const [result, setResult] = useState<LiveResult | null>(null);
  const [receivedAt, setReceivedAt] = useState<number | null>(null);
  const [inferError, setInferError] = useState<string | null>(null);
  const [history, setHistory] = useState<Sample[]>([]);
  const [devices, setDevices] = useState<{ id: string; label: string }[]>([]);
  const [active, setActive] = useState<{ id: string | null; label: string }>({ id: null, label: "" });
  const [procFps, setProcFps] = useState<number | null>(null);   // measured backend processing rate (completions/sec)
  const [cadenceMs, setCadenceMs] = useState<number | null>(null); // measured gap between completed analyses (A5)
  const [drawFps, setDrawFps] = useState<number | null>(null);      // measured overlay repaint rate (A5)
  const [cooldownUntil, setCooldownUntil] = useState<number | null>(null); // quota pause: auto-analysis suspended until this time
  const [trackQuality, setTrackQuality] = useState<FrameQuality | null>(null);
  const [rotate, setRotateState] = useState<number>(() => savedRotate());  // processed input (A), persisted
  const [crop, setCropState] = useState<string>(() => savedCrop());
  const rotateRef = useRef(rotate);                             // mirrors for the rAF/send loops (no closure staleness)
  const cropRef = useRef(crop);
  const scratchRef = useRef<HTMLCanvasElement | null>(null);    // rotation scratch canvas, reused per draw
  const snapsRef = useRef<Snap[]>([]);                          // last two model results (A2 interpolation)
  const ghostsRef = useRef<Map<number, Ghost>>(new Map());      // confirmed tracks held for 2 cycles (A3)
  const smallRef = useRef<HTMLCanvasElement | null>(null);      // downscaled frame for the motion gate
  const prevSmallRef = useRef<Uint8Array | null>(null);
  const qualityRef = useRef<TrackQualityTracker | null>(null);
  if (!qualityRef.current) qualityRef.current = createTrackQuality();

  const setRotate = useCallback((deg: number) => {
    const v = [0, 90, 180, 270].includes(deg) ? deg : 0;
    rotateRef.current = v; setRotateState(v);
    try { localStorage.setItem(ROTATE_KEY, String(v)); } catch { /* storage unavailable */ }
  }, []);
  /** Returns false (and keeps the current crop) when the box is invalid. */
  const setCrop = useCallback((raw: string): boolean => {
    const v = normalizeCrop(raw);
    if (v === null) return false;
    cropRef.current = v; setCropState(v);
    try { v ? localStorage.setItem(CROP_KEY, v) : localStorage.removeItem(CROP_KEY); } catch { /* storage unavailable */ }
    return true;
  }, []);
  const pendingKey = useRef<string | null>(null);
  const sessionRef = useRef<string>("");                        // backend tracking session, fresh per camera start
  const completionsRef = useRef<number[]>([]);                  // completion timestamps for the measured rate
  const lastSentRef = useRef(0);                                // last analysis request (cadence gate)
  const cooldownRef = useRef<number | null>(null);              // mirror of cooldownUntil for the loop
  const requestRef = useRef<((force?: boolean) => Promise<void>) | null>(null); // on-demand trigger (Analyze now button)
  const retries = useRef(0);
  const retryTimer = useRef(0);

  const stop = useCallback((userChoice = true) => {
    want.current = false;                                     // a start() still waiting for permission must not attach its stream
    clearTimeout(retryTimer.current);
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    if (userChoice) remember(true);
    sessionRef.current = ""; completionsRef.current = [];     // backend session expires by TTL; drop local rate state
    cooldownRef.current = null; lastSentRef.current = 0;
    snapsRef.current = []; ghostsRef.current = new Map(); prevSmallRef.current = null;
    qualityRef.current = createTrackQuality(); setTrackQuality(null);
    setStatus("off"); setResult(null); setInferError(null); setProcFps(null); setCadenceMs(null); setDrawFps(null); setCooldownUntil(null);
  }, []);

  const listDevices = useCallback(async () => {
    try {
      const all = await navigator.mediaDevices.enumerateDevices();
      setDevices(all.filter((d) => d.kind === "videoinput").map((d, i) => ({ id: d.deviceId, label: d.label || `Camera ${i + 1}` })));
    } catch { /* enumeration unavailable */ }
  }, []);

  const start = useCallback(async (deviceId: string | null = savedDevice(), auto = true) => {
    if (streamRef.current) return;
    if (!navigator.mediaDevices?.getUserMedia) { setStatus("unsupported"); return; }
    want.current = true;
    remember(false); setStatus("starting"); setDetail(null);
    const size = { width: { ideal: 1280 }, height: { ideal: 720 } };
    try {
      // One permission request at a time: React StrictMode (dev) calls start() twice, and concurrent requests can both hang in some browsers.
      if (!pending.current || pendingKey.current !== deviceId) {
        pendingKey.current = deviceId;
        pending.current = navigator.mediaDevices.getUserMedia({ video: deviceId ? { deviceId: { exact: deviceId }, ...size } : size, audio: false })
          .catch((e: DOMException) => {   // a remembered camera that is gone: fall back to the default one
            if (deviceId && e.name === "OverconstrainedError") { saveDevice(null); return navigator.mediaDevices.getUserMedia({ video: size, audio: false }); }
            throw e;
          }).finally(() => { pending.current = null; });
      }
      const stream = await pending.current;
      if (!want.current) { if (!streamRef.current) stream.getTracks().forEach((t) => t.stop()); return; }   // stopped while waiting
      if (streamRef.current) return;                                                                         // another start() already attached it
      streamRef.current = stream;
      const track = stream.getVideoTracks()[0];
      retries.current = 0;
      track?.addEventListener("ended", () => {
        if (streamRef.current !== stream) return;                 // an old stream that was already replaced or stopped
        streamRef.current = null; stream.getTracks().forEach((t) => t.stop());
        setStatus("error"); setResult(null); setTrackQuality(null);
        // Always-on: a dropped camera (USB/phone blip) is retried a few times before asking the user to press Start.
        if (want.current && retries.current < MAX_RETRIES) {
          retries.current++; setDetail(`The camera was disconnected. Reconnecting (attempt ${retries.current} of ${MAX_RETRIES})…`);
          retryTimer.current = window.setTimeout(() => { if (want.current && !streamRef.current) void start(track.getSettings().deviceId ?? deviceId, false); }, RETRY_MS);
        } else setDetail("The camera was disconnected. Press Start camera to reconnect.");
      });
      if (videoRef.current) { videoRef.current.srcObject = stream; await videoRef.current.play().catch(() => undefined); }
      setActive({ id: track?.getSettings().deviceId ?? null, label: track?.label ?? "" });
      sessionRef.current = newSession(); completionsRef.current = []; setProcFps(null);
      qualityRef.current = createTrackQuality(); setTrackQuality(null);
      setStatus("on");
      await listDevices();
      // Automatic choice only (nothing remembered): this project's input is DroidCam (phone over USB), so use it whenever it is listed.
      if (auto && !deviceId && !DROIDCAM.test(track?.label ?? "")) {
        const droid = (await navigator.mediaDevices.enumerateDevices()).find((d) => d.kind === "videoinput" && DROIDCAM.test(d.label));
        if (droid) { stream.getTracks().forEach((t) => t.stop()); streamRef.current = null; want.current = true; await start(droid.deviceId, false); }
      }
    } catch (e) {
      if (!want.current) return;
      const name = (e as DOMException).name;
      setStatus(name === "NotAllowedError" || name === "SecurityError" ? "denied" : "error");
      setDetail(name === "NotFoundError" ? "No camera was found." : name === "NotReadableError" ? "The camera is in use by another application." : null);
    }
  }, [listDevices]);

  /** Pick a camera explicitly; the choice is remembered. */
  const choose = useCallback(async (id: string) => { saveDevice(id); stop(false); await start(id, false); }, [start, stop]);

  useEffect(() => {
    if (!wasSwitchedOff()) void start();
    const onChange = () => void listDevices();
    navigator.mediaDevices?.addEventListener?.("devicechange", onChange);
    return () => { navigator.mediaDevices?.removeEventListener?.("devicechange", onChange); stop(false); };
  }, [start, stop, listDevices]);

  // StrictMode can remount the video element while getUserMedia is resolving;
  // attach the already-running stream once the element is back in the DOM.
  useEffect(() => {
    if (status !== "on") return;
    let alive = true, tries = 0;
    const attach = () => {
      if (!alive) return;
      const v = videoRef.current, stream = streamRef.current;
      if (v && stream) {
        if (v.srcObject !== stream) v.srcObject = stream;
        void v.play().catch(() => undefined);
        return;
      }
      if (tries++ < 20) requestAnimationFrame(attach);
    };
    attach();
    return () => { alive = false; };
  }, [status]);

  // Detection + tracking loop: preview ticks every second, but analysis requests
  // are cadence-gated (A1: ANALYZE_EVERY_MS) and motion-gated (A4), then
  // auto-paused on quota errors. Sequential by design: a slow backend delays
  // the next frame instead of queueing overlapping requests.
  useEffect(() => {
    if (status !== "on" || !backendConfigured) return;
    let alive = true, timer = 0, busy = false;
    const ctl = new AbortController();
    const grab = document.createElement("canvas");
    const scratch = document.createElement("canvas");
    const small = document.createElement("canvas");
    small.width = MOTION_SMALL[0]; small.height = MOTION_SMALL[1];
    smallRef.current = small;
    const moving = (): boolean => {
      const sg = small.getContext("2d", { willReadFrequently: true });
      if (!sg) return true;
      sg.drawImage(grab, 0, 0, small.width, small.height);
      const px = sg.getImageData(0, 0, small.width, small.height).data;
      const gray = new Uint8Array(px.length / 4);
      for (let i = 0, j = 0; i < px.length; i += 4, j++) gray[j] = (px[i] * 299 + px[i + 1] * 587 + px[i + 2] * 114) / 1000;
      const prev = prevSmallRef.current;
      prevSmallRef.current = gray;
      if (!prev || prev.length !== gray.length) return true;   // first frame: always analyse
      let sum = 0, changed = 0;
      for (let i = 0; i < gray.length; i++) {
        const d = Math.abs(gray[i] - prev[i]);
        sum += d;
        if (d >= MOTION_THRESH) changed++;
      }
      return sum / gray.length >= MOTION_THRESH || changed / gray.length >= MOTION_FRAC;
    };
    const sendOne = async (force = false) => {
      const v = videoRef.current;
      if (!alive || !v || v.videoWidth <= 0 || document.hidden) return;
      if (busy) return;
      busy = true;
      try {
        // The frame sent is the processed frame (rotate+crop): captures and the
        // preview canvas then match the model input one-to-one.
        if (!drawProcessed(v, grab, rotateRef.current, cropRef.current, scratch)) return;
        const elapsed = Date.now() - lastSentRef.current;
        if (!force && MOTION_ON) {
          const active = moving();
          if (!active && elapsed < MOTION_KEEPALIVE_MS) return;   // unchanged scene: save a call
        }
        const blob = await new Promise<Blob | null>((res) => grab.toBlob(res, "image/jpeg", 0.8));
        if (blob && alive) {
          try {
            const r = await trackFrame(blob, sessionRef.current || "default", ctl.signal);
            if (!alive) return;
            // Cap detections and tracks to max 2 fishes as requested
            const MAX_FISH = 2;
            if (r.detections && r.detections.length > MAX_FISH) {
              r.detections = [...r.detections].sort((a, b) => (b.confidence ?? 0) - (a.confidence ?? 0)).slice(0, MAX_FISH);
              r.count = r.detections.length;
            }
            if (r.tracks && r.tracks.length > MAX_FISH) {
              r.tracks = [...r.tracks].slice(0, MAX_FISH);
            }
            const now = Date.now();
            setResult(r); setReceivedAt(now); setInferError(null);
            if (TRACK_CONF) setTrackQuality(qualityRef.current?.update(r.tracks ?? []).frame ?? null);
            cooldownRef.current = null; setCooldownUntil(null);
            lastSentRef.current = now;
            const done = [...completionsRef.current, now].slice(-FPS_WINDOW);
            completionsRef.current = done;
            if (done.length >= 2) {
              const spanS = (done[done.length - 1] - done[0]) / 1000;
              if (spanS > 0) setProcFps((done.length - 1) / spanS);
              const gaps = done.slice(1).map((t, i) => t - done[i]).sort((a, b) => a - b);
              setCadenceMs(gaps[Math.floor(gaps.length / 2)]);
            }
            // A2: keep the two latest results for box interpolation; A3: hold
            // confirmed tracks for <=2 analysis cycles after they disappear.
            snapsRef.current = [...snapsRef.current, { t: now, result: r }].slice(-2);
            const next = new Map<number, Ghost>();
            for (const tr of r.tracks ?? []) {
              if (tr.confirmed !== false && tr.box && tr.static !== true) next.set(tr.id, { box: tr.box, t: now, misses: 0, confidence: tr.confidence });
            }
            ghostsRef.current.forEach((g, id) => {
              if (!next.has(id)) {
                const misses = g.misses + 1;
                if (misses <= GRACE_CYCLES) next.set(id, { ...g, misses });
              }
            });
            ghostsRef.current = next;
            setHistory((h) => [...h, { t: now, count: r.count }].slice(-120));
          } catch (e) {
            if ((e as Error).name !== "AbortError" && alive) {
              const msg = (e as Error).message;
              setInferError(friendlyLiveError(msg)); setResult(null); setTrackQuality(null);
              if (/429|quota|rate limit|exhausted/i.test(msg)) {
                const until = Date.now() + QUOTA_PAUSE_MS;   // stop hammering; resume automatically
                cooldownRef.current = until; setCooldownUntil(until);
              }
            }
          }
        }
      } finally {
        busy = false;
      }
    };
    requestRef.current = sendOne;
    const tick = async () => {
      if (!alive) return;
      const paused = cooldownRef.current !== null && Date.now() < cooldownRef.current;
      if (!paused && Date.now() - lastSentRef.current >= ANALYZE_EVERY_MS) await sendOne();
      if (alive) timer = window.setTimeout(tick, INTERVAL_MS);
    };
    void tick();
    return () => { alive = false; clearTimeout(timer); ctl.abort(); requestRef.current = null; };
  }, [status]);

  /** On-demand single-frame analysis (bypasses cadence and the motion gate; still shows quota errors honestly). */
  const analyzeNow = useCallback(() => { void requestRef.current?.(true); }, []);

  // Preview: draw the live video through the transform every animation frame.
  // Rotate/crop come from refs, so changing them repaints immediately.
  useEffect(() => {
    if (status !== "on") return;
    if (!scratchRef.current) scratchRef.current = document.createElement("canvas");
    let raf = 0;
    const draw = () => {
      const v = videoRef.current, p = previewRef.current;
      if (v && p) drawProcessed(v, p, rotateRef.current, cropRef.current, scratchRef.current!);
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [status]);

  // Draw model output over the processed preview at animation-frame rate.
  // Confirmed tracks are interpolated between the last two analyses (A2) so the
  // glass box glides with the fish instead of jumping every 4 s; tracks dropped
  // by the backend are held for two cycles, dimmed and dashed (A3); unconfirmed
  // tracks stay dashed and faded (C2). All coordinates are normalized 0-1.
  useEffect(() => {
    if (status !== "on") return;
    let raf = 0, frames = 0, windowStart = performance.now();
    const draw = () => {
      const c = overlayRef.current, p = previewRef.current;
      const now = performance.now();
      frames++;
      if (now - windowStart >= 1000) { setDrawFps(Math.round((frames * 1000) / (now - windowStart))); frames = 0; windowStart = now; }
      if (c) {
        const w = p?.width || 640, h = p?.height || 360;
        if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
        const g = c.getContext("2d");
        if (g) {
          g.clearRect(0, 0, c.width, c.height);
          const snaps = snapsRef.current;
          const cur = snaps[snaps.length - 1];
          if (cur) {
            const prev = snaps.length > 1 ? snaps[snaps.length - 2] : null;
            const prevBoxes = new Map<number, Box>();
            for (const tr of prev?.result.tracks ?? []) if (tr.box) prevBoxes.set(tr.id, tr.box);
            const live = cur.result.tracks ?? [];
            const qualityMap: Map<number, TrackQuality> | null = TRACK_CONF ? qualityRef.current?.latest() ?? null : null;
            const lowQuality = (track: (typeof live)[number]) => qualityMap?.get(track.id)?.band === "low";
            const confirmed = live.filter((t) => t.confirmed !== false && t.box && t.static !== true && !lowQuality(t));
            const tentative = live.filter((t) => (t.confirmed === false || lowQuality(t)) && t.box);
            const statics = live.filter((t) => t.static === true && t.box);
            // Clamp the interpolation factor: at most 30% extrapolation past the
            // newest snapshot, never backwards past the older one.
            const alpha = prev ? Math.max(0, Math.min(1.3, (Date.now() - prev.t) / Math.max(1, cur.t - prev.t))) : 1;
            g.lineWidth = Math.max(2, c.width / 400); g.font = `${Math.max(12, c.width / 55)}px sans-serif`;
            const drawn: Box[] = [];
            for (const tr of confirmed) {
              const b = prevBoxes.has(tr.id) ? lerpBox(prevBoxes.get(tr.id)!, tr.box!, alpha) : tr.box!;
              drawn.push(tr.box!);
              const quality = qualityMap?.get(tr.id);
              const tone = tr.behavior?.tone ?? "ok";
              const strokeCol = tone === "bad" ? "#ef4444" : tone === "warn" ? "#f59e0b" : tone === "info" ? "#38bdf8" : "#10b981";
              const bgCol = tone === "bad" ? "rgba(220, 38, 38, 0.88)" : tone === "warn" ? "rgba(217, 119, 6, 0.88)" : tone === "info" ? "rgba(2, 132, 199, 0.88)" : "rgba(16, 185, 129, 0.88)";

              g.strokeStyle = strokeCol;
              g.globalAlpha = 1;
              const d = cur.result.detections.find((dd) => near(dd.box, tr.box!));
              if (d?.outline && d.outline.length > 2) {
                const [cx0, cy0] = center(tr.box!), [cx1, cy1] = center(b);
                const dx = cx1 - cx0, dy = cy1 - cy0;
                g.beginPath();
                d.outline.forEach(([x, y], i) => (i ? g.lineTo((x + dx) * c.width, (y + dy) * c.height) : g.moveTo((x + dx) * c.width, (y + dy) * c.height)));
                g.closePath(); g.globalAlpha = 0.25; g.fillStyle = strokeCol; g.fill(); g.globalAlpha = 1; g.stroke();
              }
              g.strokeRect(b[0] * c.width, b[1] * c.height, (b[2] - b[0]) * c.width, (b[3] - b[1]) * c.height);

              // Behavior-aware badge pill above fish box
              const behLabel = tr.behavior?.label ? `Fish #${tr.id} · ${tr.behavior.label}` : formatQualityLabel(quality, tr.confidence, TRACK_CONF);
              const textMetrics = g.measureText(behLabel);
              const textW = textMetrics.width;
              const textH = Math.max(12, c.width / 55);
              const padX = 6, padY = 3;
              const pillX = b[0] * c.width;
              const pillY = Math.max(textH + padY * 2, b[1] * c.height - 4);

              g.fillStyle = bgCol;
              g.fillRect(pillX, pillY - textH - padY, textW + padX * 2, textH + padY * 2);
              g.fillStyle = "#ffffff";
              g.fillText(behLabel, pillX + padX, pillY - 1);
            }
            for (const tr of statics) {
              const b = tr.box!;
              g.strokeStyle = g.fillStyle = "#94a3b8"; g.globalAlpha = 0.35; g.setLineDash([3, 5]);
              g.strokeRect(b[0] * c.width, b[1] * c.height, (b[2] - b[0]) * c.width, (b[3] - b[1]) * c.height);
              g.setLineDash([]); g.globalAlpha = 1;
            }
            ghostsRef.current.forEach((gh, id) => {
              if (live.some((t) => t.id === id)) return;
              g.strokeStyle = g.fillStyle = "#19c8f2"; g.globalAlpha = 0.28; g.setLineDash([4, 5]);
              g.strokeRect(gh.box[0] * c.width, gh.box[1] * c.height, (gh.box[2] - gh.box[0]) * c.width, (gh.box[3] - gh.box[1]) * c.height);
              g.setLineDash([]); g.globalAlpha = 1;
            });
            for (const d of cur.result.detections) {
              const [x1, y1, x2, y2] = d.box;
              if (drawn.some((b) => near(b, d.box)) || statics.some((t) => near(t.box!, d.box))) continue;   // already drawn as a track
              const isTentative = tentative.some((t) => near(t.box!, d.box, 0.03));
              g.strokeStyle = g.fillStyle = "#19c8f2";
              g.globalAlpha = isTentative ? 0.55 : 1;
              if (isTentative) g.setLineDash([6, 4]);
              if (d.outline && d.outline.length > 2) {
                g.beginPath(); d.outline.forEach(([x, y], i) => (i ? g.lineTo(x * c.width, y * c.height) : g.moveTo(x * c.width, y * c.height))); g.closePath();
                g.globalAlpha *= 0.25; g.fill(); g.globalAlpha = isTentative ? 0.55 : 1; g.stroke();
              }
              g.strokeRect(x1 * c.width, y1 * c.height, (x2 - x1) * c.width, (y2 - y1) * c.height);
              const matched = live.find((t) => t.box && near(t.box, d.box, 0.03));
              const quality = matched ? qualityMap?.get(matched.id) : undefined;
              g.fillText(formatQualityLabel(quality, d.confidence, TRACK_CONF), x1 * c.width + 3, Math.max(14, y1 * c.height - 4));
              g.setLineDash([]); g.globalAlpha = 1;
            }
          }
        }
      }
      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => { cancelAnimationFrame(raf); setDrawFps(null); };
  }, [status]);

  return { videoRef, previewRef, overlayRef, status, detail, result, receivedAt, inferError, history, devices, active, procFps, cadenceMs, drawFps, motionOn: MOTION_ON, cooldownUntil, trackQuality, analyzeNow, analyzeEveryMs: ANALYZE_EVERY_MS, rotate, crop, setRotate, setCrop, choose, start: () => start(), stop: () => stop(true) };
}
export type LiveCamera = ReturnType<typeof useLiveCamera>;
