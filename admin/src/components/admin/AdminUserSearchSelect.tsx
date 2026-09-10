import { useCallback, useEffect, useRef, useState } from "react";
import { api, type AdminUserRow, type PageMeta } from "@/api/client";
import { formatAccountId, parseAccountIdQuery } from "@/lib/admin-account";
import { cn } from "@/lib/utils";

type ListRes = { items: AdminUserRow[]; meta: PageMeta };

type AdminUserSearchSelectProps = {
  value: number | null;
  onChange: (userId: number | null, user?: AdminUserRow | null) => void;
  placeholder?: string;
  className?: string;
};

/** 远程搜索用户（账号 ID + 邮箱） */
export function AdminUserSearchSelect({
  value,
  onChange,
  placeholder = "搜索用户邮箱 / 账号 ID",
  className,
}: AdminUserSearchSelectProps) {
  const [query, setQuery] = useState("");
  const [options, setOptions] = useState<AdminUserRow[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [selectedLabel, setSelectedLabel] = useState("");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadSelected = useCallback(async (userId: number) => {
    try {
      const res = await api<ListRes>(
        `/api/admin/users?page=1&page_size=1&q=${encodeURIComponent(String(userId))}`,
      );
      const hit = res.items.find((u) => u.id === userId) ?? res.items[0];
      if (hit) {
        setSelectedLabel(`${hit.email} · ID：${formatAccountId(hit.id)}`);
      }
    } catch {
      setSelectedLabel(`ID：${formatAccountId(userId)}`);
    }
  }, []);

  useEffect(() => {
    if (value) void loadSelected(value);
    else setSelectedLabel("");
  }, [value, loadSelected]);

  const search = useCallback((raw: string) => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      const q = raw.trim();
      if (!q) {
        setOptions([]);
        return;
      }
      setLoading(true);
      try {
        const accountId = parseAccountIdQuery(q);
        const searchQ = accountId != null ? String(accountId) : q;
        const res = await api<ListRes>(
          `/api/admin/users?page=1&page_size=10&q=${encodeURIComponent(searchQ)}`,
        );
        setOptions(res.items);
      } catch {
        setOptions([]);
      } finally {
        setLoading(false);
      }
    }, 280);
  }, []);

  return (
    <div className={cn("admin-user-search", className)}>
      <input
        className="admin-input"
        placeholder={value ? selectedLabel || placeholder : placeholder}
        value={open ? query : value ? selectedLabel : query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
          search(e.target.value);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => {
          setTimeout(() => setOpen(false), 150);
        }}
      />
      {value ? (
        <button
          type="button"
          className="admin-user-search-clear"
          onClick={() => {
            onChange(null, null);
            setQuery("");
            setSelectedLabel("");
          }}
          aria-label="清除用户"
        >
          ×
        </button>
      ) : null}
      {open && (query.trim() || options.length > 0) ? (
        <div className="admin-user-search-dropdown">
          {loading ? <div className="admin-user-search-empty">搜索中…</div> : null}
          {!loading && options.length === 0 ? (
            <div className="admin-user-search-empty">无匹配用户</div>
          ) : null}
          {options.map((u) => (
            <button
              key={u.id}
              type="button"
              className="admin-user-search-option"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => {
                onChange(u.id, u);
                setSelectedLabel(`${u.email} · ID：${formatAccountId(u.id)}`);
                setQuery("");
                setOpen(false);
              }}
            >
              <span className="font-medium">{u.email}</span>
              <span className="text-xs text-[var(--admin-muted)]">
                ID：{formatAccountId(u.id)}
                {u.nickname ? ` · ${u.nickname}` : ""}
              </span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
