/** Project pipeline status → Chinese label */
export const PROJECT_STATUS_LABELS: Record<string, string> = {
  DRAFT: "草稿",
  SCRIPTING: "脚本生成中",
  SCRIPT_READY: "脚本就绪",
  IMAGING: "分镜图生成中",
  IMAGE_READY: "分镜图就绪",
  VIDEOING: "视频生成中",
  VIDEO_READY: "视频就绪",
  AUDIOING: "配音中",
  COMPOSING: "合成中",
  AUDITING: "审核中",
  DONE: "已完成",
  REJECTED: "已拒绝",
  FAILED: "失败",
  CANCELLED: "已取消",
};

/** Order payment status → Chinese */
export const ORDER_STATUS_LABELS: Record<string, string> = {
  pending: "待支付",
  paid: "已支付",
  closed: "已关闭",
};

/** Work audit / visibility → Chinese */
export const AUDIT_STATUS_LABELS: Record<string, string> = {
  pending: "待审核",
  passed: "已通过",
  rejected: "已拒绝",
};

export const VISIBILITY_LABELS: Record<string, string> = {
  public: "公开",
  private: "私密",
  unlisted: "不公开列出",
};

/** Wallet ledger kind → Chinese */
export const LEDGER_KIND_LABELS: Record<string, string> = {
  topup: "充值",
  grant: "赠送",
  adjust: "调账",
  freeze: "冻结",
  unfreeze: "解冻",
  settle: "结算",
  refund: "退款",
};

/** Payment channel → Chinese */
export const PAY_TYPE_LABELS: Record<string, string> = {
  alipay: "支付宝",
  wxpay: "微信",
};

/** Unified task platform status → Chinese */
export const TASK_STATUS_LABELS: Record<string, string> = {
  pending: "排队中",
  leased: "已租约",
  running: "执行中",
  awaiting_poll: "等待轮询",
  awaiting_review: "待审核",
  cancel_requested: "取消中",
  succeeded: "已成功",
  failed: "失败",
  cancelled: "已取消",
};

/** Task domain → Chinese */
export const TASK_DOMAIN_LABELS: Record<string, string> = {
  drama: "漫剧",
  kepu: "AI短视频",
  tools: "工具",
  studio: "工作室",
  api: "开放 API",
};

/** Task type → Chinese（轻量同步 + 平台任务） */
export const TASK_TYPE_LABELS: Record<string, string> = {
  agent_chat: "漫剧助手聊天",
  skill_optimize: "Skill 优化提示词",
  voice_prompt: "角色音色描述",
  content_expand: "选题扩写",
  script_summary: "剧本摘要",
  episode_script: "分集剧本",
  fragment_plan: "AI 分镜",
  fragment_video: "分镜视频",
  seed_assets: "资产抽取",
  asset_image: "资产生图",
  asset_video: "资产视频",
  voice_synthesis: "配音合成",
  project_pipeline: "科普流水线",
  shot_regen_image: "单镜重绘",
  shot_regen_video: "单镜视频",
  shot_regen_audio: "单镜配音",
  project_regen_audio: "全片配音",
  project_compose_only: "仅合成",
  v1_image: "API 生图",
  v1_video: "API 生视频",
  v1_seedance: "API Seedance",
  tool_image: "工具生图",
  tool_video: "工具生视频",
};

// Resolve project status display text
export function projectStatusLabel(status: string): string {
  return PROJECT_STATUS_LABELS[status] ?? status;
}

// Resolve order status display text
export function orderStatusLabel(status: string): string {
  return ORDER_STATUS_LABELS[status] ?? status;
}

// Resolve audit status display text
export function auditStatusLabel(status: string): string {
  return AUDIT_STATUS_LABELS[status] ?? status;
}

// Resolve visibility display text
export function visibilityLabel(status: string): string {
  return VISIBILITY_LABELS[status] ?? status;
}

// Resolve ledger kind display text
export function ledgerKindLabel(kind: string): string {
  return LEDGER_KIND_LABELS[kind] ?? kind;
}

// Resolve pay type display text
export function payTypeLabel(payType: string): string {
  return PAY_TYPE_LABELS[payType] ?? payType;
}

// Resolve task status display text
export function taskStatusLabel(status: string): string {
  return TASK_STATUS_LABELS[status] ?? status;
}

// Resolve task domain display text
export function taskDomainLabel(domain: string): string {
  return TASK_DOMAIN_LABELS[domain] ?? domain;
}

// Resolve task type display text
export function taskTypeLabel(taskType: string): string {
  return TASK_TYPE_LABELS[taskType] ?? taskType;
}

/** Filter options for project status select (value stays English for API) */
export const PROJECT_STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "全部状态" },
  ...Object.entries(PROJECT_STATUS_LABELS).map(([value, label]) => ({ value, label })),
];
