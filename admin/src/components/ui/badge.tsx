import * as React from "react";
import { cn } from "@/lib/utils";

// Status / tag badge — soft admin chips
export function Badge({
  className,
  variant = "default",
  ...props
}: React.ComponentProps<"span"> & {
  variant?: "default" | "secondary" | "outline" | "destructive" | "success" | "warning" | "info";
}) {
  const variants = {
    default: "border-transparent bg-[var(--admin-text)] text-white",
    secondary: "border-transparent bg-[#f1f5f9] text-[var(--admin-muted)]",
    outline: "border-[var(--admin-border)] bg-white text-[var(--admin-muted)]",
    destructive: "border-transparent bg-[#fef2f2] text-[#dc2626]",
    success: "border-transparent bg-[var(--admin-accent-soft)] text-[var(--admin-forest)]",
    warning: "border-transparent bg-[#fff7ed] text-[#c2410c]",
    info: "border-transparent bg-[var(--admin-tag-bg)] text-[var(--admin-tag-text)]",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold tracking-wide",
        variants[variant],
        className,
      )}
      {...props}
    />
  );
}
