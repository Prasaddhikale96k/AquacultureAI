import { useCallback, useEffect, useState } from "react";

/** Seconds until the resend action unlocks; drives the Framer cooldown ring. */
export function useOtpCooldown(seconds = 30) {
  const [deadline, setDeadline] = useState(0);
  const [duration, setDuration] = useState(seconds);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!deadline) return;
    const id = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(id);
  }, [deadline]);

  const remaining = deadline ? Math.max(0, Math.ceil((deadline - now) / 1000)) : 0;
  const active = remaining > 0;

  const start = useCallback(
    (next?: number) => {
      const at = Date.now();
      const span = next ?? seconds;
      setNow(at);
      setDuration(span);
      setDeadline(at + span * 1000);
    },
    [seconds]
  );

  return { remaining, active, start, total: duration, epoch: deadline };
}
