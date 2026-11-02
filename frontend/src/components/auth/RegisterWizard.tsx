import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useAnimationControls } from "framer-motion";
import { AlertCircle, ArrowLeft, ArrowRight, Check } from "lucide-react";
import clsx from "clsx";
import { OtpInput, type OtpStatus } from "./OtpInput";
import { ResendControl } from "./ResendControl";
import { useOtpCooldown } from "./useOtpCooldown";
import { authErrorKey } from "./authMessages";
import { Button } from "../ui/Button";
import { authRegister, authResend, authVerify } from "../../services/api";
import { useAuth } from "../../state/authStore";
import { useT } from "../../i18n/LanguageProvider";
import { useReducedMotion } from "../../motion/useReducedMotion";
import { fadeUp, springSoft } from "../../motion/variants";
import type { AuthUser } from "../../types";

const SYSTEMS = [
  { value: "Pond", labelKey: "auth.systemPondShort" },
  { value: "RAS", labelKey: "auth.systemRasShort" },
  { value: "Biofloc", labelKey: "auth.systemBiofloc" },
  { value: "Cage", labelKey: "auth.systemCage" },
] as const;

type Step = 1 | 2 | 3;

interface FormState {
  name: string;
  phone: string;
  tankId: string;
  species: string;
  system: (typeof SYSTEMS)[number]["value"];
}

export function RegisterWizard() {
  const t = useT();
  const reduced = useReducedMotion();
  const { setUser } = useAuth();
  const [step, setStep] = useState<Step>(1);
  const [form, setForm] = useState<FormState>({
    name: "",
    phone: "",
    tankId: "",
    species: "Nile Tilapia (GIFT)",
    system: "Pond",
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [serverError, setServerError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sending, setSending] = useState(false);
  const [masked, setMasked] = useState("");
  const [code, setCode] = useState("");
  const [status, setStatus] = useState<OtpStatus>("idle");
  const [expiresIn, setExpiresIn] = useState(300);
  const cooldown = useOtpCooldown(30);
  const shake = useAnimationControls();
  const successTimer = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (successTimer.current) window.clearTimeout(successTimer.current);
    };
  }, []);

  const update = (patch: Partial<FormState>) => {
    setForm((current) => ({ ...current, ...patch }));
    const keys = Object.keys(patch);
    if (keys.some((key) => errors[key])) {
      setErrors((current) => {
        const next = { ...current };
        keys.forEach((key) => delete next[key]);
        return next;
      });
    }
  };

  const fail = (next: Record<string, string>) => {
    setErrors(next);
    if (!reduced) {
      void shake.start({ x: [0, -7, 7, -5, 5, 0], transition: { duration: 0.3, ease: "easeInOut" } });
    }
  };

  const validateIdentity = () => {
    const next: Record<string, string> = {};
    if (form.name.trim().length < 2) next.name = t("auth.required");
    if (!/^[6-9]\d{9}$/.test(form.phone)) next.phone = t("auth.invalidPhone");
    if (Object.keys(next).length) {
      fail(next);
      return false;
    }
    return true;
  };

  const validateFarm = () => {
    if (!form.tankId.trim()) {
      fail({ tankId: t("auth.required") });
      return false;
    }
    return true;
  };

  const goFarm = () => {
    setServerError(null);
    if (validateIdentity()) setStep(2);
  };

  const sendCode = async () => {
    setServerError(null);
    if (!validateFarm()) return;
    setBusy(true);
    try {
      const result = await authRegister({
        name: form.name.trim(),
        phone: form.phone,
        tankId: form.tankId.trim(),
        species: form.species.trim() || "Nile Tilapia (GIFT)",
        system: form.system,
      });
      if (!result.ok) {
        setServerError(t(authErrorKey(result.reason, "auth.registerFailed")));
        return;
      }
      setMasked(result.phone_masked ?? form.phone);
      setExpiresIn(result.expires_in_s ?? 300);
      cooldown.start(result.cooldown_s ?? 30);
      setCode("");
      setStatus("idle");
      setStep(3);
    } catch {
      setServerError(t("auth.registerFailed"));
    } finally {
      setBusy(false);
    }
  };

  const resend = async () => {
    setServerError(null);
    setSending(true);
    try {
      const result = await authResend(form.phone);
      if (!result.ok) {
        setServerError(t(authErrorKey(result.reason, "auth.loginFailed")));
        return;
      }
      setExpiresIn(result.expires_in_s ?? 300);
      cooldown.start(result.cooldown_s ?? 30);
      setCode("");
      setStatus("idle");
    } catch {
      setServerError(t("auth.loginFailed"));
    } finally {
      setSending(false);
    }
  };

  const verify = async (value = code) => {
    if (value.length !== 6 || busy || status === "success") return;
    setBusy(true);
    setServerError(null);
    try {
      const result = await authVerify(form.phone, value);
      if (!result.ok || !result.user) {
        setStatus("error");
        setServerError(t(authErrorKey(result.reason, "auth.verifyFailed")));
        setCode("");
        return;
      }
      setStatus("success");
      const user: AuthUser = result.user;
      successTimer.current = window.setTimeout(() => {
        history.replaceState(null, "", "#/overview");
        setUser(user);
      }, 700);
    } catch {
      setStatus("error");
      setServerError(t("auth.verifyFailed"));
      setCode("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="w-full">
      <div className="mb-5">
        <div className="flex items-baseline justify-between gap-3">
          <p className="text-xs font-medium text-[var(--text-secondary)]">
            {t("auth.registerStep", { current: step, total: 3 })}
          </p>
          <p className="text-xs font-semibold text-[var(--text-primary)]">
            {t(step === 1 ? "auth.step1Title" : step === 2 ? "auth.farmDetailsTitle" : "auth.verifyPhoneTitle")}
          </p>
        </div>
        <div className="mt-2 h-1 overflow-hidden rounded-full bg-[var(--surface-3)]">
          <motion.div
            className="h-full rounded-full bg-[var(--accent)]"
            initial={false}
            animate={{ width: `${(step / 3) * 100}%` }}
            transition={reduced ? { duration: 0 } : springSoft}
          />
        </div>
      </div>

      <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--surface-1)] p-6 shadow-[0_24px_60px_-40px_rgba(0,0,0,0.6)] sm:p-7">
        <AnimatePresence mode="wait" initial={false}>
          {step === 1 && (
            <motion.div key="identity" variants={fadeUp} initial="initial" animate="animate" exit="exit">
              <h1 className="font-display text-2xl font-semibold tracking-tight text-[var(--text-primary)]">
                {t("auth.registerTitle")}
              </h1>
              <p className="mt-1.5 text-sm leading-relaxed text-[var(--text-secondary)]">{t("auth.registerSubtitle")}</p>

              <motion.div animate={shake} className="mt-6 space-y-4">
                <Field
                  id="reg-name"
                  label={t("auth.nameLabel")}
                  value={form.name}
                  onChange={(value) => update({ name: value })}
                  placeholder={t("auth.namePlaceholder")}
                  error={errors.name}
                  autoComplete="name"
                  autoFocus
                />
                // TODO(scope): Register duplicates the +91 phone field markup here instead of importing
                // the shared PhoneForm component. PhoneForm auto-submits on a valid 10-digit number,
                // but Register step 1 pairs name+phone behind a single "Continue" button, so swapping
                // in PhoneForm would change the register flow. Keep inline markup to avoid that
                // behaviour change; revisit if PhoneForm gains a non-submitting mode.
                <div>
                  <label htmlFor="reg-phone" className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]">
                    {t("auth.phoneLabel")}
                  </label>
                  <div
                    className={clsx(
                      "flex items-center gap-2 rounded-nested border bg-[var(--surface-2)] px-3 transition-colors focus-within:border-[var(--accent)]",
                      errors.phone ? "border-[var(--critical)]" : "border-[var(--border-subtle)]"
                    )}
                  >
                    <span className="nums select-none border-r border-[var(--border-subtle)] pr-2 text-sm font-medium text-[var(--text-secondary)]">
                      +91
                    </span>
                    <input
                      id="reg-phone"
                      value={form.phone}
                      onChange={(event) => {
                        const digits = event.target.value.replace(/\D/g, "");
                        update({ phone: digits.length > 10 ? digits.slice(-10) : digits });
                      }}
                      inputMode="tel"
                      autoComplete="tel-national"
                      maxLength={10}
                      placeholder={t("auth.phonePlaceholder")}
                      aria-invalid={Boolean(errors.phone)}
                      aria-describedby={errors.phone ? "reg-phone-error" : undefined}
                      className="nums h-12 w-full bg-transparent text-base tracking-wide text-[var(--text-primary)] outline-none placeholder:text-[var(--text-secondary)]/60"
                    />
                  </div>
                  {errors.phone && (
                    <p id="reg-phone-error" role="alert" className="mt-1.5 flex items-center gap-1.5 text-xs text-[var(--critical)]">
                      <AlertCircle className="h-3.5 w-3.5" aria-hidden />
                      {errors.phone}
                    </p>
                  )}
                </div>
              </motion.div>

              {serverError && <ServerError message={serverError} />}

              <div className="mt-6 flex items-center justify-between gap-3">
                <a href="#login" className="inline-flex items-center gap-1.5 text-xs font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)]">
                  <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
                  {t("auth.backToLogin")}
                </a>
                <Button type="button" onClick={goFarm} rightIcon={<ArrowRight className="h-4 w-4" aria-hidden />}>
                  {t("auth.continue")}
                </Button>
              </div>
            </motion.div>
          )}

          {step === 2 && (
            <motion.div key="farm" variants={fadeUp} initial="initial" animate="animate" exit="exit">
              <h1 className="font-display text-2xl font-semibold tracking-tight text-[var(--text-primary)]">
                {t("auth.farmDetailsTitle")}
              </h1>
              <p className="mt-1.5 text-sm text-[var(--text-secondary)]">{t("auth.step2Title")}</p>

              <motion.div animate={shake} className="mt-6 space-y-4">
                <Field
                  id="reg-tank"
                  label={t("auth.tankLabel")}
                  value={form.tankId}
                  onChange={(value) => update({ tankId: value })}
                  placeholder={t("auth.tankPlaceholder")}
                  error={errors.tankId}
                  autoFocus
                />
                <Field
                  id="reg-species"
                  label={t("auth.speciesLabel")}
                  value={form.species}
                  onChange={(value) => update({ species: value })}
                  placeholder={t("auth.speciesPlaceholder")}
                />

                <div>
                  <span className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]">
                    {t("auth.systemTypeLabel")}
                  </span>
                  <div role="radiogroup" aria-label={t("auth.systemTypeLabel")} className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                    {SYSTEMS.map((system) => {
                      const active = form.system === system.value;
                      return (
                        <button
                          key={system.value}
                          type="button"
                          role="radio"
                          aria-checked={active}
                          onClick={() => update({ system: system.value })}
                          className={clsx(
                            "relative h-10 rounded-nested border text-xs font-medium transition-colors",
                            active
                              ? "border-[var(--accent)] text-[var(--text-primary)]"
                              : "border-[var(--border-subtle)] text-[var(--text-secondary)] hover:border-[var(--text-secondary)]"
                          )}
                        >
                          {active && (
                            <motion.span
                              layoutId="system-segment"
                              className="absolute inset-0 -z-10 rounded-nested bg-[var(--accent)]/12"
                              transition={reduced ? { duration: 0 } : springSoft}
                            />
                          )}
                          {t(system.labelKey)}
                        </button>
                      );
                    })}
                  </div>
                </div>
              </motion.div>

              {serverError && <ServerError message={serverError} />}

              <div className="mt-6 flex items-center justify-between gap-3">
                <Button type="button" variant="ghost" onClick={() => setStep(1)} leftIcon={<ArrowLeft className="h-4 w-4" aria-hidden />}>
                  {t("auth.back")}
                </Button>
                <Button type="button" onClick={() => void sendCode()} loading={busy} rightIcon={<ArrowRight className="h-4 w-4" aria-hidden />}>
                  {busy ? t("auth.sending") : t("auth.createFarm")}
                </Button>
              </div>
            </motion.div>
          )}

          {step === 3 && (
            <motion.div key="verify" variants={fadeUp} initial="initial" animate="animate" exit="exit">
              <button
                type="button"
                onClick={() => {
                  setStep(2);
                  setStatus("idle");
                  setCode("");
                  setServerError(null);
                }}
                className="mb-4 inline-flex items-center gap-1.5 text-xs font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
              >
                <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
                {t("auth.editDetails")}
              </button>

              <h1 className="font-display text-2xl font-semibold tracking-tight text-[var(--text-primary)]">
                {t("auth.verifyPhoneTitle")}
              </h1>
              <p className="mt-1.5 text-sm text-[var(--text-secondary)]">{t("auth.otpSentTo", { phone: masked })}</p>
              <p className="mt-0.5 text-[11px] text-[var(--text-secondary)]">
                {t("auth.codeValidFor", { minutes: Math.max(1, Math.round(expiresIn / 60)) })}
              </p>

              <div className="mt-5 rounded-nested border border-[var(--border-subtle)] bg-[var(--surface-2)] p-3 text-xs">
                <SummaryRow label={t("auth.nameLabel")} value={form.name} />
                <SummaryRow label={t("auth.tankLabel")} value={form.tankId} />
                <SummaryRow label={t("auth.speciesLabel")} value={form.species} />
                <SummaryRow label={t("auth.systemTypeLabel")} value={t(SYSTEMS.find((s) => s.value === form.system)!.labelKey)} />
              </div>

              <div className="mt-5">
                <OtpInput
                  value={code}
                  onChange={(next) => {
                    setCode(next);
                    if (status === "error") setStatus("idle");
                    if (serverError) setServerError(null);
                  }}
                  onComplete={(next) => void verify(next)}
                  status={status}
                  errorMessage={serverError ?? undefined}
                  successMessage={t("auth.registerSuccess")}
                  autoFocus
                  disabled={busy || status === "success"}
                />
              </div>

              {status === "success" ? (
                <div
                  role="status"
                  className="mt-4 flex min-h-11 w-full items-center justify-center gap-2 rounded-nested border border-[var(--success)]/30 bg-[var(--success)]/10 px-3 py-2 text-center text-xs font-semibold leading-snug text-[var(--success)] sm:text-sm"
                >
                  <Check className="h-4 w-4" aria-hidden />
                  {t("auth.registerSuccess")}
                </div>
              ) : (
                <Button
                  type="button"
                  size="lg"
                  className="mt-4 w-full"
                  loading={busy}
                  disabled={code.length !== 6}
                  onClick={() => void verify()}
                >
                  {busy ? t("auth.verifying") : t("auth.completeRegistration")}
                </Button>
              )}

              {serverError && status !== "error" && <ServerError message={serverError} />}

              <div className="mt-5 flex items-center justify-between gap-2">
                <span className="text-xs text-[var(--text-secondary)]">{t("auth.noCode")}</span>
                <ResendControl
                  active={cooldown.active}
                  remaining={cooldown.remaining}
                  total={cooldown.total}
                  epoch={cooldown.epoch}
                  busy={sending}
                  onResend={() => void resend()}
                />
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

function Field({
  id,
  label,
  value,
  onChange,
  placeholder,
  error,
  autoComplete,
  autoFocus,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  error?: string;
  autoComplete?: string;
  autoFocus?: boolean;
}) {
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-xs font-medium text-[var(--text-secondary)]">
        {label}
      </label>
      <input
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        autoComplete={autoComplete}
        autoFocus={autoFocus}
        aria-invalid={Boolean(error)}
        aria-describedby={error ? `${id}-error` : undefined}
        className={clsx(
          "h-12 w-full rounded-nested border bg-[var(--surface-2)] px-3 text-base text-[var(--text-primary)] outline-none transition-colors placeholder:text-[var(--text-secondary)]/60 focus:border-[var(--accent)]",
          error ? "border-[var(--critical)]" : "border-[var(--border-subtle)]"
        )}
      />
      {error && (
        <p id={`${id}-error`} role="alert" className="mt-1.5 flex items-center gap-1.5 text-xs text-[var(--critical)]">
          <AlertCircle className="h-3.5 w-3.5" aria-hidden />
          {error}
        </p>
      )}
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3 py-1">
      <span className="text-[var(--text-secondary)]">{label}</span>
      <span className="text-right font-medium text-[var(--text-primary)]">{value || "—"}</span>
    </div>
  );
}

function ServerError({ message }: { message: string }) {
  return (
    <p role="alert" className="mt-4 flex items-start gap-2 rounded-nested border border-[var(--critical)]/30 bg-[var(--critical)]/10 p-2.5 text-xs text-[var(--critical)]">
      <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
      {message}
    </p>
  );
}
