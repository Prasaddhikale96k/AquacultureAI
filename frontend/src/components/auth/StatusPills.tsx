import { AnimatePresence, motion } from "framer-motion";
import { Check, AlertCircle, RotateCw, ShieldAlert, Clock } from "lucide-react";
import clsx from "clsx";
import { useT } from "../../i18n/LanguageProvider";

export type PillVariant = "sms-ready" | "gateway-down" | "cooldown" | "lockout" | "session-expired";

interface StatusPillProps {
  variant: PillVariant;
  countdown?: number; // seconds remaining for cooldown / lockout
}

interface StatusPillsProps {
  pills: StatusPillProps[];
}

const PILL_META: Record<PillVariant, { icon: React.ElementType; labelKey: string; color: string }> = {
  "sms-ready": { icon: Check, labelKey: "auth.smsOnline", color: "#059669" },
  "gateway-down": { icon: AlertCircle, labelKey: "pills.offline", color: "#DC2626" },
  cooldown: { icon: RotateCw, labelKey: "pills.active", color: "#2563EB" },
  lockout: { icon: ShieldAlert, labelKey: "pills.high", color: "#DC2626" },
  "session-expired": { icon: Clock, labelKey: "pills.active", color: "#B45309" },
};

export function StatusPills({ pills }: StatusPillsProps) {
  const t = useT();

  return (
    <div className="flex items-center gap-2">
      <AnimatePresence mode="wait" initial={false}>
        {pills.map((pill) => {
          const meta = PILL_META[pill.variant];
          const Icon = meta.icon;
          const key = `pill-${pill.variant}`;
          const label = pill.variant === "cooldown" && pill.countdown != null ? t("auth.resendIn", { seconds: pill.countdown }) : t(meta.labelKey);
          return (
            <motion.div
              key={key}
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.18, ease: "easeOut" }}
              className={clsx(
                "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors",
                "border-[1px]",
                `border-[${meta.color}]/40 bg-[${meta.color}]/10 text-[${meta.color}]`,
              )}
            >
              <Icon className="h-3 w-3" aria-hidden />
              <span>{label}</span>
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}
