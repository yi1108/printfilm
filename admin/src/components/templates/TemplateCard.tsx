import { Crown, ImageOff, Pencil, Trash2 } from "lucide-react";
import type { AdminTemplate } from "@/api/client";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";

type TemplateCardProps = {
  template: AdminTemplate;
  onEdit: (tpl: AdminTemplate) => void;
  onDelete: (id: string) => void;
  onToggleActive: (id: string, value: boolean) => void;
  onTogglePremium: (id: string, value: boolean) => void;
};

// 解析封面 URL（相对 /static 走 Vite 代理）
function coverSrc(url: string): string {
  const trimmed = (url || "").trim();
  if (!trimmed) return "";
  if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) return trimmed;
  return trimmed.startsWith("/") ? trimmed : `/${trimmed}`;
}

// 模板卡片：封面 + 元信息 + 快捷开关
export function TemplateCard({
  template,
  onEdit,
  onDelete,
  onToggleActive,
  onTogglePremium,
}: TemplateCardProps) {
  const src = coverSrc(template.preview_cover);
  const categories = template.category?.length ? template.category : ["未分类"];

  return (
    <article
      className={cn(
        "template-card group",
        !template.is_active && "template-card--inactive",
      )}
    >
      <button
        type="button"
        className="template-card-cover"
        onClick={() => onEdit(template)}
        aria-label={`编辑模板 ${template.name}`}
      >
        {src ? (
          <img src={src} alt={template.name} loading="lazy" className="template-card-cover-img" />
        ) : (
          <div className="template-card-cover-fallback">
            <ImageOff className="h-8 w-8 text-white/70" />
          </div>
        )}
        <div className="template-card-cover-gradient" />
        <div className="template-card-cover-meta">
          <span className="template-card-sort">#{template.sort_order}</span>
          {template.is_premium ? (
            <span className="template-card-badge template-card-badge--premium">
              <Crown className="h-3 w-3" />
              Premium
            </span>
          ) : null}
          {!template.is_active ? (
            <span className="template-card-badge template-card-badge--off">已下架</span>
          ) : null}
        </div>
      </button>

      <div className="template-card-body">
        <div className="template-card-head">
          <div className="min-w-0 flex-1">
            <h3 className="template-card-title">{template.name}</h3>
            <p className="template-card-id">{template.id}</p>
          </div>
          <div className="template-card-actions">
            <button type="button" className="template-card-icon-btn" onClick={() => onEdit(template)} title="编辑">
              <Pencil className="h-4 w-4" />
            </button>
            <button
              type="button"
              className="template-card-icon-btn template-card-icon-btn--danger"
              onClick={() => onDelete(template.id)}
              title="删除"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </div>
        </div>

        {template.description ? (
          <p className="template-card-desc">{template.description}</p>
        ) : (
          <p className="template-card-desc template-card-desc--empty">暂无描述</p>
        )}

        <div className="template-card-tags">
          {categories.slice(0, 3).map((tag) => (
            <span key={tag} className="template-card-tag">
              {tag}
            </span>
          ))}
          <span className="template-card-tag template-card-tag--muted">{template.default_ratio}</span>
        </div>

        <div className="template-card-foot">
          <label className="template-card-toggle">
            <span>上架</span>
            <Switch
              checked={template.is_active}
              onCheckedChange={(v) => onToggleActive(template.id, v)}
            />
          </label>
          <label className="template-card-toggle">
            <span>Premium</span>
            <Switch
              checked={template.is_premium}
              onCheckedChange={(v) => onTogglePremium(template.id, v)}
            />
          </label>
        </div>
      </div>
    </article>
  );
}
