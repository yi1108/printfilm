import * as React from "react";
import { cn } from "@/lib/utils";

// 管理端统一下拉选择
export function Select({ className, ...props }: React.ComponentProps<"select">) {
  return <select className={cn("admin-control admin-select", className)} {...props} />;
}

// 管理端统一多行文本
export function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return <textarea className={cn("admin-control admin-textarea", className)} {...props} />;
}
