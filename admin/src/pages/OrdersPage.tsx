import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { api, type AdminLedger, type AdminOrder, type AdminUsageEventListRes, type PageMeta } from "@/api/client";
import { AdminDateRangeFilter } from "@/components/admin/AdminDateRangeFilter";
import { AdminDetailMeta, AdminDetailSection } from "@/components/admin/AdminDetailLayout";
import { AdminEntityLink } from "@/components/admin/AdminEntityLink";
import { AdminFilterBar } from "@/components/admin/AdminFilterBar";
import { AdminModal } from "@/components/admin/AdminModal";
import { AdminUserSearchSelect } from "@/components/admin/AdminUserSearchSelect";
import { PaginationBar } from "@/components/PaginationBar";
import { DEFAULT_PAGE_SIZE } from "@/lib/pagination";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader } from "@/components/ui/page";
import { useAdminDetailQuery } from "@/hooks/useAdminDetailQuery";
import { fenToYuan } from "@/lib/utils";
import { ledgerKindLabel, orderStatusLabel, payTypeLabel, taskDomainLabel } from "@/lib/statusLabels";

type OrderRes = { items: AdminOrder[]; meta: PageMeta };
type LedgerRes = { items: AdminLedger[]; meta: PageMeta };

const ORDER_TABS = new Set(["orders", "ledger", "usage"]);

function tabFromSearch(raw: string | null): string {
  return raw && ORDER_TABS.has(raw) ? raw : "orders";
}

function ledgerRefLink(row: AdminLedger) {
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

// 充值订单、钱包流水与用量明细
export function OrdersPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [tab, setTab] = useState(() => tabFromSearch(searchParams.get("tab")));
  const [orderStatus, setOrderStatus] = useState("");
  const [orderUserId, setOrderUserId] = useState<number | null>(null);
  const [ledgerKind, setLedgerKind] = useState("");
  const [ledgerUserId, setLedgerUserId] = useState<number | null>(null);
  const [orderPage, setOrderPage] = useState(1);
  const [ledgerPage, setLedgerPage] = useState(1);
  const [usagePage, setUsagePage] = useState(1);
  const [usageUserId, setUsageUserId] = useState<number | null>(null);
  const [usageTaskId, setUsageTaskId] = useState("");
  const [usageDomain, setUsageDomain] = useState("");
  const [usageBillingKey, setUsageBillingKey] = useState("");
  const [usageCapability, setUsageCapability] = useState("");
  const [usageBasis, setUsageBasis] = useState("");
  const [usageDateFrom, setUsageDateFrom] = useState("");
  const [usageDateTo, setUsageDateTo] = useState("");
  const [orders, setOrders] = useState<OrderRes | null>(null);
  const [ledger, setLedger] = useState<LedgerRes | null>(null);
  const [usage, setUsage] = useState<AdminUsageEventListRes | null>(null);
  const [orderDetail, setOrderDetail] = useState<AdminOrder | null>(null);
  const [ledgerDetail, setLedgerDetail] = useState<AdminLedger | null>(null);
  const orderQuery = useAdminDetailQuery("order");

  async function loadOrders(page = orderPage) {
    try {
      const params = new URLSearchParams({ page: String(page), page_size: String(DEFAULT_PAGE_SIZE) });
      if (orderStatus) params.set("status", orderStatus);
      if (orderUserId) params.set("user_id", String(orderUserId));
      setOrders(await api<OrderRes>(`/api/admin/orders?${params}`));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "加载订单失败");
    }
  }

  async function loadLedger(page = ledgerPage) {
    try {
      const params = new URLSearchParams({ page: String(page), page_size: String(DEFAULT_PAGE_SIZE) });
      if (ledgerKind) params.set("kind", ledgerKind);
      if (ledgerUserId) params.set("user_id", String(ledgerUserId));
      setLedger(await api<LedgerRes>(`/api/admin/ledger?${params}`));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "加载流水失败");
    }
  }

  async function loadUsage(
    page = usagePage,
    overrides?: { billing_key?: string; capability?: string },
  ) {
    try {
      const params = new URLSearchParams({ page: String(page), page_size: String(DEFAULT_PAGE_SIZE) });
      if (usageUserId) params.set("user_id", String(usageUserId));
      if (usageTaskId.trim()) params.set("task_run_id", usageTaskId.trim());
      if (usageDomain) params.set("domain", usageDomain);
      const billingKey = overrides?.billing_key ?? usageBillingKey.trim();
      const capability = overrides?.capability ?? usageCapability.trim();
      if (billingKey) params.set("billing_key", billingKey);
      if (capability) params.set("capability", capability);
      if (usageBasis) params.set("billing_basis", usageBasis);
      if (usageDateFrom) params.set("created_from", `${usageDateFrom}T00:00:00`);
      if (usageDateTo) params.set("created_to", `${usageDateTo}T23:59:59`);
      setUsage(await api<AdminUsageEventListRes>(`/api/admin/usage-events?${params}`));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "加载用量失败");
    }
  }

  useEffect(() => {
    const next = tabFromSearch(searchParams.get("tab"));
    setTab((prev) => (prev === next ? prev : next));
  }, [searchParams]);

  useEffect(() => {
    void loadOrders();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orderPage]);

  useEffect(() => {
    void loadLedger();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ledgerPage]);

  useEffect(() => {
    void loadUsage();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [usagePage]);

  useEffect(() => {
    if (!orderQuery.id || !orders?.items) return;
    const hit = orders.items.find((o) => o.id === orderQuery.id);
    if (hit) setOrderDetail(hit);
  }, [orderQuery.id, orders?.items]);

  useEffect(() => {
    const tradeNo = searchParams.get("trade");
    if (!tradeNo) return;
    void (async () => {
      try {
        const res = await api<OrderRes>(
          `/api/admin/orders?page=1&page_size=1&out_trade_no=${encodeURIComponent(tradeNo)}`,
        );
        const hit = res.items[0];
        if (hit) {
          setOrderDetail(hit);
          orderQuery.open(hit.id);
        }
      } catch {
        /* 深链失败时静默，用户仍可手动筛选 */
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  function onTabChange(next: string) {
    setTab(next);
    const params = new URLSearchParams(searchParams);
    if (next === "orders") params.delete("tab");
    else params.set("tab", next);
    setSearchParams(params, { replace: true });
  }

  async function copyText(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      toast.success("已复制");
    } catch {
      toast.error("复制失败");
    }
  }

  return (
    <div className="admin-list-page">
      <PageHeader description="查看充值单、钱包流水与 AI 用量明细" />
      <Tabs value={tab} onValueChange={onTabChange}>
        <TabsList>
          <TabsTrigger value="orders">充值订单</TabsTrigger>
          <TabsTrigger value="ledger">钱包流水</TabsTrigger>
          <TabsTrigger value="usage">用量明细</TabsTrigger>
        </TabsList>
        <TabsContent value="orders" className="space-y-4">
          <AdminFilterBar>
            <Select value={orderStatus} onChange={(e) => setOrderStatus(e.target.value)}>
              <option value="">全部状态</option>
              <option value="pending">待支付</option>
              <option value="paid">已支付</option>
              <option value="closed">已关闭</option>
            </Select>
            <AdminUserSearchSelect value={orderUserId} onChange={(id) => setOrderUserId(id)} />
            <Button
              size="sm"
              variant="secondary"
              className="admin-filter-action"
              onClick={() => {
                setOrderPage(1);
                void loadOrders(1);
              }}
            >
              筛选
            </Button>
          </AdminFilterBar>
          <div className="rounded-lg border bg-background">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>ID</TableHead>
                  <TableHead>商户单号</TableHead>
                  <TableHead>用户</TableHead>
                  <TableHead>SKU</TableHead>
                  <TableHead>金额</TableHead>
                  <TableHead>入账</TableHead>
                  <TableHead>支付</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>渠道单号</TableHead>
                  <TableHead>支付时间</TableHead>
                  <TableHead>创建时间</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(orders?.items ?? []).map((o) => (
                  <TableRow
                    key={o.id}
                    className="cursor-pointer"
                    onClick={() => {
                      setOrderDetail(o);
                      orderQuery.open(o.id);
                    }}
                  >
                    <TableCell>{o.id}</TableCell>
                    <TableCell className="font-mono text-xs">{o.out_trade_no}</TableCell>
                    <TableCell>
                      <AdminEntityLink kind="user" id={o.user_id} label={o.user_email ?? undefined} />
                    </TableCell>
                    <TableCell>{o.sku_id}</TableCell>
                    <TableCell>¥{fenToYuan(o.amount_fen)}</TableCell>
                    <TableCell>¥{fenToYuan(o.credit_fen)}</TableCell>
                    <TableCell>{payTypeLabel(o.pay_type)}</TableCell>
                    <TableCell>
                      <Badge variant={o.status === "paid" ? "success" : "secondary"}>
                        {orderStatusLabel(o.status)}
                      </Badge>
                    </TableCell>
                    <TableCell className="font-mono text-xs">{o.trade_no || "—"}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {o.paid_at ? new Date(o.paid_at).toLocaleString() : "—"}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {new Date(o.created_at).toLocaleString()}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          {orders && (
            <PaginationBar
              page={orders.meta.page}
              pageSize={orders.meta.page_size}
              total={orders.meta.total}
              onPageChange={setOrderPage}
            />
          )}
        </TabsContent>
        <TabsContent value="ledger" className="space-y-4">
          <AdminFilterBar>
            <Select value={ledgerKind} onChange={(e) => setLedgerKind(e.target.value)}>
              <option value="">全部类型</option>
              <option value="topup">充值</option>
              <option value="grant">赠送</option>
              <option value="adjust">调账</option>
              <option value="freeze">冻结</option>
              <option value="unfreeze">解冻</option>
              <option value="settle">结算</option>
              <option value="refund">退款</option>
            </Select>
            <AdminUserSearchSelect value={ledgerUserId} onChange={(id) => setLedgerUserId(id)} />
            <Button
              size="sm"
              variant="secondary"
              className="admin-filter-action"
              onClick={() => {
                setLedgerPage(1);
                void loadLedger(1);
              }}
            >
              筛选
            </Button>
          </AdminFilterBar>
          <div className="rounded-lg border bg-background">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>ID</TableHead>
                  <TableHead>用户</TableHead>
                  <TableHead>变动</TableHead>
                  <TableHead>余额后</TableHead>
                  <TableHead>类型</TableHead>
                  <TableHead>关联</TableHead>
                  <TableHead>备注</TableHead>
                  <TableHead>时间</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(ledger?.items ?? []).map((e) => (
                  <TableRow key={e.id} className="cursor-pointer" onClick={() => setLedgerDetail(e)}>
                    <TableCell>{e.id}</TableCell>
                    <TableCell>
                      <AdminEntityLink kind="user" id={e.user_id} label={e.user_email ?? undefined} />
                    </TableCell>
                    <TableCell className={e.delta_fen >= 0 ? "text-emerald-700" : "text-red-600"}>
                      {e.delta_fen >= 0 ? "+" : ""}
                      ¥{fenToYuan(e.delta_fen)}
                    </TableCell>
                    <TableCell>¥{fenToYuan(e.balance_after)}</TableCell>
                    <TableCell>
                      <Badge variant="secondary">{ledgerKindLabel(e.kind)}</Badge>
                    </TableCell>
                    <TableCell>{ledgerRefLink(e)}</TableCell>
                    <TableCell className="max-w-[200px] truncate">{e.note}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {new Date(e.created_at).toLocaleString()}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          {ledger && (
            <PaginationBar
              page={ledger.meta.page}
              pageSize={ledger.meta.page_size}
              total={ledger.meta.total}
              onPageChange={setLedgerPage}
            />
          )}
        </TabsContent>
        <TabsContent value="usage" className="space-y-4">
          <AdminFilterBar>
            <AdminUserSearchSelect value={usageUserId} onChange={(id) => setUsageUserId(id)} />
            <Input placeholder="任务 ID" value={usageTaskId} onChange={(e) => setUsageTaskId(e.target.value)} />
            <Select value={usageDomain} onChange={(e) => setUsageDomain(e.target.value)}>
              <option value="">全部领域</option>
              <option value="kepu">科普</option>
              <option value="drama">漫剧</option>
              <option value="studio">工作室</option>
              <option value="api">开放 API</option>
            </Select>
            <Input
              placeholder="billing_key"
              value={usageBillingKey}
              onChange={(e) => setUsageBillingKey(e.target.value)}
            />
            <Select value={usageCapability} onChange={(e) => setUsageCapability(e.target.value)}>
              <option value="">全部能力</option>
              <option value="llm">LLM 文本</option>
              <option value="image">生图</option>
              <option value="video">视频</option>
              <option value="tts">配音</option>
            </Select>
            <Select value={usageBasis} onChange={(e) => setUsageBasis(e.target.value)}>
              <option value="">全部计费依据</option>
              <option value="estimate">估算</option>
              <option value="upstream">实测（火山）</option>
              <option value="upstream_usage">实测(token)</option>
              <option value="upstream_cost">实测(费用)</option>
            </Select>
            <AdminDateRangeFilter
              from={usageDateFrom}
              to={usageDateTo}
              onChange={({ from, to }) => {
                setUsageDateFrom(from);
                setUsageDateTo(to);
              }}
            />
            <Button
              size="sm"
              variant="outline"
              className="admin-filter-action"
              onClick={() => {
                setUsageBillingKey("llm_chat");
                setUsageCapability("llm");
                setUsagePage(1);
                void loadUsage(1, { billing_key: "llm_chat", capability: "llm" });
              }}
            >
              LLM 用量
            </Button>
            <Button
              size="sm"
              variant="secondary"
              className="admin-filter-action"
              onClick={() => {
                setUsagePage(1);
                void loadUsage(1);
              }}
            >
              筛选
            </Button>
          </AdminFilterBar>
          <div className="rounded-lg border bg-background">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>时间</TableHead>
                  <TableHead>用户</TableHead>
                  <TableHead>任务</TableHead>
                  <TableHead>项目</TableHead>
                  <TableHead>领域</TableHead>
                  <TableHead>能力</TableHead>
                  <TableHead>模型</TableHead>
                  <TableHead>Tokens</TableHead>
                  <TableHead>扣费</TableHead>
                  <TableHead>上游成本</TableHead>
                  <TableHead>计费依据</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(usage?.items ?? []).map((row) => (
                  <TableRow key={row.id}>
                    <TableCell className="text-xs text-muted-foreground">
                      {row.created_at ? new Date(row.created_at).toLocaleString() : "—"}
                    </TableCell>
                    <TableCell>
                      <AdminEntityLink kind="user" id={row.user_id} label={row.user_email ?? undefined} />
                    </TableCell>
                    <TableCell>
                      {row.task_run_id ? (
                        <AdminEntityLink kind="task" id={row.task_run_id} />
                      ) : (
                        "历史/未关联"
                      )}
                    </TableCell>
                    <TableCell className="text-xs">
                      {row.project_id ? (
                        <AdminEntityLink kind="project" id={row.project_id} />
                      ) : row.drama_project_id ? (
                        <AdminEntityLink kind="drama" id={row.drama_project_id} />
                      ) : (
                        "—"
                      )}
                    </TableCell>
                    <TableCell>{row.domain ? taskDomainLabel(row.domain) : "—"}</TableCell>
                    <TableCell>{row.capability ?? row.billing_key}</TableCell>
                    <TableCell className="max-w-[120px] truncate text-xs">{row.model || "—"}</TableCell>
                    <TableCell>{row.total_tokens ?? 0}</TableCell>
                    <TableCell>¥{fenToYuan(row.charge_fen ?? 0)}</TableCell>
                    <TableCell>¥{fenToYuan(row.cost_fen ?? 0)}</TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          row.billing_basis === "estimate" || row.estimated
                            ? "secondary"
                            : "success"
                        }
                        title={
                          row.billing_basis === "upstream_cost"
                            ? "按火山返回的实际费用 × markup"
                            : row.billing_basis === "upstream_usage"
                              ? "按火山返回的 usage token × 配置单价 × markup"
                              : "上游未返回 usage，按配置估算 token 扣费"
                        }
                      >
                        {row.billing_basis_label ?? (row.estimated ? "估算" : "实测")}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          {usage && (
            <PaginationBar
              page={usage.meta.page}
              pageSize={usage.meta.page_size}
              total={usage.meta.total}
              onPageChange={setUsagePage}
            />
          )}
        </TabsContent>
      </Tabs>

      <AdminModal
        open={orderQuery.isOpen && !!orderDetail}
        onOpenChange={(open) => {
          if (!open) {
            setOrderDetail(null);
            orderQuery.close();
          }
        }}
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
                { label: "金额", value: `¥${fenToYuan(orderDetail.amount_fen)}` },
                { label: "入账", value: `¥${fenToYuan(orderDetail.credit_fen)}` },
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

      <AdminModal
        open={!!ledgerDetail}
        onOpenChange={(open) => !open && setLedgerDetail(null)}
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
                { label: "变动", value: `¥${fenToYuan(ledgerDetail.delta_fen)}` },
                { label: "余额后", value: `¥${fenToYuan(ledgerDetail.balance_after)}` },
                { label: "关联", value: ledgerRefLink(ledgerDetail) },
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
    </div>
  );
}
