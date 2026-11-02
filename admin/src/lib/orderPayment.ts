type PaymentSnapshot = {
  amount_fen: number;
  payment_currency?: string | null;
  payment_amount_minor?: number | null;
};

/** Order snapshots describe the charge currency; legacy orders retain their CNY amount. */
export function orderPaymentLabel(order: PaymentSnapshot): string {
  const currency = (order.payment_currency || "cny").toLowerCase();
  const minor = order.payment_amount_minor ?? (currency === "cny" ? order.amount_fen : null);
  if (minor === null || !Number.isSafeInteger(minor) || minor < 0) return `${currency.toUpperCase()} —`;
  return `${currency.toUpperCase()} ${(minor / 100).toFixed(2)}`;
}
