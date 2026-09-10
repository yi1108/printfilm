import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { api, type AdminDramaFragment, type PageMeta } from "@/api/client";
import { AdminEntityLink } from "@/components/admin/AdminEntityLink";
import { AdminFilterBar } from "@/components/admin/AdminFilterBar";
import { AdminUserSearchSelect } from "@/components/admin/AdminUserSearchSelect";
import { PaginationBar } from "@/components/PaginationBar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page";
import { DRAMA_GENERATION_STATUSES, formatDramaGenerationStatus } from "@/lib/dramaLabels";
import { DEFAULT_PAGE_SIZE } from "@/lib/pagination";

type ListRes = { items: AdminDramaFragment[]; meta: PageMeta };

/** 全站漫剧分镜列表 */
export function DramaFragmentsPage() {
  const [searchParams] = useSearchParams();
  const initialProjectId = searchParams.get("project_id");
  const initialEpisodeId = searchParams.get("episode_id");

  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [userId, setUserId] = useState<number | null>(null);
  const [projectId, setProjectId] = useState(initialProjectId ?? "");
  const [episodeId, setEpisodeId] = useState(initialEpisodeId ?? "");
  const [generationStatus, setGenerationStatus] = useState("");
  const [data, setData] = useState<ListRes | null>(null);

  async function load(nextPage = page) {
    try {
      const params = new URLSearchParams({ page: String(nextPage), page_size: String(DEFAULT_PAGE_SIZE) });
      if (q.trim()) params.set("q", q.trim());
      if (userId) params.set("user_id", String(userId));
      if (projectId.trim()) params.set("project_id", projectId.trim());
      if (episodeId.trim()) params.set("episode_id", episodeId.trim());
      if (generationStatus.trim()) params.set("generation_status", generationStatus.trim());
      setData(await api<ListRes>(`/api/admin/drama-fragments?${params}`));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "加载失败");
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page]);

  return (
    <div className="admin-list-page">
      <PageHeader description="全站漫剧分镜：按项目、分集筛选，查看生成状态与资产引用" />
      <AdminFilterBar>
        <Input placeholder="内容 / 集名 / 项目" value={q} onChange={(e) => setQ(e.target.value)} />
        <AdminUserSearchSelect value={userId} onChange={setUserId} />
        <Input placeholder="项目 ID" value={projectId} onChange={(e) => setProjectId(e.target.value)} />
        <Input placeholder="分集 ID" value={episodeId} onChange={(e) => setEpisodeId(e.target.value)} />
        <select
          className="admin-native-select"
          value={generationStatus}
          onChange={(e) => setGenerationStatus(e.target.value)}
        >
          <option value="">全部生成状态</option>
          {DRAMA_GENERATION_STATUSES.map((s) => (
            <option key={s} value={s}>
              {formatDramaGenerationStatus(s)}
            </option>
          ))}
        </select>
        <Button
          size="sm"
          variant="secondary"
          className="admin-filter-action"
          onClick={() => {
            setPage(1);
            void load(1);
          }}
        >
          筛选
        </Button>
      </AdminFilterBar>

      <div className="admin-table-wrap">
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>序号</th>
              <th>内容</th>
              <th>分集</th>
              <th>项目</th>
              <th>时长</th>
              <th>生成</th>
              <th>资产</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {(data?.items ?? []).map((row) => (
              <tr key={row.id}>
                <td>{row.id}</td>
                <td>{row.sort_order}</td>
                <td className="max-w-[200px] truncate">{row.content || "—"}</td>
                <td className="max-w-[100px] truncate">{row.episode_name || row.episode_id}</td>
                <td>
                  <AdminEntityLink kind="drama" id={row.project_id} label={row.project_title ?? undefined} />
                </td>
                <td>{row.duration_sec != null ? `${row.duration_sec}s` : "—"}</td>
                <td className="text-xs text-[var(--admin-muted)]">
                  {formatDramaGenerationStatus(row.generation_status)}
                </td>
                <td>{row.asset_ref_count}</td>
                <td>
                  <Button size="sm" variant="outline" asChild>
                    <Link to={`/drama-fragments/${row.id}`}>查看</Link>
                  </Button>
                </td>
              </tr>
            ))}
            {(data?.items.length ?? 0) === 0 ? (
              <tr>
                <td colSpan={9} className="!text-center text-[var(--admin-muted)]">
                  暂无分镜
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      {data?.meta ? (
        <PaginationBar
          page={data.meta.page}
          pageSize={data.meta.page_size}
          total={data.meta.total}
          onPageChange={setPage}
        />
      ) : null}
    </div>
  );
}
