import { useEffect, useState } from "react";
import { CheckCircle2, ShieldCheck } from "lucide-react";
import { getAuthStatus } from "../services/api";
import type { AuthStatus, AuthUser } from "../types";
import { Badge } from "../components/ui";

export default function SmsSetup({ user }: { user: AuthUser }) {
  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const phone = user.phone ?? "";
  const masked = phone ? `${phone.slice(0, 3)}••••${phone.slice(-3)}` : "Verified number";

  useEffect(() => { void getAuthStatus().then(setAuth).catch(() => setAuth(null)); }, []);

  return (
    <section aria-label="SMS account" className="rounded-card border border-[var(--border-subtle)] bg-[var(--surface-1)] p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-sm font-semibold text-[var(--text-primary)]">
          <ShieldCheck className="h-4 w-4 text-[var(--accent)]" />Signed in for SMS alerts
        </p>
        <Badge tone={auth?.enabled ? "ok" : "warn"}>{auth?.enabled ? "SMS gateway configured" : "SMS gateway not configured"}</Badge>
      </div>
      <p className="mt-2 flex flex-wrap items-center gap-2 text-sm text-[var(--success)]">
        <CheckCircle2 className="h-4 w-4" />{user.name || "Farmer"} · {masked} verified
      </p>
      <p className="mt-1 text-[11px] text-[var(--text-secondary)]">
        Temperature, turbidity, surface-swimming and dawn oxygen alerts are sent to this number.
        To use a different number, log out and sign in again with that phone.
      </p>
    </section>
  );
}
