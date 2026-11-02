import { motion } from "framer-motion";
import { Brain, Droplets, Radio, ScanSearch } from "lucide-react";
import type { BackendState } from "../types";

export default function Hero({ backend }: { backend: BackendState }) {
  const items = [
    { icon: ScanSearch, title: "AI Video Analysis", sub: "API vision (Groq/Gemini)", status: backend === "connected" ? "Backend connected" : "Needs backend" },
    { icon: Droplets, title: "Water Quality", sub: "Monitoring & Trends", status: "Historical data" },
    { icon: Brain, title: "Behavior Insights", sub: "Experimental", status: "Not validated" },
    { icon: Radio, title: "Real-time Sensors", sub: "ESP32 + ThingSpeak", status: "Not connected" },
  ];
  return (
    <section id="dashboard" className="grid items-center gap-5 py-4 lg:grid-cols-[1.1fr_1fr] lg:py-5">
      <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
        <h1 className="text-3xl font-bold leading-[1.1] tracking-tight sm:text-4xl xl:text-[40px]">
          Understand your<br /><span className="text-cyan">aquatic ecosystem</span>
        </h1>
        <p className="mt-3 max-w-xl text-sm text-mute sm:text-[15px]">
          Upload fish tank videos, analyze fish movement with AI, and monitor water quality for smarter and more sustainable aquaculture.
        </p>
      </motion.div>
      <ul className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        {items.map(({ icon: Icon, title, sub, status }, i) => (
          <motion.li key={title} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 + i * 0.07 }}
            className="rounded-2xl border border-line/70 bg-panel/50 p-3 backdrop-blur">
            <span className="mb-2 grid h-9 w-9 place-items-center rounded-full border border-cyan/30 bg-cyan/10 text-cyan"><Icon className="h-4 w-4" /></span>
            <p className="text-sm font-semibold leading-tight">{title}</p>
            <p className="text-xs text-mute">{sub}</p>
            <p className="mt-1.5 text-[11px] text-cyan/80">{status}</p>
          </motion.li>
        ))}
      </ul>
    </section>
  );
}
