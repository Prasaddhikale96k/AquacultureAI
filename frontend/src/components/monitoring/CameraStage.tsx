import type { RefObject } from "react";
import { CameraOff } from "lucide-react";
import type { CameraStatus } from "../../config/alerts";

const WHY: Record<CameraStatus, string> = {
  denied: "Camera permission was denied. Allow the camera for this site in the browser, then press Start camera.",
  unsupported: "This browser or page cannot access a camera. Use http://localhost or HTTPS.",
  error: "The camera could not be opened or was disconnected.",
  off: "The camera is switched off. Press Start camera to resume live detection.",
  starting: "Waiting for the camera…",
  on: "",
};

export default function CameraStage({ videoRef, previewRef, overlayRef, status, detail }: {
  videoRef: RefObject<HTMLVideoElement | null>;
  previewRef: RefObject<HTMLCanvasElement | null>;
  overlayRef: RefObject<HTMLCanvasElement | null>;
  status: CameraStatus;
  detail?: string | null;
}) {
  return (
    <div className="relative overflow-hidden rounded-card border border-[var(--border-subtle)] bg-[var(--surface-0)]" style={{ aspectRatio: "16 / 9" }}>
      <video ref={videoRef} muted playsInline aria-label="Live camera" className="pointer-events-none absolute h-px w-px opacity-0" />
      <canvas ref={previewRef} aria-hidden className={`h-full w-full ${status === "on" ? "" : "invisible"}`} />
      <canvas ref={overlayRef} aria-hidden className="pointer-events-none absolute inset-0 h-full w-full" />
      {status !== "on" && (
        <div className="absolute inset-0 grid place-items-center p-4 text-center text-[var(--text-secondary)]">
          <div>
            <CameraOff className="mx-auto mb-2 h-8 w-8 text-[var(--text-secondary)]" />
            <p className="font-medium text-[var(--text-primary)]">Camera feed not connected</p>
            <p className="mt-1 max-w-sm text-xs text-[var(--text-secondary)]">{detail ?? WHY[status]}</p>
          </div>
        </div>
      )}
    </div>
  );
}
