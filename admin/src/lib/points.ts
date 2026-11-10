/** Account quantities only. Payment, costs and creator revenue remain money. */
export function points(value: unknown): string {
  return typeof value === 'number' && Number.isSafeInteger(value) ? `${value.toLocaleString('zh-CN')} 积分` : '—';
}

export function parsePoints(value: string, max = Number.MAX_SAFE_INTEGER): number | null {
  const text = value.trim();
  if (!/^\d+$/.test(text)) return null;
  const amount = Number(text);
  return Number.isSafeInteger(amount) && amount <= max ? amount : null;
}
