import { useCallback, useEffect, useState } from "react";
import { Bot, TriangleAlert } from "lucide-react";
import type { ExplanationResponse } from "../types";
import { backendConfigured, getExplanation } from "../services/api";
import { Badge } from "../components/ui";

const LISTS: { key: "risk_factors" | "supporting_evidence" | "recommended_checks" | "missing_information" | "limitations"; title: string }[] = [
  { key: "risk_factors", title: "Risk factors" },
  { key: "supporting_evidence", title: "Supporting evidence" },
  { key: "recommended_checks", title: "Recommended checks" },
  { key: "missing_information", title: "Missing information" },
  { key: "limitations", title: "Limitations" },
];

/**
 * Section E — structured Gemini explanation of the deterministic assessment.
 * User-triggered only, cached per evidence, cooldown-guarded server-side.
 * Clearly labeled LLM-generated; never overrides the risk status.
 */
export default function AiAdvisor({ tankId, jobId }: { tankId: string; jobId: string | null }) {
  const [exp, setExp] = useState<ExplanationResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const explain = useCallback(async () => {
    if (!tankId) return;
    setLoading(true); setError(null);
    try {
      setExp(await getExplanation(tankId, jobId));
    } catch (e) {
      const err = e as Error & { retryAfterS?: number };
      setError(err.retryAfterS
        ? `Fresh evidence was submitted within the cooldown — retry in ~${err.retryAfterS}s. The last explanation is kept below if present.`
        : err.message);
    } finally {
      setLoading(false);
    }
  }, [tankId, jobId]);

  useEffect(() => { setExp(null); setError(null); }, [tankId, jobId]);

  return (
    <section aria-label="AI explanation" className="rounded-xl border border-line/70 bg-surface/40 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-mute">
          <Bot className="h-3.5 w-3.5" /> AI explanation (Gemini)
        </h3>
        {exp && (
          <>
            <Badge tone="ok">{exp.provider === "groq" ? "Groq" : "Gemini"} · {exp.model}</Badge>
            {exp.cached && <Badge tone="info">Cached · {new Date(exp.generated_at).toLocaleTimeString()}</Badge>}
            {exp.risk_status && <Badge tone="mute">Risk: {exp.risk_status}</Badge>}
          </>
        )}
        <button
          onClick={() => void explain()}
          disabled={!backendConfigured || !tankId || loading}
          className="ml-auto rounded-lg border border-cyan/40 px-2.5 py-1 text-xs font-medium text-cyan disabled:cursor-not-allowed disabled:opacity-40"
        >
          {loading ? "Explaining…" : exp ? "Re-explain" : "Explain with AI"}
        </button>
      </div>

      {!backendConfigured ? (
        <p className="mt-2 text-xs text-mute">Connect the backend to use the AI explanation.</p>
      ) : !tankId ? (
        <p className="mt-2 text-xs text-mute">Save water measurements for a tank first — the AI only explains real screening results, never invents them.</p>
      ) : null}

      {error && (
        <p role="alert" className="mt-2 flex items-start gap-1.5 text-xs text-bad">
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />{error}
        </p>
      )}

      {exp && (
        <div className="mt-2 space-y-2 text-xs">
          <p className="leading-relaxed"><span className="font-medium">Summary: </span>{exp.summary}</p>
          <p className="leading-relaxed text-mute">{exp.water_quality_explanation}</p>
          <p className="leading-relaxed text-mute">{exp.behavior_observations}</p>
          {LISTS.map(({ key, title }) => exp[key].length > 0 && (
            <div key={key}>
              <p className="font-medium text-cyan">{title}</p>
              <ul className="ml-4 list-disc text-mute">{exp[key].map((x) => <li key={x}>{x}</li>)}</ul>
            </div>
          ))}
          <p className="text-[10px] text-mute">{exp.disclaimer} Generated {new Date(exp.generated_at).toLocaleString()}.</p>
        </div>
      )}
    </section>
  );
}
