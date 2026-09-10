import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

type PageHeaderProps = {
  title?: string;
  description?: string;
  actions?: ReactNode;
  className?: string;
};

// 统一页面标题区（标题由顶栏展示，此处仅描述与操作）
export function PageHeader({ description, actions, className }: PageHeaderProps) {
  if (!description && !actions) return null;
  return (
    <div className={cn("admin-page-header", className)}>
      {description ? <p className="admin-page-desc">{description}</p> : null}
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

type EmptyStateProps = {
  title?: string;
  description?: string;
  className?: string;
};

// 空列表占位
export function EmptyState({
  title = "暂无数据",
  description = "换个筛选条件再试试",
  className,
}: EmptyStateProps) {
  return (
    <div className={cn("admin-empty", className)}>
      <div className="admin-empty-icon">∅</div>
      <div className="admin-empty-title">{title}</div>
      <div className="admin-empty-desc">{description}</div>
    </div>
  );
}

type ToolbarProps = {
  children: ReactNode;
  className?: string;
};

// 筛选 / 搜索工具条（与 AdminFilterBar 一致）
export function Toolbar({ children, className }: ToolbarProps) {
  return (
    <div className={cn("admin-filter-bar", className)}>
      <div className="admin-filter-bar-main">{children}</div>
    </div>
  );
}
