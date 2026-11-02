import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Fish, KeyRound, Phone, ShieldCheck } from "lucide-react";
import { authLogin, authVerify, getAuthStatus } from "../services/api";
import type { AuthStatus, AuthUser } from "../types";
import { Badge } from "../components/ui";

type Step = "phone" | "otp";

export default function LoginGate({ onAuthenticated }: { onAuthenticated: (user: AuthUser) => void }) {
  const [step, setStep] = useState<Step>("phone");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [masked, setMasked] = useState("");
  const [expiresIn, setExpiresIn] = useState(300);
  const [cooldown, setCooldown] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [auth, setAuth] = useState<AuthStatus | null>(null);

  useEffect(() => {
    void getAuthStatus().then(setAuth).catch(() => setAuth(null));
  }, []);

  useEffect(() => {
    if (cooldown <= 0) return;
    const id = window.setInterval(() => setCooldown((c) => Math.max(0, c - 1)), 1000);
    return () => window.clearInterval(id);
  }, [cooldown]);

  const validPhone = useMemo(() => phone.replace(/\D/g, "").length >= 10, [phone]);

  const send = async () => {
    setBusy(true); setError(null); setNotice(null);
    try {
      const result = await authLogin(phone);
      if (!result.ok) { setError(result.reason ?? "Could not send the OTP."); return; }
      setMasked(result.phone_masked ?? phone);
      setExpiresIn(result.expires_in_s ?? 300);
      setCooldown(result.cooldown_s ?? 30);
      setStep("otp"); setCode("");
      setNotice(`A 6-digit code was sent to ${result.phone_masked ?? phone}.`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const verify = async () => {
    setBusy(true); setError(null);
    try {
      const result = await authVerify(phone, code);
      if (!result.ok || !result.user) { setError(result.reason ?? "That code did not work."); return; }
      onAuthenticated(result.user);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid min-h-screen place-items-center bg-surface px-4 py-10">
      <div className="w-full max-w-md">
        <div className="mb-6 flex items-center justify-center gap-2.5">
          <span className="grid h-11 w-11 place-items-center rounded-2xl bg-brand/15"><Fish className="h-6 w-6 text-brand" /></span>
          <span className="text-xl font-semibold text-ink">Aquaculture<span className="text-brand">AI</span></span>
        </div>

        <section aria-label="Sign in" className="rounded-3xl border border-line bg-white p-6 shadow-[0_1px_2px_rgb(20_23_28/0.04),0_18px_50px_-24px_rgb(20_23_28/0.25)]">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h1 className="text-2xl font-extrabold tracking-tight text-ink">Farmer sign in</h1>
              <p className="mt-1 text-sm text-mute">Enter your mobile number. We will send a one-time code by SMS.</p>
            </div>
            <ShieldCheck className="mt-1 h-6 w-6 shrink-0 text-ok" />
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-2 text-[11px] text-mute">
            <Badge tone={auth?.enabled ? "ok" : "warn"}>{auth?.enabled ? "SMS gateway online" : "SMS gateway not configured"}</Badge>
            <span>No password. Your number is used only for alerts and sign-in.</span>
          </div>

          {step === "phone" ? (
            <div className="mt-6 space-y-3">
              <label className="block text-xs font-medium text-ink" htmlFor="login-phone">Mobile number</label>
              <div className="flex items-center gap-2 rounded-xl border border-line bg-white px-3 focus-within:border-cyan">
                <Phone className="h-4 w-4 text-mute" />
                <input id="login-phone" value={phone} onChange={(e) => setPhone(e.target.value)} inputMode="tel" autoComplete="tel"
                  placeholder="+91XXXXXXXXXX" className="h-11 w-full text-sm outline-none placeholder:text-mute"
                  onKeyDown={(e) => { if (e.key === "Enter" && validPhone && !busy) void send(); }} />
              </div>
              <button onClick={() => void send()} disabled={busy || !validPhone}
                className="h-11 w-full rounded-xl bg-brand text-sm font-semibold text-white shadow-sm hover:opacity-90 disabled:opacity-40">
                {busy ? "Sending code…" : "Send OTP"}
              </button>
              <p className="text-[11px] text-mute">Use the number registered with the farm. Indian numbers may be entered as 10 digits.</p>
            </div>
          ) : (
            <div className="mt-6 space-y-3">
              <button onClick={() => { setStep("phone"); setError(null); setNotice(null); }}
                className="inline-flex items-center gap-1 text-xs font-medium text-cyan">
                <ArrowLeft className="h-3.5 w-3.5" />Change number
              </button>
              <p className="flex items-center gap-1.5 text-sm text-ink"><KeyRound className="h-4 w-4 text-cyan" />Enter the code sent to <b>{masked}</b></p>
              <input value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))} inputMode="numeric"
                autoComplete="one-time-code" placeholder="6-digit OTP" aria-label="One-time password"
                className="h-11 w-full rounded-xl border border-line px-3 text-center text-lg tracking-[0.4em] outline-none focus:border-cyan" />
              <button onClick={() => void verify()} disabled={busy || code.length !== 6}
                className="h-11 w-full rounded-xl bg-brand text-sm font-semibold text-white shadow-sm hover:opacity-90 disabled:opacity-40">
                {busy ? "Verifying…" : "Verify and sign in"}
              </button>
              <div className="flex items-center justify-between text-[11px] text-mute">
                <span>Code valid for {Math.round(expiresIn / 60)} min.</span>
                <button onClick={() => void send()} disabled={busy || cooldown > 0} className="font-medium text-cyan disabled:text-mute">
                  {cooldown > 0 ? `Resend in ${cooldown}s` : "Resend code"}
                </button>
              </div>
            </div>
          )}

          {notice && <p role="status" className="mt-3 rounded-lg border border-ok/30 bg-ok/5 p-2 text-[12px] text-ok">{notice}</p>}
          {error && <p role="status" className="mt-3 rounded-lg border border-warn/40 bg-warn/10 p-2 text-[12px] text-warn">{error}</p>}
        </section>

        <p className="mt-4 text-center text-[11px] text-mute">
          Advisory system only. No pump, feeder or relay control. In an emergency, check the pond and call a technician.
        </p>
      </div>
    </div>
  );
}
