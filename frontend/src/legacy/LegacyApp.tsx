/**
 * P0 ROLLBACK SNAPSHOT (AMENDMENT A2/A3).
 *
 * This is the pre-rebuild application tree, kept byte-for-byte in behaviour and
 * lazy-loaded so it never inflates the v2 bundle. `VITE_UI_THEME=legacy` renders
 * this file. Do NOT delete until P5 owner sign-off.
 *
 * As later phases move files into src/legacy/, update the imports here so the
 * rollback keeps pointing at the frozen copies rather than the rebuilt ones.
 */
import { useCallback, useEffect, useState } from "react";
import { MotionConfig } from "framer-motion";
import Shell, { LEGACY_PAGES as PAGES, type LegacyPage as Page } from "./ShellLegacy";
import Toasts, { type ToastItem } from "../components/Toasts";
import LoginGate from "../components/LoginGate";
import Overview from "../sections/Overview";
import SensorsPage from "../sections/SensorsPage";
import WaterPage from "../sections/WaterPage";
import AlertsPage from "../sections/AlertsPage";
import PredictionsPage from "../sections/PredictionsPage";
import BehaviorPage from "../sections/BehaviorPage";
import Monitoring from "./Monitoring";
import { SENSOR_KEYS } from "../services/thingspeak";
import { cameraStatus, modelStatus, thingSpeakStatus } from "../sections/StatusPanels";
import { AUTH_EVENT, AUTH_USER_KEY, authLogout, authMe } from "../services/api";
import type { AuthUser } from "../types";
import { useAnalysis, type Notify } from "../hooks/useAnalysis";
import { useBackendState } from "../hooks/useBackendState";
import { useSensors } from "../hooks/useSensors";
import { useLiveCamera } from "../hooks/useLiveCamera";

const pageFromHash = (): Page => {
  const id = location.hash.replace(/^#\/?/, "");
  return (PAGES.some((p) => p.id === id) ? id : "overview") as Page;
};

export default function LegacyApp() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    let alive = true;
    const clear = () => { localStorage.removeItem(AUTH_USER_KEY); setUser(null); };
    void authMe().then((current) => {
      if (!alive) return;
      if (current) {
        localStorage.setItem(AUTH_USER_KEY, JSON.stringify(current));
        setUser(current);
      } else {
        localStorage.removeItem(AUTH_USER_KEY);
      }
      setChecking(false);
    });
    window.addEventListener(AUTH_EVENT, clear);
    return () => { alive = false; window.removeEventListener(AUTH_EVENT, clear); };
  }, []);

  if (checking) {
    return (
      <div className="grid min-h-screen place-items-center bg-surface">
        <p className="text-sm text-mute">Checking your session...</p>
      </div>
    );
  }

  if (!user) {
    return <LoginGate onAuthenticated={(next) => {
      localStorage.setItem(AUTH_USER_KEY, JSON.stringify(next));
      setUser(next);
    }} />;
  }

  return <FarmApp user={user} onLogout={async () => { await authLogout(); setUser(null); }} />;
}

function FarmApp({ user, onLogout }: { user: AuthUser; onLogout: () => void }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [page, setPageState] = useState<Page>(pageFromHash);
  const { state: backend, modelAvailable, visionBackend } = useBackendState();
  const sensors = useSensors();
  const cam = useLiveCamera();

  const setPage = (next: Page) => {
    setPageState(next);
    history.replaceState(null, "", `#/${next}`);
    window.scrollTo(0, 0);
  };
  useEffect(() => {
    const f = () => setPageState(pageFromHash());
    window.addEventListener("hashchange", f);
    return () => window.removeEventListener("hashchange", f);
  }, []);

  const notify: Notify = useCallback((kind, message) => {
    const t = { id: Date.now() + Math.random(), kind, message };
    setToasts((x) => [...x, t]);
    window.setTimeout(() => setToasts((x) => x.filter((i) => i.id !== t.id)), 5000);
  }, []);
  const analysis = useAnalysis(notify);

  const integ = { backendConnected: backend === "connected", modelAvailable, visionBackend, camera: cam.status, inferring: cam.result !== null };
  const status = [thingSpeakStatus(sensors), cameraStatus(cam.status), modelStatus(integ)];
  const lastReadingAt = sensors.readings ? Math.max(0, ...SENSOR_KEYS.map((k) => sensors.readings![k].at(-1)?.t ?? 0)) : 0;

  return (
    <MotionConfig reducedMotion="user">
      <Shell page={page} setPage={setPage} status={status} fetchedAt={sensors.fetchedAt} lastReadingAt={lastReadingAt || null} pollSeconds={sensors.pollMs / 1000}
        canRefresh={!sensors.problem} busy={sensors.busy} onRefresh={() => void sensors.refresh()} user={user} onLogout={onLogout}>
        <div className="mx-auto max-w-[1536px]">
          {page === "overview" && <Overview />}
          {page === "sensors" && <SensorsPage s={sensors} />}
          {page === "water" && <WaterPage jobId={analysis.jobId} notify={notify} />}
          {page === "alerts" && <AlertsPage user={user} />}
          {page === "predictions" && <PredictionsPage />}
          {page === "behavior" && <BehaviorPage backendConnected={backend === "connected"} />}
          {/* Always mounted so the camera and detection loop keep running across pages. */}
          <div hidden={page !== "monitoring"}>
              <Monitoring cam={cam} a={analysis} modelAvailable={modelAvailable} backendConnected={backend === "connected"} visionBackend={visionBackend} />
          </div>
          <p className="mt-4 px-1 text-center text-[11px] text-mute">
            Experimental research tool. Thresholds are provisional and unvalidated; detection and tracking quality vary by tank, lighting and camera; no fish-health diagnosis or mortality prediction is provided.
          </p>
        </div>
      </Shell>
      <Toasts items={toasts} dismiss={(id) => setToasts((x) => x.filter((t) => t.id !== id))} />
    </MotionConfig>
  );
}
