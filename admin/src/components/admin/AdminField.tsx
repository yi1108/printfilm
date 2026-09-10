import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

type AdminFieldProps = {
  label?: string;
  hint?: string;
  className?: string;
  children: ReactNode;
};

// 管理端表单字段：标签 + 控件 + 可选说明
export function AdminField({ label, hint, className, children }: AdminFieldProps) {
  return (
    <div className={cn("admin-field", className)}>
      {label ? <label className="admin-field-label">{label}</label> : null}
      {children}
      {hint ? <p className="admin-field-hint">{hint}</p> : null}
    </div>
  );
}
