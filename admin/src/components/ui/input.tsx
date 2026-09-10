import * as React from "react";
import { cn } from "@/lib/utils";

// 管理端统一文本输入
export function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      className={cn("admin-control", className)}
      {...props}
    />
  );
}
