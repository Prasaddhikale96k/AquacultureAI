import type { VideoMeta } from "../types";

/** Reads real metadata and a first-frame poster in the browser. Fields stay undefined if the browser cannot decode the file. */
export function readVideoMeta(file: File): Promise<VideoMeta> {
  const base: VideoMeta = { name: file.name, sizeBytes: file.size };
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const video = document.createElement("video");
    video.preload = "metadata";
    video.muted = true;
    const done = (m: VideoMeta) => { URL.revokeObjectURL(url); resolve(m); };
    const timer = window.setTimeout(() => done(base), 8000);
    video.onerror = () => { clearTimeout(timer); done(base); };
    video.onloadedmetadata = () => {
      base.durationSec = Number.isFinite(video.duration) ? video.duration : undefined;
      base.width = video.videoWidth;
      base.height = video.videoHeight;
      video.currentTime = Math.min(0.5, (video.duration || 1) / 2);
    };
    video.onseeked = () => {
      clearTimeout(timer);
      const canvas = document.createElement("canvas");
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      canvas.getContext("2d")?.drawImage(video, 0, 0);
      canvas.toBlob((blob) => {
        URL.revokeObjectURL(url);
        resolve({ ...base, posterUrl: blob ? URL.createObjectURL(blob) : undefined });
      }, "image/jpeg", 0.85);
    };
    video.src = url;
  });
}

export const fmtSize = (b: number) => (b >= 1e9 ? `${(b / 1e9).toFixed(2)} GB` : `${(b / 1e6).toFixed(1)} MB`);
export const fmtDuration = (s?: number) => (s === undefined ? "—" : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}`);
