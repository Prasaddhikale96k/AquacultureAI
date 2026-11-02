import { motion } from "framer-motion";
import type { useAnalysis } from "../hooks/useAnalysis";
import UploadPanel from "./UploadPanel";
import ResultsPanel from "./ResultsPanel";

export default function VideoAnalysis({ a }: { a: ReturnType<typeof useAnalysis> }) {
  return (
    <motion.section id="video-analysis" aria-label="Video analysis" className="glass grid grid-cols-[minmax(0,1fr)] gap-5 rounded-2xl p-4 lg:grid-cols-[minmax(300px,0.8fr)_minmax(0,1.6fr)] lg:p-5"
      initial={{ opacity: 0, y: 14 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ duration: 0.4 }}>
      <UploadPanel meta={a.meta} hasFile={a.file !== null} phase={a.phase} stage={a.stage} progress={a.progress} error={a.error}
        onSelect={a.select} onClear={a.clear} onAnalyze={a.analyze} onCancel={a.cancel} />
      <ResultsPanel meta={a.meta} hasFile={a.file !== null} phase={a.phase} result={a.result} error={a.error} />
    </motion.section>
  );
}
