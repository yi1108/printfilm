import {
  Clapperboard,
  Film,
  Image,
  MessageSquareText,
  Mic,
  Palette,
  Video,
  Webhook,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import type { AdminUsageBucket } from "@/api/client";
import type { DashboardMetric } from "@/pages/dashboard/DashboardFilters";
import type { DashboardInsightItem, DashboardInsightTone } from "@/pages/dashboard/DashboardInsightGrid";
import { formatDashboardMetric, readBucketMetric } from "@/pages/dashboard/dashboardMetrics";

const CAPABILITY_META: Record<string, { label: string; icon: LucideIcon; tone: DashboardInsightTone }> = {
  llm: { label: "LLM 文本", icon: MessageSquareText, tone: "purple" },
  image: { label: "生图", icon: Image, tone: "blue" },
  video: { label: "视频", icon: Video, tone: "teal" },
  tts: { label: "配音", icon: Mic, tone: "sand" },
  unknown: { label: "其他", icon: Wrench, tone: "slate" },
};

const DOMAIN_META: Record<string, { label: string; icon: LucideIcon; tone: DashboardInsightTone }> = {
  drama: { label: "漫剧", icon: Film, tone: "teal" },
  kepu: { label: "AI短视频", icon: Clapperboard, tone: "blue" },
  api: { label: "开放 API", icon: Webhook, tone: "purple" },
  tools: { label: "工具", icon: Wrench, tone: "sand" },
  studio: { label: "工作室", icon: Palette, tone: "mint" },
  unknown: { label: "其他", icon: Wrench, tone: "slate" },
};

function buildInsightItems(
  rows: AdminUsageBucket[],
  metric: DashboardMetric,
  metaMap: Record<string, { label: string; icon: LucideIcon; tone: DashboardInsightTone }>,
  labelForKey?: (key: string) => string,
): DashboardInsightItem[] {
  const prepared = [...rows]
    .map((row) => ({
      row,
      value: readBucketMetric(row, metric),
    }))
    .filter((item) => item.value > 0);
  const total = prepared.reduce((sum, item) => sum + item.value, 0);

  return prepared
    .sort((a, b) => b.value - a.value)
    .map(({ row, value }) => {
      const meta = metaMap[row.key] ?? metaMap.unknown;
      const sharePct = total > 0 ? ((value / total) * 100).toFixed(1) : null;
      const shareHint = sharePct ? `占比 ${sharePct}%` : undefined;
      return {
        key: row.key,
        label: labelForKey?.(row.key) ?? meta.label,
        value: formatDashboardMetric(value, metric),
        hint: [shareHint, `${row.calls.toLocaleString()} 次调用`].filter(Boolean).join(" · "),
        icon: meta.icon,
        tone: meta.tone,
      };
    });
}

/** 能力分布洞察卡片 */
export function buildCapabilityInsights(
  rows: AdminUsageBucket[],
  metric: DashboardMetric,
): DashboardInsightItem[] {
  return buildInsightItems(rows, metric, CAPABILITY_META);
}

/** 领域分布洞察卡片 */
export function buildDomainInsights(
  rows: AdminUsageBucket[],
  metric: DashboardMetric,
  labelForKey: (key: string) => string,
): DashboardInsightItem[] {
  return buildInsightItems(rows, metric, DOMAIN_META, labelForKey);
}
