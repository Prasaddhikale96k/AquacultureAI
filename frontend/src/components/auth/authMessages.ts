/**
 * Map backend reason strings to dictionary keys so the UI never mixes
 * languages: a Hindi screen must not surface a raw English server string.
 */
export function authErrorKey(reason: string | undefined, fallbackKey: string): string {
  const r = (reason ?? "").toLowerCase();
  if (!r) return fallbackKey;
  if (r.includes("expired")) return "auth.otpExpired";
  if (r.includes("provider") || r.includes("smtp") || r.includes("sms") || r.includes("deliver")) {
    return "auth.smsNotConfigured";
  }
  if (r.includes("wrong") || r.includes("invalid") || r.includes("otp")) return "auth.otpError";
  if (r.includes("wait") || r.includes("too many") || r.includes("limit")) return "auth.tooMany";
  return fallbackKey;
}
