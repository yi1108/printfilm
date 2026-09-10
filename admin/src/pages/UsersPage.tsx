import { useEffect, useState } from "react";
import { toast } from "sonner";
import { api, type AdminStats, type AdminUserRow, type PageMeta } from "@/api/client";
import { AdminField } from "@/components/admin/AdminField";
import { AdminFilterBar } from "@/components/admin/AdminFilterBar";
import { AdminListStats } from "@/components/admin/AdminListStats";
import { AdminModal } from "@/components/admin/AdminModal";
import { AdminSearchInput } from "@/components/admin/AdminSearchInput";
import { UserDetailDrawer } from "@/components/admin/UserDetailDrawer";
import { PaginationBar } from "@/components/PaginationBar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EmptyState, PageHeader } from "@/components/ui/page";
import { Select } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useAdminDetailQuery } from "@/hooks/useAdminDetailQuery";
import { formatAccountId } from "@/lib/admin-account";
import { DEFAULT_PAGE_SIZE } from "@/lib/pagination";
import { fenToYuan } from "@/lib/utils";

type ListRes = { items: AdminUserRow[]; meta: PageMeta };

// 用户管理：搜索、筛选、只读明细与编辑
export function UsersPage() {
  const [q, setQ] = useState("");
  const [planFilter, setPlanFilter] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [data, setData] = useState<ListRes | null>(null);
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState<AdminUserRow | null>(null);
  const [detailUser, setDetailUser] = useState<AdminUserRow | null>(null);
  const [form, setForm] = useState({
    plan: "free",
    role: "user",
    balance_yuan: "0",
    balance_note: "",
  });
  const [saving, setSaving] = useState(false);
  const userDetail = useAdminDetailQuery("user");

  async function load(nextPage = page, nextQ = q, nextSize = pageSize) {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        page: String(nextPage),
        page_size: String(nextSize),
      });
      if (nextQ.trim()) params.set("q", nextQ.trim());
      if (planFilter) params.set("plan", planFilter);
      if (roleFilter) params.set("role", roleFilter);
      const res = await api<ListRes>(`/api/admin/users?${params}`);
      setData(res);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, pageSize]);

  useEffect(() => {
    void api<AdminStats>("/api/admin/stats?days=7")
      .then(setStats)
      .catch((err) => {
        setStats(null);
        toast.error(err instanceof Error ? err.message : "统计加载失败");
      });
  }, []);

  useEffect(() => {
    if (!userDetail.id || !data?.items) return;
    const hit = data.items.find((u) => u.id === userDetail.id);
    if (hit) setDetailUser(hit);
  }, [userDetail.id, data?.items]);

  function openEdit(user: AdminUserRow) {
    setEditing(user);
    setForm({
      plan: user.plan || "free",
      role: user.role || "user",
      balance_yuan: fenToYuan(user.balance_fen),
      balance_note: "",
    });
  }

  async function saveEdit() {
    if (!editing) return;
    setSaving(true);
    try {
      const balanceFen = Math.round(parseFloat(form.balance_yuan || "0") * 100);
      if (Number.isNaN(balanceFen)) throw new Error("余额格式无效");
      await api(`/api/admin/users/${editing.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          plan: form.plan,
          role: form.role,
          balance_fen: balanceFen,
          balance_note: form.balance_note || undefined,
        }),
      });
      toast.success("已保存");
      setEditing(null);
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  function applyFilters() {
    setPage(1);
    void load(1, q, pageSize);
  }

  return (
    <div className="admin-list-page">
      <PageHeader description="搜索用户，调整套餐与余额" />

      <AdminFilterBar>
        <AdminSearchInput
          value={q}
          onChange={setQ}
          placeholder="搜索邮箱 / 昵称 / 账号 ID"
          onKeyDown={(e) => {
            if (e.key === "Enter") applyFilters();
          }}
        />
        <Select value={planFilter} onChange={(e) => setPlanFilter(e.target.value)}>
          <option value="">全部套餐</option>
          <option value="free">free</option>
          <option value="pro">pro</option>
          <option value="team">team</option>
        </Select>
        <Select value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)}>
          <option value="">全部角色</option>
          <option value="user">user</option>
          <option value="admin">admin</option>
        </Select>
        <Button size="sm" className="admin-filter-action" onClick={applyFilters} disabled={loading}>
          {loading ? "加载中…" : "搜索"}
        </Button>
      </AdminFilterBar>

      <AdminListStats
        items={[
          { label: "总用户数", value: stats?.user_count ?? (loading ? "…" : "—") },
          {
            label: "本月调用",
            value: stats != null ? (stats.usage_calls_month ?? 0) : loading ? "…" : "—",
            hint: stats ? `今日 ${stats.usage_calls_today ?? 0} 次` : undefined,
          },
          {
            label: "累计调用",
            value: stats != null ? (stats.usage_calls_total ?? 0) : loading ? "…" : "—",
          },
        ]}
      />

      <div className="space-y-3">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>账号 ID</TableHead>
              <TableHead>邮箱</TableHead>
              <TableHead>昵称</TableHead>
              <TableHead>手机</TableHead>
              <TableHead>套餐</TableHead>
              <TableHead>余额</TableHead>
              <TableHead>冻结</TableHead>
              <TableHead>角色</TableHead>
              <TableHead>注册时间</TableHead>
              <TableHead className="w-[140px]">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(data?.items ?? []).map((u) => (
              <TableRow key={u.id}>
                <TableCell className="font-mono text-xs text-[#909399]">{formatAccountId(u.id)}</TableCell>
                <TableCell className="font-medium">{u.email}</TableCell>
                <TableCell>{u.nickname || "—"}</TableCell>
                <TableCell className="text-xs">{u.phone || "—"}</TableCell>
                <TableCell>
                  <Badge variant="info">{u.plan}</Badge>
                </TableCell>
                <TableCell className="tabular-nums">¥{fenToYuan(u.balance_fen)}</TableCell>
                <TableCell className="tabular-nums">¥{fenToYuan(u.frozen_fen)}</TableCell>
                <TableCell>
                  <Badge variant={u.role === "admin" ? "success" : "secondary"}>{u.role}</Badge>
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {u.created_at ? new Date(u.created_at).toLocaleString() : "—"}
                </TableCell>
                <TableCell>
                  <div className="flex gap-1">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        setDetailUser(u);
                        userDetail.open(u.id);
                      }}
                    >
                      查看
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => openEdit(u)}>
                      编辑
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
            {!loading && (data?.items.length ?? 0) === 0 && (
              <TableRow>
                <TableCell colSpan={10} className="p-0">
                  <EmptyState title="暂无用户" description="试试换个关键词搜索" />
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>

        {data && (
          <PaginationBar
            page={data.meta.page}
            pageSize={pageSize}
            total={data.meta.total}
            onPageChange={setPage}
            onPageSizeChange={(size) => {
              setPageSize(size);
              setPage(1);
            }}
          />
        )}
      </div>

      <UserDetailDrawer
        userId={userDetail.id}
        open={userDetail.isOpen}
        onOpenChange={(open) => {
          if (!open) userDetail.close();
        }}
        initialUser={detailUser}
      />

      <AdminModal
        open={!!editing}
        onOpenChange={(open) => !open && setEditing(null)}
        size="md"
        title="编辑用户"
        subtitle={editing?.email}
        footer={
          <Button className="w-full sm:w-auto" disabled={saving} onClick={() => void saveEdit()}>
            {saving ? "保存中…" : "保存修改"}
          </Button>
        }
      >
        <div className="admin-form-grid admin-form-grid--2">
          <AdminField label="套餐">
            <Select value={form.plan} onChange={(e) => setForm((f) => ({ ...f, plan: e.target.value }))}>
              <option value="free">free</option>
              <option value="pro">pro</option>
              <option value="team">team</option>
            </Select>
          </AdminField>
          <AdminField label="角色">
            <Select value={form.role} onChange={(e) => setForm((f) => ({ ...f, role: e.target.value }))}>
              <option value="user">user</option>
              <option value="admin">admin</option>
            </Select>
          </AdminField>
          <AdminField label="余额（元）">
            <Input
              value={form.balance_yuan}
              onChange={(e) => setForm((f) => ({ ...f, balance_yuan: e.target.value }))}
            />
          </AdminField>
          <AdminField label="调账备注" hint="可选">
            <Input
              value={form.balance_note}
              onChange={(e) => setForm((f) => ({ ...f, balance_note: e.target.value }))}
              placeholder="管理员备注"
            />
          </AdminField>
        </div>
      </AdminModal>
    </div>
  );
}
