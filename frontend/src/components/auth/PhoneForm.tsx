import { useEffect, useRef, useState } from "react";
import { motion, useAnimationControls } from "framer-motion";
import { AlertCircle, ArrowRight, Phone } from "lucide-react";
import clsx from "clsx";
import { Button } from "../ui/Button";
import { useT } from "../../i18n/LanguageProvider";
import { useReducedMotion } from "../../motion/useReducedMotion";

interface PhoneFormProps {
  onSubmit: (phone: string) => void | Promise<void>;
  busy?: boolean;
  error?: string | null;
  defaultValue?: string;
  ctaLabel?: string;
}

export function PhoneForm({ onSubmit, busy = false, error, defaultValue = "", ctaLabel }: PhoneFormProps) {
  const t = useT();
  const reduced = useReducedMotion();
  const [phone, setPhone] = useState(defaultValue.replace(/\D/g, "").slice(-10));
  const [touched, setTouched] = useState(false);
  const controls = useAnimationControls();
  const previousError = useRef<string | null | undefined>(error);

  const valid = /^[6-9]\d{9}$/.test(phone);

  useEffect(() => {
    if (!error || previousError.current === error) return;
    previousError.current = error;
    if (!reduced) {
      void controls.start({ x: [0, -7, 7, -5, 5, 0], transition: { duration: 0.3, ease: "easeInOut" } });
    }
  }, [error, controls, reduced]);

  useEffect(() => {
    if (!error) previousError.current = error;
  }, [error]);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    setTouched(true);
    if (!valid || busy) return;
    void onSubmit(phone);
  };

  const shownError = touched && !valid ? t("auth.invalidPhone") : error;

  return (
    <motion.form animate={controls} onSubmit={submit} className="space-y-4" noValidate>
      <div>
        <label htmlFor="auth-phone" className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]">
          {t("auth.phoneLabel")}
        </label>
        <div
          className={clsx(
            "flex items-center gap-2 rounded-nested border bg-[var(--surface-2)] px-3 transition-colors focus-within:border-[var(--accent)]",
            shownError ? "border-[var(--critical)]" : "border-[var(--border-subtle)]"
          )}
        >
          <Phone className="h-4 w-4 shrink-0 text-[var(--text-secondary)]" aria-hidden />
          <span className="nums select-none border-r border-[var(--border-subtle)] pr-2 text-sm font-medium text-[var(--text-secondary)]">
            +91
          </span>
          <input
            id="auth-phone"
            value={phone}
            onChange={(event) => {
              const digits = event.target.value.replace(/\D/g, "");
              setPhone(digits.length > 10 ? digits.slice(-10) : digits);
            }}
            onBlur={() => setTouched(true)}
            inputMode="tel"
            autoComplete="tel-national"
            placeholder={t("auth.phonePlaceholder")}
            aria-invalid={Boolean(shownError)}
            aria-describedby={shownError ? "auth-phone-error" : undefined}
            maxLength={10}
            className="nums h-12 w-full bg-transparent text-base tracking-wide text-[var(--text-primary)] outline-none placeholder:text-[var(--text-secondary)]/60"
          />
        </div>
        {shownError && (
          <p id="auth-phone-error" role="alert" className="mt-1.5 flex items-center gap-1.5 text-xs text-[var(--critical)]">
            <AlertCircle className="h-3.5 w-3.5" aria-hidden />
            {shownError}
          </p>
        )}
        <p className="mt-1.5 text-[11px] text-[var(--text-secondary)]">{t("auth.phoneHelp")}</p>
      </div>

      <Button type="submit" size="lg" loading={busy} disabled={busy || (touched && !valid)} className="w-full" rightIcon={<ArrowRight className="h-4 w-4" aria-hidden />}>
        {ctaLabel ?? t("auth.sendOtp")}
      </Button>
    </motion.form>
  );
}
