/** 漫剧资产生成状态（与 params.generation.status 一致） */
export const DRAMA_GENERATION_STATUSES = [
  "queued",
  "running",
  "generating",
  "done",
  "failed",
  "cancelled",
] as const;

/** 漫剧生成状态中文标签（idle 仅用于分镜等无 params.generation 时的展示回退） */
export function dramaGenerationStatusLabel(status: string): string {
  const map: Record<string, string> = {
    queued: "排队中",
    running: "生成中",
    generating: "生成中",
    done: "已完成",
    failed: "失败",
    cancelled: "已取消",
    idle: "未开始",
  };
  return map[status] ?? status;
}

/** 列表/详情展示：空值显示 — */
export function formatDramaGenerationStatus(status: string | null | undefined): string {
  if (!status) return "—";
  return dramaGenerationStatusLabel(status);
}

/** 漫剧资产类型中文标签 */
export function dramaAssetTypeLabel(type: string): string {
  const map: Record<string, string> = {
    character: "角色",
    scene: "场景",
    prop: "道具",
    material: "素材",
    narration: "旁白",
    video: "视频",
    audio: "音频",
    text: "文本",
    none: "未分类",
  };
  return map[type] ?? type;
}
