import type { PageMeta } from "./common";

/** 充值订单、钱包流水与用量明细的接口契约；金额单位均为分。 */
export type AdminOrder = {
  id: number;
  out_trade_no: string;
  user_id: number;
  user_email?: string | null;
  sku_id: string;
  amount_fen: number;
  credit_fen: number;
  payment_currency?: "cny" | "usd" | "hkd" | null;
  payment_amount_minor?: number | null;
  payment_exchange_rate?: string | null;
  pay_type: string;
  status: string;
  trade_no?: string | null;
  paid_at?: string | null;
  created_at: string;
};

export type AdminLedger = {
  id: number;
  user_id: number;
  user_email?: string | null;
  delta_fen: number;
  balance_after: number;
  kind: string;
  ref_type: string;
  ref_id: string;
  note: string;
  created_at: string;
  /** 手动调账操作人邮箱（ref_type=admin 时） */
  operator_email?: string | null;
};

export type AdminUsageEventBrief = {
  billing_detail?: { mode: string; price_version: number; operation_id: string; model_id: string; resolution: string; duration?: number; unit_price_yuan: string; delivered: boolean; route: { channel_id: string; channel_name: string; upstream_model: string } } | null;
  id: number;
  billing_key: string;
  capability?: string | null;
  model?: string;
  total_tokens?: number;
  charge_fen?: number;
  estimated?: boolean;
  billing_basis?: string;
  billing_basis_label?: string;
  created_at?: string | null;
};

export type AdminUsageEvent = {
  id: number;
  user_id: number;
  user_email?: string | null;
  task_run_id?: number | null;
  domain?: string | null;
  capability?: string | null;
  billing_key: string;
  model?: string;
  total_tokens?: number;
  charge_fen?: number;
  estimated?: boolean;
  billing_basis?: string;
  billing_basis_label?: string;
  created_at?: string | null;
  task_domain?: string | null;
  task_type?: string | null;
  task_status?: string | null;
  project_id?: number | null;
  drama_project_id?: number | null;
  provider?: string | null;
};

export type AdminUsageEventListRes = {
  items: AdminUsageEvent[];
  meta: PageMeta;
};
