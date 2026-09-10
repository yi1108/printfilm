import type { ReactNode } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

type AdminModalSize = "md" | "lg" | "xl" | "full";

type AdminModalProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  subtitle?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  size?: AdminModalSize;
  className?: string;
  bodyClassName?: string;
};

const SIZE_CLASS: Record<AdminModalSize, string> = {
  md: "admin-modal--md",
  lg: "admin-modal--lg",
  xl: "admin-modal--xl",
  full: "admin-modal--full",
};

// 管理端统一弹窗壳（标题 / 内容 / 底栏）
export function AdminModal({
  open,
  onOpenChange,
  title,
  subtitle,
  children,
  footer,
  size = "lg",
  className,
  bodyClassName,
}: AdminModalProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn("admin-modal", SIZE_CLASS[size], className)}>
        <DialogHeader className="admin-modal-header">
          <DialogTitle className="admin-modal-title">{title}</DialogTitle>
          {subtitle ? <p className="admin-modal-subtitle">{subtitle}</p> : null}
        </DialogHeader>
        {children ? <div className={cn("admin-modal-body", bodyClassName)}>{children}</div> : null}
        {footer ? <div className="admin-modal-footer">{footer}</div> : null}
      </DialogContent>
    </Dialog>
  );
}
