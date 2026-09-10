import { useEffect, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { api, type AdminDramaEpisode } from "@/api/client";
import {
  AdminDetailMeta,
  AdminDetailSection,
  AdminDetailTableWrap,
} from "@/components/admin/AdminDetailLayout";
import { AdminEntityLink } from "@/components/admin/AdminEntityLink";
import { Button } from "@/components/ui/button";
import { formatDramaGenerationStatus } from "@/lib/dramaLabels";

/** 漫剧分集详情：含分镜列表 */
export function DramaEpisodeDetailPage() {
  const { episodeId } = useParams<{ episodeId: string }>();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<AdminDramaEpisode | null>(null);
  const [loading, setLoading] = useState(true);
  const id = Number(episodeId);

  useEffect(() => {
    if (!id || Number.isNaN(id)) {
      navigate("/drama-episodes", { replace: true });
      return;
    }
    setLoading(true);
    void api<AdminDramaEpisode>(`/api/admin/drama-episodes/${id}`)
      .then(setDetail)
      .catch((err) => {
        toast.error(err instanceof Error ? err.message : "加载失败");
        navigate("/drama-episodes", { replace: true });
      })
      .finally(() => setLoading(false));
  }, [id, navigate]);

  if (loading && !detail) {
    return <div className="admin-detail-page-loading">加载中…</div>;
  }
  if (!detail) return null;

  return (
    <div className="admin-detail-page">
      <div className="admin-detail-page-toolbar">
        <Button variant="ghost" size="sm" className="admin-detail-back" asChild>
          <Link to="/drama-episodes">
            <ArrowLeft className="h-4 w-4" />
            返回分集列表
          </Link>
        </Button>
        <div className="admin-detail-page-heading">
          <h2 className="admin-detail-page-title">
            分集 #{detail.id} · {detail.name}
          </h2>
          <p className="admin-detail-page-sub">
            <AdminEntityLink kind="drama" id={detail.project_id} label={detail.project_title ?? undefined} />
          </p>
        </div>
        <div className="admin-detail-page-actions">
          <Button size="sm" variant="outline" asChild>
            <Link to={`/drama-projects/${detail.project_id}?tab=episodes`}>打开项目</Link>
          </Button>
          <Button size="sm" variant="outline" asChild>
            <Link to={`/drama-fragments?episode_id=${detail.id}`}>全部分镜</Link>
          </Button>
        </div>
      </div>

      <AdminDetailSection title="基本信息">
        <AdminDetailMeta
          items={[
            {
              label: "用户",
              value: detail.user_id ? (
                <AdminEntityLink kind="user" id={detail.user_id} label={detail.user_email ?? undefined} />
              ) : (
                "—"
              ),
            },
            {
              label: "所属项目",
              value: <AdminEntityLink kind="drama" id={detail.project_id} label={detail.project_title ?? undefined} />,
            },
            { label: "分镜数", value: detail.fragment_count },
            { label: "分镜计划", value: detail.fragment_plan_status || "—" },
            {
              label: "更新时间",
              value: detail.updated_at ? new Date(detail.updated_at).toLocaleString() : "—",
            },
          ]}
        />
      </AdminDetailSection>

      <AdminDetailSection title={`分镜列表（${(detail.fragments ?? []).length}）`}>
        <AdminDetailTableWrap>
          <table>
            <thead>
              <tr>
                <th>序号</th>
                <th>ID</th>
                <th>内容</th>
                <th>时长</th>
                <th>生成</th>
                <th>资产引用</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {(detail.fragments ?? []).length === 0 ? (
                <tr>
                  <td colSpan={7} className="!text-center text-[var(--admin-muted)]">
                    暂无分镜
                  </td>
                </tr>
              ) : (
                (detail.fragments ?? []).map((f) => (
                  <tr key={f.id}>
                    <td>{f.sort_order}</td>
                    <td>{f.id}</td>
                    <td className="max-w-[240px] truncate">{f.content || "—"}</td>
                    <td>{f.duration_sec != null ? `${f.duration_sec}s` : "—"}</td>
                    <td className="text-xs text-[var(--admin-muted)]">
                      {formatDramaGenerationStatus(f.generation_status)}
                    </td>
                    <td>{f.asset_ref_count}</td>
                    <td>
                      <Button size="sm" variant="outline" asChild>
                        <Link to={`/drama-fragments/${f.id}`}>查看</Link>
                      </Button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </AdminDetailTableWrap>
      </AdminDetailSection>
    </div>
  );
}
