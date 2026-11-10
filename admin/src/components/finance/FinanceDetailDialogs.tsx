import { points } from "@/lib/points";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import type { AdminLedger, AdminOrder } from "@/api/client";
import { AdminDetailMeta, AdminDetailSection } from "@/components/admin/AdminDetailLayout";
import { AdminEntityLink } from "@/components/admin/AdminEntityLink";
import { AdminModal } from "@/components/admin/AdminModal";
import { Button } from "@/components/ui/button";

import { orderPaymentLabel } from "@/lib/orderPayment";
import { ledgerKindLabel, orderStatusLabel, payTypeLabel } from "@/lib/statusLabels";

/** 钱包关联对象链接：兼容数字订单 ID 与历史商户单号。 */
export function LedgerRefLink({ row }: { row: AdminLedger }) {
  if (row.ref_type === "order" && row.ref_id) {
    const id = Number(row.ref_id);
    if (Number.isFinite(id) && id > 0) {
      return <AdminEntityLink kind="order" id={id} label={`订单#${id}`} />;
    }
    return (
      <Link
        to={`/orders?tab=orders&trade=${encodeURIComponent(row.ref_id)}`}
        className="admin-link font-mono text-xs"
      >
        {row.ref_id}
      </Link>
    );
  }
  if (!row.ref_type && !row.ref_id) return "—";
  return (
    <span className="font-mono text-xs">
      {row.ref_type}/{row.ref_id}
    </span>
  );
}

/** 展示充值订单详情，复制单号与关闭行为由弹层管理。 */
export function OrderDetailDialog({
  orderDetail,
  open,
  onClose,
}: { orderDetail: AdminOrder | null; open: boolean; onClose: () => void }) {
  // 将商户单号写入剪贴板，并反馈复制结果。
  async function copyText(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      toast.success("已复制");
    } catch {
      toast.error("复制失败");
    }
  }

  return (
    <AdminModal
      open={open && !!orderDetail}
      onOpenChange={(nextOpen) => !nextOpen && onClose()}
      size="md"
      title={orderDetail ? `订单明细 #${orderDetail.id}` : "订单明细"}
      subtitle={orderDetail?.out_trade_no}
      footer={
        orderDetail ? (
          <Button size="sm" variant="outline" onClick={() => void copyText(orderDetail.out_trade_no)}>
            复制商户单号
          </Button>
        ) : undefined
      }
    >
      {orderDetail ? (
        <AdminDetailSection>
          <AdminDetailMeta
            items={[
              {
                label: "用户",
                value: (
                  <AdminEntityLink
                    kind="user"
                    id={orderDetail.user_id}
                    label={orderDetail.user_email ?? undefined}
                  />
                ),
              },
              { label: "SKU", value: orderDetail.sku_id },
              { label: "支付金额", value: orderPaymentLabel(orderDetail) },
              { label: "到账积分", value: points(orderDetail.credit_fen) },
              ...(orderDetail.payment_currency && orderDetail.payment_currency !== "cny" ? [{ label: "订单汇率", value: `1 ${orderDetail.payment_currency.toUpperCase()} = ${orderDetail.payment_exchange_rate || "—"} CNY` }] : []),
              { label: "支付方式", value: payTypeLabel(orderDetail.pay_type) },
              { label: "状态", value: orderStatusLabel(orderDetail.status) },
              { label: "渠道单号", value: orderDetail.trade_no || "—" },
              {
                label: "支付时间",
                value: orderDetail.paid_at ? new Date(orderDetail.paid_at).toLocaleString() : "—",
              },
              {
                label: "创建时间",
                value: new Date(orderDetail.created_at).toLocaleString(),
                full: true,
              },
            ]}
          />
        </AdminDetailSection>
      ) : null}
    </AdminModal>
  );
}

/** 展示钱包流水详情，复用列表中的关联对象链接。 */
export function LedgerDetailDialog({
  ledgerDetail,
  onClose,
}: { ledgerDetail: AdminLedger | null; onClose: () => void }) {
  return (
    <AdminModal
      open={!!ledgerDetail}
      onOpenChange={(nextOpen) => !nextOpen && onClose()}
      size="md"
      title={ledgerDetail ? `流水明细 #${ledgerDetail.id}` : "流水明细"}
    >
      {ledgerDetail ? (
        <AdminDetailSection>
          <AdminDetailMeta
            items={[
              {
                label: "用户",
                value: (
                  <AdminEntityLink
                    kind="user"
                    id={ledgerDetail.user_id}
                    label={ledgerDetail.user_email ?? undefined}
                  />
                ),
              },
              { label: "类型", value: ledgerKindLabel(ledgerDetail.kind) },
              { label: "变动", value: points(ledgerDetail.delta_fen) },
              { label: "剩余积分", value: points(ledgerDetail.balance_after) },
              { label: "关联", value: <LedgerRefLink row={ledgerDetail} /> },
              { label: "备注", value: ledgerDetail.note || "—" },
              {
                label: "时间",
                value: new Date(ledgerDetail.created_at).toLocaleString(),
                full: true,
              },
            ]}
          />
        </AdminDetailSection>
      ) : null}
    </AdminModal>
  );
}
