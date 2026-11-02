import { useEffect, useState } from "react";
import gsap from "gsap";

const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

/**
 * Hook to listen for OS-level prefers-reduced-motion setting.
 * When reduced motion is preferred, animations should be disabled/instantaneous,
 * while all UI functionality remains 100% accessible.
 */
export function useReducedMotion(): boolean {
  const [prefersReduced, setPrefersReduced] = useState<boolean>(() => {
    if (typeof window === "undefined" || !window.matchMedia) return false;
    return window.matchMedia(REDUCED_MOTION_QUERY).matches;
  });

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mediaQuery = window.matchMedia(REDUCED_MOTION_QUERY);

    const updateMotionPreference = (e: MediaQueryListEvent) => {
      setPrefersReduced(e.matches);
    };

    mediaQuery.addEventListener("change", updateMotionPreference);
    return () => {
      mediaQuery.removeEventListener("change", updateMotionPreference);
    };
  }, []);

  return prefersReduced;
}

/**
 * Returns true if the environment currently requests reduced motion.
 */
export function isReducedMotion(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia(REDUCED_MOTION_QUERY).matches;
}

/**
 * Helper for GSAP animations: creates a gsap.matchMedia instance
 * that checks `(prefers-reduced-motion: reduce)` vs `(prefers-reduced-motion: no-preference)`.
 * Always returns a cleanup function to be called on component unmount.
 */
export function createGsapMatchMedia(setup: (context: { isReduced: boolean }) => void): () => void {
  const mm = gsap.matchMedia();

  mm.add(
    {
      isReduced: "(prefers-reduced-motion: reduce)",
      isFull: "(prefers-reduced-motion: no-preference)",
    },
    (context) => {
      const isReduced = Boolean(context.conditions?.isReduced);
      setup({ isReduced });
    }
  );

  return () => {
    mm.revert(); // gsap-cleanup
  };
}
