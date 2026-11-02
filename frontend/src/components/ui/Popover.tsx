import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";

const FOCUSABLE = 'a[href], button:not([disabled]), select:not([disabled]), input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export default function Popover({ label, trigger, children, align = "start", className = "" }: {
  label: string;
  trigger: ReactNode;
  children: ReactNode;
  align?: "start" | "end";
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [side, setSide] = useState<"top" | "bottom">("bottom");
  const rootRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelId = useId();

  const close = useCallback(() => setOpen(false), []);
  const toggle = () => {
    if (!open && triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect();
      setSide(window.innerHeight - rect.bottom < 360 && rect.top > 360 ? "top" : "bottom");
    }
    setOpen((value) => !value);
  };

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) close();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        close();
        return;
      }
      if (event.key !== "Tab" || !panelRef.current) return;
      const nodes = Array.from(panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (nodes.length === 0) {
        event.preventDefault();
        panelRef.current.focus({ preventScroll: true });
        return;
      }
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    const frame = requestAnimationFrame(() => {
      const first = panelRef.current?.querySelector<HTMLElement>(FOCUSABLE);
      (first ?? panelRef.current)?.focus({ preventScroll: true });
    });
    return () => {
      cancelAnimationFrame(frame);
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
      if (panelRef.current?.contains(document.activeElement) || document.activeElement === document.body) triggerRef.current?.focus({ preventScroll: true });
    };
  }, [open, close]);

  return (
    <div ref={rootRef} className={`relative inline-flex ${className}`}>
      <button ref={triggerRef} type="button" aria-haspopup="dialog" aria-expanded={open} aria-controls={panelId}
        onClick={toggle}
        className="inline-flex h-9 items-center gap-2 rounded-nested border border-[var(--border-subtle)] bg-[var(--surface-1)] px-3 text-sm text-[var(--text-primary)] hover:bg-[var(--surface-2)]">
        {trigger}
      </button>
      <AnimatePresence>
        {open && (
          <motion.div ref={panelRef} id={panelId} role="dialog" aria-label={label} tabIndex={-1}
            initial={{ opacity: 0, scale: 0.96, y: side === "top" ? 4 : -4 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: side === "top" ? 4 : -4 }}
            transition={{ duration: 0.16, ease: "easeOut" }}
            style={{ transformOrigin: `${side === "top" ? "bottom" : "top"} ${align === "end" ? "right" : "left"}` }}
            className={`absolute z-50 max-h-[min(24rem,calc(100vh-6rem))] w-[min(20rem,calc(100vw-2rem))] overflow-y-auto rounded-card border border-[var(--border-subtle)] bg-[var(--surface-1)] p-3 text-left shadow-xl ${side === "top" ? "bottom-full mb-2" : "top-full mt-2"} ${align === "end" ? "right-0" : "left-0"}`}>
            {children}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
