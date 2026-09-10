import { cn } from "@/lib/utils";
import { AdminField } from "@/components/admin/AdminField";

export type AdminSelectOption = {
  value: string;
  label: string;
};

type AdminSelectProps = {
  label?: string;
  hint?: string;
  value: string;
  options: AdminSelectOption[];
  placeholder?: string;
  className?: string;
  onChange: (value: string) => void;
};

// 管理端下拉选择（统一样式）
export function AdminSelect({
  label,
  hint,
  value,
  options,
  placeholder,
  className,
  onChange,
}: AdminSelectProps) {
  const control = (
    <div className={cn("admin-select-wrap", className)}>
      <select
        className="admin-select"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {placeholder ? <option value="">{placeholder}</option> : null}
        {options.map((opt) => (
          <option key={opt.value || "__empty"} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  );

  if (!label && !hint) return control;
  return (
    <AdminField label={label} hint={hint}>
      {control}
    </AdminField>
  );
}
