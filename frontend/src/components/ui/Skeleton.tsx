import { type HTMLAttributes } from "react";
import clsx from "clsx";
import { twMerge } from "tailwind-merge";

export interface SkeletonProps extends HTMLAttributes<HTMLDivElement> {
  className?: string;
  circle?: boolean;
}

export function Skeleton({ className, circle = false, ...props }: SkeletonProps) {
  return (
    <div
      className={twMerge(
        clsx(
          "skeleton",
          circle ? "rounded-full" : "rounded-nested",
          className
        )
      )}
      {...props}
    />
  );
}
