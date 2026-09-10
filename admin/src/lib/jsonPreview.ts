/** Compact JSON preview for admin task list / tooltips. */

// 将对象压成单行摘要；空值返回 —
export function compactJsonPreview(value: unknown, maxLen = 96): string {
  if (value == null) return "—";
  if (typeof value === "string") {
    const t = value.trim();
    if (!t) return "—";
    return t.length > maxLen ? `${t.slice(0, maxLen)}…` : t;
  }
  if (typeof value !== "object") {
    const s = String(value);
    return s.length > maxLen ? `${s.slice(0, maxLen)}…` : s;
  }
  if (Array.isArray(value) && value.length === 0) return "[]";
  if (!Array.isArray(value) && Object.keys(value as object).length === 0) return "—";
  try {
    const s = JSON.stringify(value);
    if (!s || s === "{}" || s === "[]") return "—";
    return s.length > maxLen ? `${s.slice(0, maxLen)}…` : s;
  } catch {
    return "—";
  }
}

// 美化多行 JSON（详情弹窗）
export function prettyJson(value: unknown): string {
  if (value == null) return "—";
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

// 是否有可展示的 JSON 内容
export function hasJsonContent(value: unknown): boolean {
  if (value == null) return false;
  if (typeof value === "string") return value.trim().length > 0;
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === "object") return Object.keys(value as object).length > 0;
  return true;
}
