import BehaviorPanel from "./BehaviorPanel";

export default function BehaviorPage({ backendConnected }: { backendConnected: boolean }) {
  return (
    <div className="flex flex-col gap-4">
      <p className="rounded-card border border-[var(--border-subtle)] bg-[var(--surface-1)] p-3 text-[11px] text-mute">
        Camera-derived behavior proxies only. These are not health diagnoses and are not calibrated against dissolved oxygen until a DO sensor is installed.
      </p>
      <BehaviorPanel backendConnected={backendConnected} />
    </div>
  );
}
