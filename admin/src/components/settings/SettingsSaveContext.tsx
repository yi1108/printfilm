import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type SettingsSaveAction = {
  onSave: () => void | Promise<void>;
  saving?: boolean;
  label?: string;
};

type SettingsSaveContextValue = {
  action: SettingsSaveAction | null;
  registerSave: (action: SettingsSaveAction | null) => void;
};

const SettingsSaveContext = createContext<SettingsSaveContextValue | null>(null);

// 设置页：子 Tab 注册保存动作，页头渲染统一「保存」按钮
export function SettingsSaveProvider({ children }: { children: ReactNode }) {
  const [action, setAction] = useState<SettingsSaveAction | null>(null);
  const registerSave = useCallback((next: SettingsSaveAction | null) => {
    setAction((prev) => {
      if (!prev && !next) return prev;
      if (
        prev &&
        next &&
        prev.saving === next.saving &&
        (prev.label ?? "保存") === (next.label ?? "保存")
      ) {
        // 同步最新 onSave，避免闭包过期；不触发无意义重渲染依赖
        prev.onSave = next.onSave;
        return prev;
      }
      return next;
    });
  }, []);
  const value = useMemo(() => ({ action, registerSave }), [action, registerSave]);
  return <SettingsSaveContext.Provider value={value}>{children}</SettingsSaveContext.Provider>;
}

export function useSettingsSaveSlot() {
  const ctx = useContext(SettingsSaveContext);
  if (!ctx) {
    throw new Error("useSettingsSaveSlot must be used within SettingsSaveProvider");
  }
  return ctx;
}

// Tab 挂载时注册保存；卸载时清空
export function useRegisterSettingsSave(action: SettingsSaveAction | null) {
  const { registerSave } = useSettingsSaveSlot();
  useEffect(() => {
    registerSave(action);
    return () => registerSave(null);
  }, [action, registerSave]);
}
