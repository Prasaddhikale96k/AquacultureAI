import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { AnimatePresence, MotionConfig, motion } from "framer-motion";
import Shell, { PAGES, type Page } from "./components/Shell";
import Toasts, { type ToastItem } from "./components/Toasts";
import Login from "./pages/Login";
import Register from "./pages/Register";
import { ProtectedRoute, SessionLoader } from "./routes/ProtectedRoute";
import { bootstrapAuth, useAuth } from "./state/authStore";
import Overview from "./sections/Overview";
import { SENSOR_KEYS } from "./services/thingspeak";
import { cameraStatus, modelStatus, thingSpeakStatus } from "./sections/StatusPanels";
import type { AuthUser } from "./types";
import { useAnalysis, type Notify } from "./hooks/useAnalysis";
import { useBackendState } from "./hooks/useBackendState";
import { useSensors } from "./hooks/useSensors";
import { useLiveCamera } from "./hooks/useLiveCamera";

const SensorsPage = lazy(() => import("./sections/SensorsPage"));
const WaterPage = lazy(() => import("./sections/WaterPage"));
const AlertsPage = lazy(() => import("./sections/AlertsPage"));
const PredictionsPage = lazy(() => import("./sections/PredictionsPage"));
const BehaviorPage = lazy(() => import("./sections/BehaviorPage"));
const Monitoring = lazy(() => import("./pages/Monitoring"));

const PageFallback = () => (
  <div className="grid gap-4" aria-busy="true" aria-label="Loading page">
    <div className="h-24 animate-pulse rounded-card border border-[var(--border-subtle)] bg-[var(--surface-1)]" />
    <div className="h-64 animate-pulse rounded-card border border-[var(--border-subtle)] bg-[var(--surface-1)]" />
  </div>
);

const pageFromHash = (): Page => {
  const id = location.hash.replace(/^#\/?/, "");
  return (PAGES.some((p) => p.id === id) ? id : "overview") as Page;
};

export default function App() {
  const { user, status, logout } = useAuth();
  const [hash, setHash] = useState(() => location.hash);

  useEffect(() => {
    void bootstrapAuth();
    const onHashChange = () => setHash(location.hash);
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const route = hash.replace(/^#\/?/, "");
  const reduceMotion = import.meta.env.DEV && new URLSearchParams(location.search).get("motion") === "off" ? "always" : "user";

  if (status === "checking") return <SessionLoader />;

  return (
    <MotionConfig reducedMotion={reduceMotion}>
      {user ? (
        <ProtectedRoute fallback={<Login />}>
          <FarmApp user={user} onLogout={() => void logout()} />
        </ProtectedRoute>
      ) : route === "register" ? (
        <Register />
      ) : (
        <Login />
      )}
    </MotionConfig>
  );
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
    <>
      <Shell page={page} setPage={setPage} status={status} fetchedAt={sensors.fetchedAt} lastReadingAt={lastReadingAt || null} pollSeconds={sensors.pollMs / 1000}
        canRefresh={!sensors.problem} busy={sensors.busy} onRefresh={() => void sensors.refresh()} user={user} onLogout={onLogout}>
        <div>
          <Suspense fallback={<PageFallback />}>
            <AnimatePresence mode="wait" initial={false}>
              <motion.div key={page} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.2, ease: "easeOut" }}>
                {page === "overview" && <Overview onNavigate={setPage} />}
                {page === "sensors" && <SensorsPage s={sensors} />}
                {page === "water" && <WaterPage jobId={analysis.jobId} notify={notify} />}
                {page === "alerts" && <AlertsPage user={user} />}
                {page === "predictions" && <PredictionsPage />}
                {page === "behavior" && <BehaviorPage backendConnected={backend === "connected"} />}
              </motion.div>
            </AnimatePresence>
          </Suspense>
          {/* Always mounted so the camera and detection loop keep running across pages. */}
          <div hidden={page !== "monitoring"}>
            <Suspense fallback={<PageFallback />}>
              <Monitoring cam={cam} a={analysis} modelAvailable={modelAvailable} backendConnected={backend === "connected"} visionBackend={visionBackend} />
            </Suspense>
          </div>
          <p className="mt-4 px-1 text-center text-[11px] text-mute">
            Experimental research tool. Thresholds are provisional and unvalidated; detection and tracking quality vary by tank, lighting and camera; no fish-health diagnosis or mortality prediction is provided.
          </p>
        </div>
      </Shell>
      <Toasts items={toasts} dismiss={(id) => setToasts((x) => x.filter((t) => t.id !== id))} />
    </>
  );
}
