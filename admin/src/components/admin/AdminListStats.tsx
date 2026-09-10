import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export type AdminListStatItem = {
  label: string;
  value: ReactNode;
  hint?: string;
};

type AdminListStatsProps = {
  items: AdminListStatItem[];
  className?: string;
};

/** 列表页顶部指标卡（白底简洁样式） */
export function AdminListStats({ items, className }: AdminListStatsProps) {
  if (items.length === 0) return null;
  return (
    <div className={cn("admin-list-stats", className)}>
      {items.map((item) => (
        <div key={item.label} className="admin-list-stat-card">
          <div className="admin-list-stat-label">{item.label}</div>
          <div className="admin-list-stat-value">{item.value}</div>
          {item.hint ? <div className="admin-list-stat-hint">{item.hint}</div> : null}
        </div>
      ))}
    </div>
  );
}
