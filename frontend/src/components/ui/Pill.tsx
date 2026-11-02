import { forwardRef, type HTMLAttributes, type ReactNode } from "react";
import clsx from "clsx";
import { twMerge } from "tailwind-merge";
import { CheckCircle2, AlertTriangle, XCircle, Info, HelpCircle } from "lucide-react";

export type PillVariant = "neutral" | "success" | "warn" | "critical" | "info";

export interface PillProps extends HTMLAttributes<HTMLSpanElement> {
  children?: ReactNode;
  variant?: PillVariant;
  icon?: ReactNode;
  showIcon?: boolean;
  size?: "sm" | "md";
  className?: string;
}

const defaultIcons: Record<PillVariant, ReactNode> = {
  neutral: <HelpCircle className="h-3 w-3 shrink-0" />,
  success: <CheckCircle2 className="h-3 w-3 shrink-0 text-[var(--success)]" />,
  warn: <AlertTriangle className="h-3 w-3 shrink-0 text-[var(--warn)]" />,
  critical: <XCircle className="h-3 w-3 shrink-0 text-[var(--critical)]" />,
  info: <Info className="h-3 w-3 shrink-0 text-[var(--info)]" />,
};

export const Pill = forwardRef<HTMLSpanElement, PillProps>(
  (
    {
      children,
      variant = "neutral",
      icon,
      showIcon = true,
      size = "sm",
      className,
      ...props
    },
    ref
  ) => {
    // Check if the label contains PROVISIONAL or EXPERIMENTAL
    let resolvedVariant = variant;
    if (
      typeof children === "string" &&
      (children.toUpperCase().includes("PROVISIONAL") ||
        children.toUpperCase().includes("EXPERIMENTAL"))
    ) {
      resolvedVariant = "info";
    }

    const base =
      "inline-flex items-center font-medium rounded-pill border select-none transition-colors";

    const variantStyles: Record<PillVariant, string> = {
      neutral:
        "bg-[var(--surface-2)] text-[var(--text-secondary)] border-[var(--border-subtle)]",
      success:
        "bg-[color-mix(in_srgb,var(--success)_12%,transparent)] text-[var(--success)] border-[color-mix(in_srgb,var(--success)_28%,transparent)]",
      warn:
        "bg-[color-mix(in_srgb,var(--warn)_12%,transparent)] text-[var(--warn)] border-[color-mix(in_srgb,var(--warn)_28%,transparent)]",
      critical:
        "bg-[color-mix(in_srgb,var(--critical)_12%,transparent)] text-[var(--critical)] border-[color-mix(in_srgb,var(--critical)_28%,transparent)]",
      info:
        "bg-[color-mix(in_srgb,var(--info)_12%,transparent)] text-[var(--info)] border-[color-mix(in_srgb,var(--info)_28%,transparent)]",
    };

    const sizeStyles = {
      sm: "h-5 px-2 text-[11px] gap-1 tracking-wide",
      md: "h-6 px-2.5 text-xs gap-1.5",
    };

    const selectedIcon = icon !== undefined ? icon : showIcon ? defaultIcons[resolvedVariant] : null;

    return (
      <span
        ref={ref}
        className={twMerge(clsx(base, variantStyles[resolvedVariant], sizeStyles[size], className))}
        {...props}
      >
        {selectedIcon}
        <span className="truncate">{children}</span>
      </span>
    );
  }
);

Pill.displayName = "Pill";
