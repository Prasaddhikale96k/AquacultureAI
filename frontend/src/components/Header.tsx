import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Bell, Fish, Menu, UserRound, X } from "lucide-react";
import type { BackendState } from "../types";
import type { ToastItem } from "./Toasts";

export const NAV = [
  { id: "dashboard", label: "Dashboard" },
  { id: "video-analysis", label: "Video Analysis" },
  { id: "water-quality", label: "Water Quality" },
  { id: "assessment", label: "Assessment" },
  { id: "insights", label: "Insights" },
  { id: "history", label: "History" },
] as const;

const BACKEND: Record<BackendState, [string, string]> = {
  demo: ["Demo mode · backend not connected", "bg-warn"],
  connecting: ["Connecting to backend…", "bg-warn"],
  connected: ["Backend connected", "bg-ok"],
  unreachable: ["Backend unreachable", "bg-bad"],
};

export default function Header({ active, backend, modelAvailable, log }: { active: string; backend: BackendState; modelAvailable: boolean; log: ToastItem[] }) {
  const [menu, setMenu] = useState(false);
  const [bell, setBell] = useState(false);
  const bellRef = useRef<HTMLDivElement>(null);
  const [label, dot] = backend === "connected" && !modelAvailable ? ["Backend connected · model weights missing", "bg-warn"] : BACKEND[backend];

  useEffect(() => {
    const close = (e: MouseEvent) => bellRef.current && !bellRef.current.contains(e.target as Node) && setBell(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const links = NAV.map((n) => (
    <a key={n.id} href={`#${n.id}`} onClick={() => setMenu(false)} aria-current={active === n.id ? "true" : undefined}
      className={`rounded-lg px-3 py-1.5 text-sm transition-colors ${active === n.id ? "bg-cyan/15 text-cyan" : "text-mute hover:text-white"}`}>
      {n.label}
    </a>
  ));

  return (
    <header className="sticky top-0 z-40 border-b border-line/60 bg-abyss/80 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-[1536px] items-center gap-4 px-4 lg:px-6">
        <a href="#dashboard" className="flex items-center gap-2.5">
          <span className="grid h-8 w-8 place-items-center rounded-xl bg-gradient-to-br from-cyan to-brand"><Fish className="h-5 w-5 text-abyss" /></span>
          <span className="leading-tight">
            <span className="block text-[15px] font-semibold">Aquaculture<span className="text-cyan">AI</span></span>
            <span className="hidden text-[10px] text-mute xl:block">AI for Healthier Fish &amp; Sustainable Aquaculture</span>
          </span>
        </a>
        <nav className="ml-4 hidden items-center gap-1 lg:flex" aria-label="Sections">{links}</nav>
        <div className="ml-auto flex items-center gap-3">
          <span className="hidden items-center gap-2 text-xs text-mute md:flex" title="Backend status">
            <span className={`h-2 w-2 rounded-full ${dot}`} />{label}
          </span>
          <div ref={bellRef} className="relative">
            <button aria-label="Notifications" aria-expanded={bell} onClick={() => setBell((b) => !b)}
              className="relative grid h-9 w-9 place-items-center rounded-lg border border-line text-mute hover:text-white">
              <Bell className="h-4 w-4" />
              {log.length > 0 && <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-cyan" />}
            </button>
            <AnimatePresence>
              {bell && (
                <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                  className="glass absolute right-0 mt-2 w-72 rounded-xl p-3 text-sm">
                  <p className="mb-2 text-xs font-medium text-mute">This session</p>
                  {log.length === 0 ? <p className="text-mute">No notifications yet.</p> : (
                    <ul className="max-h-60 space-y-2 overflow-auto">{log.slice().reverse().map((n) => <li key={n.id}>{n.message}</li>)}</ul>
                  )}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
          <div className="hidden items-center gap-2 sm:flex">
            <span className="grid h-8 w-8 place-items-center rounded-full bg-surface text-mute"><UserRound className="h-4 w-4" /></span>
            <span className="text-xs leading-tight"><span className="block">Guest</span><span className="text-mute">No sign-in</span></span>
          </div>
          <button aria-label={menu ? "Close menu" : "Open menu"} aria-expanded={menu} onClick={() => setMenu((m) => !m)}
            className="grid h-9 w-9 place-items-center rounded-lg border border-line lg:hidden">
            {menu ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
          </button>
        </div>
      </div>
      <AnimatePresence>
        {menu && (
          <motion.nav initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden border-t border-line/60 lg:hidden" aria-label="Sections (mobile)">
            <div className="flex flex-col gap-1 p-3">
              {links}
              <a href="#video-analysis" onClick={() => setMenu(false)} className="mt-1 rounded-lg bg-brand px-3 py-2 text-center text-sm font-medium">Upload video</a>
            </div>
          </motion.nav>
        )}
      </AnimatePresence>
    </header>
  );
}
