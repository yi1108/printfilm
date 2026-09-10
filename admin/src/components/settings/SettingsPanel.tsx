import type { ReactNode } from "react";
import { useEffect, useRef } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { useSettingsSaveSlot } from "@/components/settings/SettingsSaveContext";

type PanelProps = {
  title: string;
  description?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
};

// 配置分区面板：标题 + 内容
export function SettingsPanel({ title, description, actions, children, className }: PanelProps) {
  return (
    <section className={cn("settings-panel", className)}>
      <div className="settings-panel-header">
        <div className="min-w-0">
          <h3 className="settings-panel-title">{title}</h3>
          {description ? <p className="settings-panel-desc">{description}</p> : null}
        </div>
        {actions ? <div className="settings-panel-actions">{actions}</div> : null}
      </div>
      <div className="settings-panel-body">{children}</div>
    </section>
  );
}

type SettingsTabShellProps = {
  children: ReactNode;
  onSave?: () => void | Promise<void>;
  saving?: boolean;
  saveLabel?: string;
};

// Tab 内容区：把保存动作注册到页头，不再单独占一行工具条
export function SettingsTabShell({ children, onSave, saving, saveLabel = "保存" }: SettingsTabShellProps) {
  const { registerSave } = useSettingsSaveSlot();
  const onSaveRef = useRef(onSave);
  onSaveRef.current = onSave;

  useEffect(() => {
    if (!onSave) {
      registerSave(null);
      return () => registerSave(null);
    }
    registerSave({
      onSave: () => onSaveRef.current?.(),
      saving,
      label: saveLabel,
    });
    return () => registerSave(null);
  }, [onSave ? true : false, saving, saveLabel, registerSave]);

  return (
    <div className="settings-tab-shell">
      <div className="settings-tab-body">{children}</div>
    </div>
  );
}

// 加载占位
export function SettingsLoading({ label = "加载中…" }: { label?: string }) {
  return (
    <div className="settings-loading">
      <Loader2 className="h-4 w-4 animate-spin" />
      {label}
    </div>
  );
}

// 带图标的区块标题
export function SectionTitle({ icon, title }: { icon: ReactNode; title: string }) {
  return (
    <div className="settings-section-title">
      <span className="settings-section-icon">{icon}</span>
      <span>{title}</span>
    </div>
  );
}

// 表单标签 + 控件
export function LabeledControl({
  label,
  hint,
  children,
  className,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label className={cn("settings-field", className)}>
      <span className="settings-field-label">{label}</span>
      {children}
      {hint ? <span className="settings-field-hint">{hint}</span> : null}
    </label>
  );
}

// 内嵌子面板（浅灰底，用于状态条或独立分组）
export function SettingsSurface({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={cn("settings-surface", className)}>{children}</div>;
}

export type SettingsStatusItem = {
  id: string;
  label: string;
  ready: boolean;
  readyText?: string;
  pendingText?: string;
};

// 顶部就绪/状态条（与模型路由一致）
export function SettingsStatusBar({
  title,
  items,
  extra,
}: {
  title: string;
  items: SettingsStatusItem[];
  extra?: ReactNode;
}) {
  return (
    <SettingsSurface className="settings-readiness-bar">
      <div className="settings-readiness-title-row">
        <div className="settings-readiness-title">{title}</div>
        {extra}
      </div>
      <div className="settings-readiness-row">
        {items.map((item) => (
          <div key={item.id} className={cn("settings-readiness-item", item.ready && "is-ready")}>
            <span className={cn("settings-readiness-dot", item.ready ? "is-on" : "is-off")} />
            <span>{item.label}</span>
            <em>{item.ready ? item.readyText ?? "已配置" : item.pendingText ?? "未就绪"}</em>
          </div>
        ))}
      </div>
    </SettingsSurface>
  );
}
