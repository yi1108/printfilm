import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-[10px] text-sm font-semibold transition-all duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--admin-accent-ring)] focus-visible:ring-offset-1 disabled:pointer-events-none disabled:opacity-45 active:scale-[0.98]",
  {
    variants: {
      variant: {
        default:
          "bg-[var(--admin-forest)] text-white shadow-[0_4px_12px_rgba(31,92,72,0.22)] hover:bg-[var(--admin-forest-deep)]",
        secondary:
          "border border-[var(--admin-border)] bg-white text-[var(--admin-text)] hover:border-[#c5d4cc] hover:bg-[#f8fafc]",
        outline:
          "border border-[var(--admin-border)] bg-white text-[var(--admin-muted)] hover:border-[rgba(61,154,114,0.35)] hover:text-[var(--admin-forest)]",
        ghost: "text-[var(--admin-muted)] hover:bg-[var(--admin-accent-soft)] hover:text-[var(--admin-forest)]",
        destructive:
          "bg-[#ef4444] text-white shadow-sm hover:bg-[#dc2626]",
        soft: "bg-[var(--admin-accent-soft)] text-[var(--admin-forest)] hover:bg-[rgba(61,154,114,0.18)]",
      },
      size: {
        default: "h-9 px-4",
        sm: "h-8 rounded-[9px] px-3 text-xs",
        lg: "h-10 rounded-[10px] px-6",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

// Admin primary action button
export function Button({ className, variant, size, asChild = false, ...props }: ButtonProps) {
  const Comp = asChild ? Slot : "button";
  return <Comp className={cn(buttonVariants({ variant, size, className }))} {...props} />;
}
