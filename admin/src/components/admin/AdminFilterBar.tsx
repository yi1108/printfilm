import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

type AdminFilterBarProps = {
  children: ReactNode;
  trailing?: ReactNode;
  className?: string;
};

/** 管理端列表筛选条：单行紧凑横排，空间不足时自动换行 */
export function AdminFilterBar({ children, trailing, className }: AdminFilterBarProps) {
  return (
    <div className={cn("admin-filter-bar", className)}>
      <div className="admin-filter-bar-main">{children}</div>
      {trailing ? <div className="admin-filter-bar-trailing">{trailing}</div> : null}
    </div>
  );
}

type AdminFilterFieldProps = {
  label?: string;
  children: ReactNode;
  className?: string;
};

/** 筛选条内联字段：标签与控件同一行 */
export function AdminFilterField({ label, children, className }: AdminFilterFieldProps) {
  return (
    <label className={cn("admin-filter-inline", className)}>
      {label ? <span className="admin-filter-inline-label">{label}</span> : null}
      {children}
    </label>
  );
}
