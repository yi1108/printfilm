import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";

/** 通过 URL query 打开/关闭详情弹层（可刷新恢复） */
export function useAdminDetailQuery(paramKey: string) {
  const [searchParams, setSearchParams] = useSearchParams();

  const id = useMemo(() => {
    const raw = searchParams.get(paramKey);
    if (!raw) return null;
    const n = Number(raw);
    return Number.isFinite(n) && n > 0 ? n : null;
  }, [paramKey, searchParams]);

  const open = useCallback(
    (nextId: number) => {
      setSearchParams(
        (prev) => {
          const p = new URLSearchParams(prev);
          p.set(paramKey, String(nextId));
          return p;
        },
        { replace: false },
      );
    },
    [paramKey, setSearchParams],
  );

  const close = useCallback(() => {
    setSearchParams(
      (prev) => {
        const p = new URLSearchParams(prev);
        p.delete(paramKey);
        return p;
      },
      { replace: true },
    );
  }, [paramKey, setSearchParams]);

  return { id, open, close, isOpen: id != null };
}
