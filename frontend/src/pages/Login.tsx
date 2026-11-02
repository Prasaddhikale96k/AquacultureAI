import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowRight, Check } from "lucide-react";
import { AuthLayout } from "../components/auth/AuthLayout";
import { AuthCard } from "../components/auth/AuthCard";
import { PhoneForm } from "../components/auth/PhoneForm";
import { OtpInput, type OtpStatus } from "../components/auth/OtpInput";
import { ResendControl } from "../components/auth/ResendControl";
import { StatusPills } from "../components/auth/StatusPills";
import { useOtpCooldown } from "../components/auth/useOtpCooldown";
import { authErrorKey } from "../components/auth/authMessages";
import { Button } from "../components/ui/Button";
import { authLogin, authResend, authVerify, getAuthStatus } from "../services/api";
import { useAuth } from "../state/authStore";
import { useT } from "../i18n/LanguageProvider";
import type { AuthStatus } from "../types";
import { fadeUp } from "../motion/variants";

type Step = "phone" | "otp";

export default function Login() {
  const t = useT();
  const { setUser } = useAuth();
  const [step, setStep] = useState<Step>("phone");
  const [phone, setPhone] = useState("");
  const [masked, setMasked] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<OtpStatus>("idle");
  const [expiresIn, setExpiresIn] = useState(300);
  const [authStatus, setAuthStatus] = useState<AuthStatus | null>(null);
  const cooldown = useOtpCooldown(30);
  const successTimer = useRef<number | null>(null);

  useEffect(() => {
    void getAuthStatus().then(setAuthStatus).catch(() => setAuthStatus(null));
    return () => {
      if (successTimer.current) window.clearTimeout(successTimer.current);
    };
  }, []);

  const send = async (target: string, resend = false) => {
    setError(null);
    setStatus("idle");
    resend ? setSending(true) : setBusy(true);
    try {
      const result = await authLogin(target);
      if (!result.ok) {
        setError(t(authErrorKey(result.reason, "auth.loginFailed")));
        return;
      }
      setMasked(result.phone_masked ?? target);
      setExpiresIn(result.expires_in_s ?? 300);
      cooldown.start(result.cooldown_s ?? 30);
      if (!resend) {
        setCode("");
        setStep("otp");
      }
    } catch {
      setError(t("auth.loginFailed"));
    } finally {
      setBusy(false);
      setSending(false);
    }
  };

  const resend = async () => {
    setError(null);
    setSending(true);
    try {
      const result = await authResend(phone);
      if (!result.ok) {
        setError(t(authErrorKey(result.reason, "auth.loginFailed")));
        return;
      }
      setExpiresIn(result.expires_in_s ?? 300);
      cooldown.start(result.cooldown_s ?? 30);
      setCode("");
    } catch {
      setError(t("auth.loginFailed"));
    } finally {
      setSending(false);
    }
  };

  const verify = async (value = code) => {
    if (value.length !== 6 || busy || status === "success") return;
    setBusy(true);
    setError(null);
    try {
      const result = await authVerify(phone, value);
      if (!result.ok || !result.user) {
        setStatus("error");
        setError(t(authErrorKey(result.reason, "auth.verifyFailed")));
        setCode("");
        return;
      }
      setStatus("success");
      const user = result.user;
      successTimer.current = window.setTimeout(() => {
        history.replaceState(null, "", "#/overview");
        setUser(user);
      }, 650);
    } catch {
      setStatus("error");
      setError(t("auth.verifyFailed"));
      setCode("");
    } finally {
      setBusy(false);
    }
  };

  const backToPhone = () => {
    setStep("phone");
    setCode("");
    setError(null);
    setStatus("idle");
  };

  const goRegister = () => {
    history.replaceState(null, "", "#register");
    window.dispatchEvent(new Event("hashchange"));
  };

  const smsState = authStatus === null ? "checking" : authStatus.enabled ? "ready" : "offline";
  const smsPills =
    smsState === "ready"
      ? [{ variant: "sms-ready" as const }]
      : smsState === "offline"
        ? [{ variant: "gateway-down" as const }]
        : [];

  return (
    <AuthLayout>
      <div className="w-full max-w-[420px]">
        <AuthCard>
          <div className="mb-4">
            <StatusPills pills={smsPills} />
          </div>

          <AnimatePresence mode="wait" initial={false}>
            {step === "phone" ? (
              <motion.div key="phone" variants={fadeUp} initial="initial" animate="animate" exit="exit">
                <h1 className="font-display text-2xl font-semibold tracking-tight text-[var(--text-primary)]">
                  {t("auth.signInTitle")}
                </h1>
                <p className="mt-1.5 text-sm leading-relaxed text-[var(--text-secondary)]">
                  {t("auth.signInSubtitle")}
                </p>

                <div className="mt-6">
                  <PhoneForm
                    onSubmit={(value) => {
                      setPhone(value);
                      void send(value);
                    }}
                    busy={busy}
                    error={error}
                  />
                </div>

                <div className="mt-6 border-t border-[var(--border-subtle)] pt-4">
                  <p className="flex flex-wrap items-center gap-1.5 text-xs text-[var(--text-secondary)]">
                    {t("auth.newFarm")}
                    <button
                      type="button"
                      onClick={goRegister}
                      className="inline-flex items-center gap-1 font-semibold text-[var(--accent)] hover:text-[var(--accent-strong)]"
                    >
                      {t("auth.createFarm")}
                      <ArrowRight className="h-3.5 w-3.5" aria-hidden />
                    </button>
                  </p>
                </div>
              </motion.div>
            ) : (
              <motion.div key="otp" variants={fadeUp} initial="initial" animate="animate" exit="exit">
                <button
                  type="button"
                  onClick={backToPhone}
                  className="mb-4 inline-flex items-center gap-1.5 text-xs font-medium text-[var(--text-secondary)] transition-colors hover:text-[var(--text-primary)]"
                >
                  <ArrowRight className="h-3.5 w-3.5 rotate-180" aria-hidden />
                  {t("auth.changePhone")}
                </button>

                <h1 className="font-display text-2xl font-semibold tracking-tight text-[var(--text-primary)]">
                  {t("auth.otpTitle")}
                </h1>
                <p className="mt-1.5 text-sm text-[var(--text-secondary)]">
                  {t("auth.otpSentTo", { phone: masked })}
                </p>
                <p className="mt-0.5 text-[11px] text-[var(--text-secondary)]">
                  {t("auth.codeValidFor", { minutes: Math.max(1, Math.round(expiresIn / 60)) })}
                </p>

                <div className="mt-6">
                  <OtpInput
                    value={code}
                    onChange={(next) => {
                      setCode(next);
                      if (status === "error") setStatus("idle");
                      if (error) setError(null);
                    }}
                    onComplete={(next) => void verify(next)}
                    status={status}
                    errorMessage={error ?? undefined}
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
                    {t("auth.otpSuccess")}
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
                    {busy ? t("auth.verifying") : t("auth.verifyOtp")}
                  </Button>
                )}

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
        </AuthCard>

        <p className="mt-4 px-1 text-[11px] leading-relaxed text-[var(--text-secondary)]">
          {t("auth.secureNote")}
        </p>
      </div>
    </AuthLayout>
  );
}
