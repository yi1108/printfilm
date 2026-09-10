/** 公开账号 ID 展示：不足四位补零 */
export function formatAccountId(userId: number): string {
  const n = Math.max(0, Math.floor(userId));
  if (n < 10000) return String(n).padStart(4, "0");
  return String(n);
}

/** 从搜索词解析账号 ID（支持 0001 或纯数字） */
export function parseAccountIdQuery(raw: string): number | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  const digits = trimmed.replace(/^0+/, "") || "0";
  const n = Number(digits);
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : null;
}
