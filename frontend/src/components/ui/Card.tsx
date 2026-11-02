import { forwardRef, type HTMLAttributes, type ReactNode } from "react";
import clsx from "clsx";
import { twMerge } from "tailwind-merge";

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children?: ReactNode;
  variant?: "default" | "nested" | "glass" | "interactive";
  className?: string;
}

export const Card = forwardRef<HTMLDivElement, CardProps>(
  ({ children, variant = "default", className, ...props }, ref) => {
    const base = "transition-colors duration-150 relative";
    
    const variantStyles = {
      default: "bg-[var(--surface-1)] border border-[var(--border-subtle)] rounded-[12px]",
      nested: "bg-[var(--surface-2)] border border-[var(--border-subtle)] rounded-[8px]",
      glass: "glass-chrome rounded-[12px]",
      interactive: "bg-[var(--surface-1)] border border-[var(--border-subtle)] rounded-[12px] hover:border-[var(--accent)] hover:bg-[var(--surface-2)] cursor-pointer",
    };

    return (
      <div
        ref={ref}
        className={twMerge(clsx(base, variantStyles[variant], className))}
        {...props}
      >
        {children}
      </div>
    );
  }
);

Card.displayName = "Card";

export function CardHeader({
  title,
  subtitle,
  action,
  className,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={twMerge("flex items-start justify-between gap-3 p-4 border-b border-[var(--border-subtle)]", className)}>
      <div>
        <h3 className="font-display font-semibold text-base text-[var(--text-primary)]">
          {title}
        </h3>
        {subtitle && (
          <p className="text-xs text-[var(--text-secondary)] mt-0.5">
            {subtitle}
          </p>
        )}
      </div>
      {action && <div className="flex items-center gap-2">{action}</div>}
    </div>
  );
}

export function CardBody({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={twMerge("p-4", className)}>{children}</div>;
}
