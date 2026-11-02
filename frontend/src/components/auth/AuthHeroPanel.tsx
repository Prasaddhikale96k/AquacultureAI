import { useEffect, useRef, useState } from "react";
import gsap from "gsap";
import { Fish, Waves } from "lucide-react";
import { useTheme } from "../../theme/ThemeProvider";
import { useT } from "../../i18n/LanguageProvider";
import { useReducedMotion } from "../../motion/useReducedMotion";

const STATS = [
  { value: 6, labelKey: "auth.statParams" },
  { value: 5, labelKey: "auth.statLevels" },
  { value: 24, labelKey: "auth.statAdvisory" },
] as const;

const MOBILE_QUERY = "(max-width: 639px)";

/**
 * Auth hero panel (THEME OVERRIDE v2).
 *
 * LIGHT variant is the owner's default: white/near-white surfaces, slate text,
 * teal/cyan accent, faint fish-silhouette texture (8-14 % opacity) and a soft
 * caustic shimmer. DARK variant is the pre-existing near-black "deep-water"
 * look retained as an opt-in toggle.
 *
 * GSAP owns the fish parallax drift, caustic shimmer and stat count-up; every
 * timeline is created inside a gsap.context whose revert() is tagged
 * // gsap-cleanup. Framer Motion owns nothing inside this component (no
 * shared DOM nodes).
 */
export function AuthHeroPanel() {
  const { theme } = useTheme();
  const t = useT();
  const root = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();
  const [isMobile, setIsMobile] = useState(false);
  // Dev-only QA switch (?motion=off): deterministic final frame for screenshots.
  const still =
    import.meta.env.DEV && new URLSearchParams(window.location.search).get("motion") === "off";

  const light = theme !== "dark";

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia(MOBILE_QUERY);
    setIsMobile(mq.matches);
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  // GSAP owns the hero canvas/SVG layers; Framer Motion does not touch them.
  useEffect(() => {
    if (!root.current || isMobile) return;
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

      // GSAP timelines tagged // gsap-cleanup for auditability.
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
  }, [isMobile, reduced, still]);

  const fishOpacity = light ? 0.10 : 0.16;
  const fishColor = light ? "#94A3B8" : "#5eead4";
  const causticBlob = light
    ? "rgba(8,145,178,0.12)"
    : "rgba(56,189,214,0.28)";
  const causticBlobB = light
    ? "rgba(14,116,144,0.12)"
    : "rgba(15,118,110,0.32)";
  const advisoryBorder = light ? "rgba(14,116,144,0.25)" : "rgba(255,255,255,0.15)";
  const statBorder = light ? "rgba(15,23,42,0.08)" : "rgba(255,255,255,0.10)";
  const statBg = light ? "#F1F5F9" : "rgba(255,255,255,0.04)";
  const pillColor = light ? "#0E7490" : "teal-100/80";

  // Mobile collapse: logo + single-line promise only, no stat chips / fish / caustic.
  if (isMobile) {
    return (
      <div
        ref={root}
        className="relative overflow-hidden border-b border-[var(--border-subtle)] bg-[var(--surface-0)]"
        style={{ height: light ? "auto" : "auto" }}
      >
        <div className="flex items-center gap-3 px-5 py-6">
          <span className="grid h-9 w-9 place-items-center rounded-xl bg-[var(--accent)]/12 text-[var(--accent)]">
            <Fish className="h-5 w-5" aria-hidden />
          </span>
          <div className="min-w-0">
            <p className="font-display text-base font-semibold leading-tight tracking-tight text-[var(--text-primary)]">
              {t("auth.canvasTitle")}
            </p>
            <p className="truncate text-[11px] leading-relaxed text-[var(--text-secondary)]">
              {t("auth.canvasSubtitle")}
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      ref={root}
      className="relative hidden h-full min-h-screen overflow-hidden lg:block"
    >
      {/* Background gradient — light teal-tinted / dark near-black teal. */}
      <div
        className="absolute inset-0"
        style={{
          background: light
            ? "linear-gradient(160deg,#ECFEFF 0%,#F8FAFC 55%,#FFFFFF 100%)"
            : "radial-gradient(120% 90% at 15% 0%,#0e3a4a 0%,#07202f 45%,#041019 100%)",
        }}
      />

      {/* Caustic shimmer blobs — one calm animated texture, premium not busy. */}
      <div
        data-caustic="a"
        aria-hidden
        className="absolute -left-24 top-[-15%] h-[70%] w-[85%] rounded-full blur-3xl"
        style={{ background: `radial-gradient(closest-side,${causticBlob},transparent)` }}
      />
      <div
        data-caustic="b"
        aria-hidden
        className="absolute bottom-[-20%] right-[-10%] h-[75%] w-[90%] rounded-full blur-3xl"
        style={{ background: `radial-gradient(closest-side,${causticBlobB},transparent)` }}
      />

      <div aria-hidden className="pointer-events-none absolute inset-0">
        <svg
          data-fish="a"
          className={`absolute left-[8%] top-[17%] h-14 w-28 text-[${fishColor}]`}
          style={{ opacity: fishOpacity }}
          viewBox="0 0 120 60"
          fill="currentColor"
        >
          <path d="M6 30c18-16 44-22 68-18 14 2 26 9 34 18-8 9-20 16-34 18-24 4-50-2-68-18Z" />
          <path d="M108 30 94 18v24l14-12Z" />
          <circle cx="30" cy="27" r="2.5" className="#05121f" />
        </svg>
        <svg
          data-fish="b"
          className={`absolute left-[28%] top-[70%] h-10 w-20 text-[${fishColor}]`}
          style={{ opacity: fishOpacity }}
          viewBox="0 0 120 60"
          fill="currentColor"
        >
          <path d="M114 30C96 14 70 8 46 12 32 14 20 21 12 30c8 9 20 16 34 18 24 4 50-2 68-18Z" />
          <path d="M12 30 26 18v24L12 30Z" />
          <circle cx="90" cy="27" r="2.5" className="#05121f" />
        </svg>
      </div>

      <div className="relative z-10 flex h-full flex-col justify-between p-10 xl:p-14">
        <div className="flex items-center gap-3 text-[var(--text-primary)]">
          <span className="grid h-11 w-11 place-items-center rounded-2xl bg-[var(--accent)]/12 text-[var(--accent)]">
            <Fish className="h-6 w-6" aria-hidden />
          </span>
          <span className="font-display text-lg font-semibold tracking-tight">
            Aquaculture<span className="text-[var(--accent)]">AI</span>
          </span>
        </div>

        <div data-hero-copy className="max-w-md">
          <p
            className="mb-3 inline-flex items-center gap-2 rounded-full border px-3 py-1 text-[11px] font-medium uppercase tracking-[0.18em]"
            style={{
              borderColor: advisoryBorder,
              color: pillColor,
              backgroundColor: light ? "#CFFAFE" : "rgba(255,255,255,0.05)",
            }}
          >
            <Waves className="h-3.5 w-3.5" aria-hidden />
            <span className="text-[11px] font-medium">{t("auth.advisoryBadge")}</span>
          </p>
          <h2 className="font-display text-4xl font-semibold leading-[1.08] tracking-tight text-[var(--text-primary)] xl:text-[2.75rem]">
            {t("auth.canvasTitle")}
          </h2>
          <p className="mt-4 text-sm leading-relaxed text-[var(--text-secondary)]">
            {t("auth.canvasSubtitle")}
          </p>
        </div>

        <dl className="grid max-w-md grid-cols-3 gap-4">
          {STATS.map((stat) => (
            <div
              key={stat.labelKey}
              data-stat
              className="rounded-card border px-4 py-3 backdrop-blur-sm"
              style={{
                borderColor: statBorder,
                backgroundColor: statBg,
                color: light ? "#0F172A" : "#FFFFFF",
              }}
            >
              <dd className="nums font-display text-2xl font-semibold" style={{ color: light ? "#0891B2" : "#FFFFFF" }}>
                <span data-counter={stat.value}>{stat.value}</span>
                {stat.labelKey === "auth.statAdvisory" ? <span className="text-sm" style={{ opacity: light ? 0.55 : 0.65 }}>{stat.labelKey === "auth.statAdvisory" ? "×7" : ""}</span> : null}
              </dd>
              <dt className="mt-0.5 text-[11px] leading-snug" style={{ color: light ? "#475569" : "rgba(230,237,243,0.70)" }}>
                {t(stat.labelKey)}
              </dt>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}
