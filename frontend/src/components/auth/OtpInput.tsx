import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion, useAnimationControls } from "framer-motion";
import { Check } from "lucide-react";
import clsx from "clsx";
import { springFast } from "../../motion/variants";
import { useT } from "../../i18n/LanguageProvider";
import { useReducedMotion } from "../../motion/useReducedMotion";

export type OtpStatus = "idle" | "error" | "success";

interface OtpInputProps {
  value: string;
  onChange: (value: string) => void;
  onComplete?: (value: string) => void;
  length?: number;
  status?: OtpStatus;
  errorMessage?: string;
  successMessage?: string;
  disabled?: boolean;
  autoFocus?: boolean;
}

/**
 * Six segmented OTP boxes.
 *
 * Interaction contract:
 *  - typing a digit writes it and advances focus
 *  - Backspace on an empty box clears the previous box and moves back
 *  - paste splits any digit string across boxes
 *  - ArrowLeft/Right/Home/End move focus; Enter submits a complete code
 *  - error = shake + red morph, success = green sweep into a checkmark
 *  - every state is announced through an assertive live region
 *
 * Framer Motion owns this component (no GSAP on these nodes).
 */
export function OtpInput({
  value,
  onChange,
  onComplete,
  length = 6,
  status = "idle",
  errorMessage,
  successMessage,
  disabled = false,
  autoFocus = false,
}: OtpInputProps) {
  const t = useT();
  const reduced = useReducedMotion();
  const inputs = useRef<Array<HTMLInputElement | null>>([]);
  const [focused, setFocused] = useState<number | null>(null);
  const controls = useAnimationControls();
  const previousStatus = useRef<OtpStatus>(status);

  const digits = useMemo(() => Array.from({ length }, (_, i) => value[i] ?? ""), [value, length]);

  const commit = (next: string) => {
    onChange(next);
    if (next.length === length && /^\d+$/.test(next)) onComplete?.(next);
  };

  const focusBox = (index: number) => {
    const el = inputs.current[Math.max(0, Math.min(length - 1, index))];
    if (el) {
      el.focus();
      el.select();
    }
  };

  useEffect(() => {
    if (autoFocus) focusBox(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoFocus]);

  useEffect(() => {
    if (status === previousStatus.current) return;
    previousStatus.current = status;
    if (status === "error") {
      const id = window.setTimeout(() => focusBox(0), 60);
      if (!reduced) {
        void controls.start({
          x: [0, -8, 8, -6, 6, 0],
          transition: { duration: 0.3, ease: "easeInOut" },
        });
      }
      return () => window.clearTimeout(id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, controls, reduced]);

  const writeDigit = (index: number, raw: string) => {
    const digit = raw.replace(/\D/g, "").slice(-1);
    const next = [...digits];
    next[index] = digit;
    commit(next.join("").replace(/\s/g, ""));
    if (digit && index < length - 1) focusBox(index + 1);
  };

  const handleKeyDown = (index: number, event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Backspace") {
      event.preventDefault();
      const next = [...digits];
      if (next[index]) {
        next[index] = "";
        commit(next.join(""));
      } else if (index > 0) {
        next[index - 1] = "";
        commit(next.join(""));
        focusBox(index - 1);
      }
      return;
    }
    if (event.key === "Delete") {
      event.preventDefault();
      const next = [...digits];
      next[index] = "";
      commit(next.join(""));
      return;
    }
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      focusBox(index - 1);
      return;
    }
    if (event.key === "ArrowRight") {
      event.preventDefault();
      focusBox(index + 1);
      return;
    }
    if (event.key === "Home") {
      event.preventDefault();
      focusBox(0);
      return;
    }
    if (event.key === "End") {
      event.preventDefault();
      focusBox(length - 1);
      return;
    }
    if (event.key === "Enter" && value.length === length) {
      event.preventDefault();
      onComplete?.(value);
    }
  };

  const handlePaste = (index: number, event: React.ClipboardEvent<HTMLInputElement>) => {
    const pasted = event.clipboardData.getData("text").replace(/\D/g, "");
    if (!pasted) return;
    event.preventDefault();
    const start = pasted.length >= length ? 0 : index;
    const next = [...digits];
    for (let i = 0; i < pasted.length && start + i < length; i += 1) {
      next[start + i] = pasted[i];
    }
    const combined = next.join("").replace(/\s/g, "");
    commit(combined);
    focusBox(Math.min(length - 1, start + pasted.length));
  };

  const liveMessage =
    status === "error"
      ? (errorMessage ?? t("auth.otpError"))
      : status === "success"
        ? (successMessage ?? t("auth.otpSuccess"))
        : "";

  return (
    <div className="w-full">
      <motion.div
        animate={controls}
        className="relative flex items-center justify-between gap-2"
        role="group"
        aria-label={t("auth.otpLabel")}
      >
        {digits.map((digit, index) => (
          <div key={index} className="relative flex-1">
            <input
              ref={(el) => {
                inputs.current[index] = el;
              }}
              value={digit}
              onChange={(event) => writeDigit(index, event.target.value)}
              onKeyDown={(event) => handleKeyDown(index, event)}
              onPaste={(event) => handlePaste(index, event)}
              onFocus={(event) => {
                setFocused(index);
                event.currentTarget.select();
              }}
              onBlur={() => setFocused((current) => (current === index ? null : current))}
              disabled={disabled || status === "success"}
              inputMode="numeric"
              pattern="[0-9]*"
              maxLength={1}
              autoComplete={index === 0 ? "one-time-code" : "off"}
              aria-label={t("auth.otpDigit", { index: index + 1, length })}
              aria-invalid={status === "error"}
              className={clsx(
                "nums relative z-10 h-14 w-full rounded-nested border bg-[var(--surface-2)] text-center font-display text-2xl font-semibold text-transparent caret-transparent outline-none transition-colors",
                status === "error"
                  ? "border-[var(--critical)]"
                  : status === "success"
                    ? "border-[var(--success)]"
                    : "border-[var(--border-subtle)] focus:border-[var(--accent)]",
                disabled && "opacity-60"
              )}
            />
            <AnimatePresence mode="popLayout" initial={false}>
              {digit ? (
                <motion.span
                  key={`${index}-${digit}`}
                  aria-hidden
                  initial={reduced ? false : { scale: 0.6, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={springFast}
                  className={clsx(
                    "pointer-events-none absolute inset-0 z-20 grid place-items-center font-display text-2xl font-semibold",
                    status === "error" ? "text-[var(--critical)]" : status === "success" ? "text-[var(--success)]" : "text-[var(--text-primary)]"
                  )}
                >
                  {digit}
                </motion.span>
              ) : focused === index ? (
                <motion.span
                  key={`caret-${index}`}
                  aria-hidden
                  animate={reduced ? { opacity: 1 } : { opacity: [1, 0, 1] }}
                  transition={reduced ? { duration: 0 } : { duration: 1, repeat: Infinity, ease: "linear" }}
                  className="pointer-events-none absolute left-1/2 top-1/2 z-20 h-6 w-px -translate-x-1/2 -translate-y-1/2 bg-[var(--accent)]"
                />
              ) : null}
            </AnimatePresence>
          </div>
        ))}

        <AnimatePresence>
          {status === "success" && (
            <motion.div
              className="pointer-events-none absolute inset-0 z-30 overflow-hidden rounded-nested"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
            >
              {!reduced && (
                <motion.div
                  className="absolute inset-y-0 w-1/2 bg-gradient-to-r from-transparent via-[var(--success)]/25 to-transparent"
                  initial={{ x: "-120%" }}
                  animate={{ x: "260%" }}
                  transition={{ duration: 0.4, ease: "easeOut" }}
                />
              )}
              <motion.div
                className="absolute inset-0 z-30 grid place-items-center bg-[var(--surface-2)]"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
              >
                <motion.span
                  initial={{ scale: 0.4, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  transition={springFast}
                  className="grid h-9 w-9 place-items-center rounded-full bg-[var(--success)] text-[#06281c]"
                >
                  <Check className="h-5 w-5" aria-hidden />
                </motion.span>
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>

      <p
        aria-live="assertive"
        className={clsx(
          "mt-2 min-h-[1rem] text-xs",
          status === "error" ? "text-[var(--critical)]" : "sr-only"
        )}
      >
        {liveMessage}
      </p>
    </div>
  );
}
