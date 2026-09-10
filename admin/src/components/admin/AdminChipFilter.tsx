import { cn } from "@/lib/utils";

export type AdminChipOption = {
  value: string;
  label: string;
  count?: number;
};

type AdminChipFilterProps = {
  label?: string;
  value: string;
  options: AdminChipOption[];
  onChange: (value: string) => void;
  className?: string;
};

// 管理端分类 Chip 筛选
export function AdminChipFilter({ label, value, options, onChange, className }: AdminChipFilterProps) {
  const segment = className?.includes("admin-chip-filter--segment");
  return (
    <div className={cn("admin-chip-filter", className)}>
      {label ? <span className="admin-chip-filter-label">{label}</span> : null}
      <div className={cn("admin-chip-filter-list", segment && "is-segment")} role="tablist">
        {options.map((opt) => {
          const active = value === opt.value;
          return (
            <button
              key={opt.value || "__all"}
              type="button"
              role="tab"
              aria-selected={active}
              className={cn(segment ? "admin-segment-btn" : "admin-chip", active && "is-active")}
              onClick={() => onChange(opt.value)}
            >
              {opt.label}
              {typeof opt.count === "number" ? (
                <span className="admin-chip-count">{opt.count}</span>
              ) : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}
