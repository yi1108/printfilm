import { useEffect, useMemo, useState } from "react";
import { LayoutGrid, Loader2, Plus } from "lucide-react";
import { toast } from "sonner";
import { api, type AdminTemplate, type PageMeta } from "@/api/client";
import { AdminChipFilter } from "@/components/admin/AdminChipFilter";
import { AdminConfirmDialog } from "@/components/admin/AdminConfirmDialog";
import { AdminFilterBar } from "@/components/admin/AdminFilterBar";
import { AdminSearchInput } from "@/components/admin/AdminSearchInput";
import { AdminSelect } from "@/components/admin/AdminSelect";
import { TemplateCard } from "@/components/templates/TemplateCard";
import {
  TemplateEditorDialog,
  type TemplateFormState,
} from "@/components/templates/TemplateEditorDialog";
import { PaginationBar } from "@/components/PaginationBar";
import { TEMPLATE_PAGE_SIZE } from "@/lib/pagination";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page";

type ListRes = { items: AdminTemplate[]; meta: PageMeta };
type MetaRes = { categories: string[] };

const STATUS_OPTIONS = [
  { value: "", label: "全部状态" },
  { value: "active", label: "已上架" },
  { value: "inactive", label: "已下架" },
  { value: "premium", label: "Premium" },
];

const emptyForm = (): TemplateFormState => ({
  id: "",
  name: "",
  description: "",
  category: "",
  preview_cover: "",
  style_prefix: "",
  character_prompt: "",
  extra_prompt: "",
  negative_prompt: "",
  default_ratio: "16:9",
  shot_duration_min: 3,
  shot_duration_max: 8,
  llm_system_addon: "",
  sort_order: 0,
  is_active: true,
  is_premium: false,
});

// 从 seedream_config 读取角色/额外提示词
function seedreamText(cfg: Record<string, unknown> | undefined, key: string): string {
  const value = cfg?.[key];
  return typeof value === "string" ? value : "";
}

// 模板管理：封面卡片网格 + 分类筛选 + 全局 UI 组件
export function TemplatesPage() {
  const [page, setPage] = useState(1);
  const [data, setData] = useState<ListRes | null>(null);
  const [categories, setCategories] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<AdminTemplate | null>(null);
  const [form, setForm] = useState<TemplateFormState>(emptyForm());
  const [saving, setSaving] = useState(false);
  const [q, setQ] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  // 加载模板分页列表（服务端筛选）
  async function load(nextPage = page) {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        page: String(nextPage),
        page_size: String(TEMPLATE_PAGE_SIZE),
      });
      if (q.trim()) params.set("q", q.trim());
      if (categoryFilter) params.set("category", categoryFilter);
      if (statusFilter === "active") params.set("is_active", "true");
      if (statusFilter === "inactive") params.set("is_active", "false");
      setData(await api<ListRes>(`/api/admin/templates?${params}`));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }

  // 加载全库分类标签
  async function loadMeta() {
    try {
      const meta = await api<MetaRes>("/api/admin/templates/meta");
      setCategories(meta.categories ?? []);
    } catch {
      /* 分类元数据失败不阻塞列表 */
    }
  }

  useEffect(() => {
    void loadMeta();
  }, []);

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page]);

  const categoryOptions = useMemo(() => {
    const items = data?.items ?? [];
    const countFor = (cat: string) =>
      items.filter((t) => (t.category || []).includes(cat)).length;
    return [
      { value: "", label: "全部分类", count: items.length },
      ...categories.map((cat) => ({
        value: cat,
        label: cat,
        count: countFor(cat),
      })),
    ];
  }, [categories, data?.items]);

  const filteredItems = useMemo(() => {
    const items = data?.items ?? [];
    if (statusFilter !== "premium") return items;
    return items.filter((t) => t.is_premium);
  }, [data?.items, statusFilter]);

  // 打开新建弹窗
  function openCreate() {
    setEditing(null);
    setForm(emptyForm());
    setOpen(true);
  }

  // 打开编辑弹窗（拉取最新配置）
  async function openEdit(tpl: AdminTemplate) {
    try {
      const fresh = await api<AdminTemplate>(`/api/admin/templates/${tpl.id}`);
      setEditing(fresh);
      setForm({
        id: fresh.id,
        name: fresh.name,
        description: fresh.description,
        category: (fresh.category || []).join(","),
        preview_cover: fresh.preview_cover,
        style_prefix: fresh.style_prefix,
        character_prompt: seedreamText(fresh.seedream_config, "character_prompt"),
        extra_prompt: seedreamText(fresh.seedream_config, "extra_prompt"),
        negative_prompt: fresh.negative_prompt,
        default_ratio: fresh.default_ratio,
        shot_duration_min: fresh.shot_duration_min,
        shot_duration_max: fresh.shot_duration_max,
        llm_system_addon: fresh.llm_system_addon,
        sort_order: fresh.sort_order,
        is_active: fresh.is_active,
        is_premium: fresh.is_premium,
      });
      setOpen(true);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "加载模板详情失败");
    }
  }

  // 创建或更新模板
  async function save() {
    setSaving(true);
    try {
      const category = form.category
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      if (editing) {
        await api(`/api/admin/templates/${editing.id}`, {
          method: "PATCH",
          body: JSON.stringify({
            name: form.name,
            description: form.description,
            category,
            preview_cover: form.preview_cover,
            style_prefix: form.style_prefix,
            negative_prompt: form.negative_prompt,
            default_ratio: form.default_ratio,
            shot_duration_min: form.shot_duration_min,
            shot_duration_max: form.shot_duration_max,
            llm_system_addon: form.llm_system_addon,
            sort_order: form.sort_order,
            is_active: form.is_active,
            is_premium: form.is_premium,
            seedream_config: {
              ...(editing.seedream_config || {}),
              character_prompt: form.character_prompt,
              extra_prompt: form.extra_prompt,
            },
          }),
        });
      } else {
        if (!form.id.trim()) throw new Error("请填写模板 ID");
        await api(`/api/admin/templates`, {
          method: "POST",
          body: JSON.stringify({
            id: form.id.trim(),
            name: form.name,
            description: form.description,
            category,
            preview_cover: form.preview_cover,
            style_prefix: form.style_prefix,
            negative_prompt: form.negative_prompt,
            default_ratio: form.default_ratio,
            shot_duration_min: form.shot_duration_min,
            shot_duration_max: form.shot_duration_max,
            llm_system_addon: form.llm_system_addon,
            sort_order: form.sort_order,
            is_active: form.is_active,
            is_premium: form.is_premium,
            seedream_config: {
              character_prompt: form.character_prompt,
              extra_prompt: form.extra_prompt,
            },
            seedance_config: {},
            audio_config: {},
            subtitle_config: {},
          }),
        });
      }
      toast.success("已保存");
      setOpen(false);
      await Promise.all([load(), loadMeta()]);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  // 快捷切换上架 / Premium
  async function quickPatch(id: string, body: Partial<AdminTemplate>) {
    try {
      await api(`/api/admin/templates/${id}`, { method: "PATCH", body: JSON.stringify(body) });
      await load();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "更新失败");
    }
  }

  // 确认删除模板
  async function confirmDelete() {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await api(`/api/admin/templates/${deleteTarget}`, { method: "DELETE" });
      toast.success("已删除");
      setDeleteTarget(null);
      await Promise.all([load(), loadMeta()]);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "删除失败");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="admin-list-page">
      <PageHeader
        description="风格 / 角色 / 提示词以本页为准；已创建项目需在分镜页恢复模板后才会跟随。"
        actions={
          <Button onClick={openCreate} className="gap-2">
            <Plus className="h-4 w-4" />
            新建模板
          </Button>
        }
      />

      <AdminFilterBar
        trailing={
          <>
            <LayoutGrid className="h-4 w-4" />
            {filteredItems.length} / {data?.meta.total ?? 0} 项
          </>
        }
      >
        <AdminSearchInput
          className="min-w-[220px] flex-1 max-w-md"
          placeholder="搜索名称 / ID / 描述 / 分类"
          value={q}
          onChange={setQ}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              setPage(1);
              void load(1);
            }
          }}
        />
        <AdminSelect
          className="w-36"
          value={statusFilter}
          options={STATUS_OPTIONS}
          onChange={(v) => {
            setStatusFilter(v);
            setPage(1);
          }}
        />
        <AdminChipFilter
          label="分类"
          value={categoryFilter}
          options={categoryOptions}
          onChange={(v) => {
            setCategoryFilter(v);
            setPage(1);
          }}
        />
        <Button
          variant="secondary"
          size="sm"
          onClick={() => {
            setPage(1);
            void load(1);
          }}
        >
          筛选
        </Button>
      </AdminFilterBar>

      {loading ? (
        <div className="template-grid-loading">
          <Loader2 className="h-6 w-6 animate-spin text-[#67c23a]" />
          <span>加载模板…</span>
        </div>
      ) : filteredItems.length === 0 ? (
        <div className="template-grid-empty">
          <p>暂无匹配的模板</p>
          <Button variant="outline" size="sm" onClick={openCreate}>
            新建第一个模板
          </Button>
        </div>
      ) : (
        <div className="template-grid">
          {filteredItems.map((t) => (
            <TemplateCard
              key={t.id}
              template={t}
              onEdit={(tpl) => void openEdit(tpl)}
              onDelete={(id) => setDeleteTarget(id)}
              onToggleActive={(id, v) => void quickPatch(id, { is_active: v })}
              onTogglePremium={(id, v) => void quickPatch(id, { is_premium: v })}
            />
          ))}
        </div>
      )}

      {data && data.meta.total > TEMPLATE_PAGE_SIZE && (
        <PaginationBar
          page={data.meta.page}
          pageSize={data.meta.page_size}
          total={data.meta.total}
          onPageChange={setPage}
        />
      )}

      <TemplateEditorDialog
        open={open}
        saving={saving}
        editing={editing}
        form={form}
        categorySuggestions={categories}
        onOpenChange={setOpen}
        onChange={(patch) => setForm((prev) => ({ ...prev, ...patch }))}
        onSave={() => void save()}
      />

      <AdminConfirmDialog
        open={Boolean(deleteTarget)}
        title="删除模板"
        description={deleteTarget ? `确认删除模板「${deleteTarget}」？已被项目引用的模板无法删除。` : undefined}
        confirmLabel="删除"
        loading={deleting}
        destructive
        onOpenChange={(next) => {
          if (!next) setDeleteTarget(null);
        }}
        onConfirm={() => void confirmDelete()}
      />
    </div>
  );
}
