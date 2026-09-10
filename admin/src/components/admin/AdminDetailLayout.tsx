import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

type MetaItem = {
  label: string;
  value: ReactNode;
  full?: boolean;
};

type StatItem = {
  label: string;
  value: ReactNode;
};

/** 详情弹窗分区标题 + 内容 */
export function AdminDetailSection({
  title,
  children,
  className,
}: {
  title?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("admin-detail-section", className)}>
      {title ? <h4 className="admin-detail-section-title">{title}</h4> : null}
      {children}
    </section>
  );
}

/** 只读 key-value 网格（基本信息） */
export function AdminDetailMeta({ items }: { items: MetaItem[] }) {
  return (
    <dl className="admin-detail-meta">
      {items.map((item) => (
        <div
          key={item.label}
          className={cn("admin-detail-meta-item", item.full && "admin-detail-meta-item--full")}
        >
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** 费用/指标四宫格 */
export function AdminDetailStatGrid({ items }: { items: StatItem[] }) {
  return (
    <div className="admin-detail-stat-grid">
      {items.map((item) => (
        <div key={item.label} className="admin-detail-stat-card">
          <div className="admin-detail-stat-label">{item.label}</div>
          <div className="admin-detail-stat-value">{item.value}</div>
        </div>
      ))}
    </div>
  );
}

/** 弹窗内嵌表格容器 */
export function AdminDetailTableWrap({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={cn("admin-detail-table-wrap", className)}>{children}</div>;
}

/** 备注/脚本文本块 */
export function AdminDetailNote({
  children,
  empty = false,
  className,
}: {
  children: ReactNode;
  empty?: boolean;
  className?: string;
}) {
  return (
    <div className={cn("admin-detail-note", empty && "admin-detail-note--empty", className)}>
      {children}
    </div>
  );
}
