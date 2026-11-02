import { useEffect, useRef } from "react";
import gsap from "gsap";
import { Fish, Waves } from "lucide-react";
import { useT } from "../i18n/LanguageProvider";
import { useReducedMotion } from "../motion/useReducedMotion";

const STATS = [
  { value: 6, labelKey: "auth.statParams" },
  { value: 5, labelKey: "auth.statLevels" },
  { value: 24, labelKey: "auth.statAdvisory" },
] as const;

/**
 * Frozen snapshot of the previous dark-only "deep-water" hero panel.
 * Retained here solely for the VITE_UI_THEME=legacy rollback path; do not
 * import from the default v2 tree. Copy of the former AuthCanvas.tsx.
 */
export function AuthHeroPanelDark() {
  const t = useT();
  const root = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();
  const still =
    import.meta.env.DEV && new URLSearchParams(window.location.search).get("motion") === "off";

  useEffect(() => {
    if (!root.current) return;
    const ctx = gsap.context(() => {
      const counters = gsap.utils.toArray<HTMLElement>("[data-counter]");
      if (reduced || still) {
        counters.forEach((el) => {
          el.textContent = el.dataset.counter ?? "0";
        });
        return;
      }

      const intro = gsap.timeline({ defaults: { ease: "power2.out" } });
      intro
        .from("[data-fish]", { x: -26, duration: 0.6, stagger: 0.1 }, 0)
        .from("[data-hero-copy]", { y: 14, duration: 0.6 }, 0.05)
        .from("[data-stat]", { y: 10, duration: 0.5, stagger: 0.08 }, 0.15);

      counters.forEach((el) => {
        const end = Number(el.dataset.counter ?? 0);
        const state = { v: 0 };
        gsap.fromTo(
          state,
          { v: 0 },
          {
            v: end,
            duration: 0.8,
            delay: 0.2,
            ease: "power1.out",
            onUpdate: () => {
              el.textContent = String(Math.round(state.v));
            },
          }
        );
      });

      gsap.to("[data-caustic='a']", {
        xPercent: 7,
        yPercent: -5,
        scale: 1.08,
        duration: 9,
        repeat: -1,
        yoyo: true,
        ease: "sine.inOut",
      });
      gsap.to("[data-caustic='b']", {
        xPercent: -6,
        yPercent: 4,
        scale: 1.12,
        duration: 11,
        repeat: -1,
        yoyo: true,
        ease: "sine.inOut",
      });
      gsap.to("[data-fish='a']", {
        x: 22,
        y: -12,
        rotation: 2,
        duration: 8,
        repeat: -1,
        yoyo: true,
        ease: "sine.inOut",
      });
      gsap.to("[data-fish='b']", {
        x: -18,
        y: 10,
        rotation: -2,
        duration: 10,
        repeat: -1,
        yoyo: true,
        ease: "sine.inOut",
      });
    }, root);

    return () => ctx.revert(); // gsap-cleanup
  }, [reduced, still]);

  return (
    <div ref={root} className="relative h-full overflow-hidden bg-[#05121f]">
      <div className="absolute inset-0 bg-[radial-gradient(120%_90%_at_15%_0%,#0e3a4a_0%,#07202f_45%,#041019_100%)]" />
      <div
        data-caustic="a"
        aria-hidden
        className="absolute -left-24 top-[-15%] h-[70%] w-[85%] rounded-full bg-[radial-gradient(closest-side,rgba(56,189,214,0.28),transparent)] blur-3xl"
      />
      <div
        data-caustic="b"
        aria-hidden
        className="absolute bottom-[-20%] right-[-10%] h-[75%] w-[90%] rounded-full bg-[radial-gradient(closest-side,rgba(15,118,110,0.32),transparent)] blur-3xl"
      />
      <div aria-hidden className="absolute inset-0 bg-[linear-gradient(to_top,rgba(4,16,25,0.9),transparent_55%)]" />

      <div aria-hidden className="pointer-events-none absolute inset-0">
        <svg
          data-fish="a"
          className="absolute left-[8%] top-[17%] h-14 w-28 text-cyan-200/20"
          viewBox="0 0 120 60"
          fill="currentColor"
        >
          <path d="M6 30c18-16 44-22 68-18 14 2 26 9 34 18-8 9-20 16-34 18-24 4-50-2-68-18Z" />
          <path d="M108 30 94 18v24l14-12Z" />
          <circle cx="30" cy="27" r="2.5" className="text-[#05121f]" />
        </svg>
        <svg
          data-fish="b"
          className="absolute left-[28%] top-[70%] h-10 w-20 text-teal-200/20"
          viewBox="0 0 120 60"
          fill="currentColor"
        >
          <path d="M114 30C96 14 70 8 46 12 32 14 20 21 12 30c8 9 20 16 34 18 24 4 50-2 68-18Z" />
          <path d="M12 30 26 18v24L12 30Z" />
          <circle cx="90" cy="27" r="2.5" className="text-[#05121f]" />
        </svg>
      </div>

      <div className="relative z-10 flex h-full flex-col justify-between p-10 xl:p-14">
        <div className="flex items-center gap-3 text-white/90">
          <span className="grid h-11 w-11 place-items-center rounded-2xl bg-white/10 backdrop-blur">
            <Fish className="h-6 w-6" aria-hidden />
          </span>
          <span className="font-display text-lg font-semibold tracking-tight">
            Aquaculture<span className="text-[#5eead4]">AI</span>
          </span>
        </div>

        <div data-hero-copy className="max-w-md">
          <p className="mb-3 inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/5 px-3 py-1 text-[11px] font-medium uppercase tracking-[0.18em] text-teal-100/80">
            <Waves className="h-3.5 w-3.5" aria-hidden />
            {t("auth.advisoryBadge")}
          </p>
          <h2 className="font-display text-4xl font-semibold leading-[1.08] tracking-tight text-white xl:text-[2.75rem]">
            {t("auth.canvasTitle")}
          </h2>
          <p className="mt-4 text-sm leading-relaxed text-white/70">{t("auth.canvasSubtitle")}</p>
        </div>

        <dl className="grid max-w-md grid-cols-3 gap-4">
          {STATS.map((stat) => (
            <div
              key={stat.labelKey}
              data-stat
              className="rounded-2xl border border-white/10 bg-white/[0.04] px-4 py-3 backdrop-blur"
            >
              <dd className="nums font-display text-2xl font-semibold text-white">
                <span data-counter={stat.value}>{stat.value}</span>
                {stat.labelKey === "auth.statAdvisory" ? <span className="text-sm">×7</span> : null}
              </dd>
              <dt className="mt-0.5 text-[11px] leading-snug text-white/60">{t(stat.labelKey)}</dt>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}
