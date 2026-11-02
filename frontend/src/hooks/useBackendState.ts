import { useEffect, useState } from "react";
import type { BackendState } from "../types";
import { backendConfigured, checkHealth } from "../services/api";

/** "connected" is reported only after /health answered successfully. */
export function useBackendState(): { state: BackendState; modelAvailable: boolean; visionBackend: "api" | "yolo" | null } {
  const [state, setState] = useState<BackendState>(backendConfigured ? "connecting" : "demo");
  const [modelAvailable, setModel] = useState(false);
  const [visionBackend, setVision] = useState<"api" | "yolo" | null>(null);
  useEffect(() => {
    if (!backendConfigured) return;
    let alive = true;
    const ping = () => checkHealth().then(
      (h) => { if (alive) { setState("connected"); setModel(h.modelAvailable); setVision(h.visionBackend ?? null); } },
      () => alive && setState("unreachable"),
    );
    ping();
    const id = window.setInterval(ping, 15000);
    return () => { alive = false; clearInterval(id); };
  }, []);
  return { state, modelAvailable, visionBackend };
}
