import WaterAssessment from "./WaterAssessment";
import RiskPanel from "./RiskPanel";

export default function WaterPage({ jobId, notify }: { jobId: string | null; notify: (k: "success" | "error" | "info", m: string) => void }) {
  return (
    <div className="flex flex-col gap-4">
      <RiskPanel jobId={jobId} />
      <WaterAssessment jobId={jobId} notify={notify} />
    </div>
  );
}
