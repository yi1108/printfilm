export type ModelCapability = "text" | "image" | "video" | "audio";

export type PresetModelOption = { id: string; label: string };

/** 与后端 media_model_presets.PRESET_MODELS 对齐（TokenFree 点分 id） */
export const PRESET_MODELS: Record<ModelCapability, PresetModelOption[]> = {
  text: [
    { id: "gpt-6.1-sol", label: "GPT-6.1 Sol" },
    { id: "deepseek-v4-pro", label: "DeepSeek V4 Pro" },
    { id: "gpt-6-astra", label: "GPT-6 Astra" },
  ],
  image: [
    { id: "seedream-5.0-pro", label: "Seedream 5.0 Pro" },
    { id: "seedream-5.0", label: "Seedream 5.0" },
    { id: "seedream-5.0-flash", label: "Seedream 5.0 Flash" },
    { id: "gpt-image-2", label: "GPT Image 2" },
    { id: "gpt-image-2.5", label: "GPT Image 2.5" },
  ],
  video: [
    { id: "seedance-2.5", label: "Seedance 2.5" },
    { id: "seedance-2.0", label: "Seedance 2.0" },
    { id: "seedance-2.0-fast", label: "Seedance 2.0 Fast" },
    // mini：TokenFree→Ark 未开通，暂不下发
    { id: "MiniMax-H3", label: "MiniMax H3" },
  ],
  audio: [{ id: "qwen-tts-2025-05-22", label: "Qwen TTS" }],
};

export const CAPABILITY_ORDER: ModelCapability[] = ["text", "image", "video", "audio"];

export const CAPABILITY_LABELS: Record<ModelCapability, string> = {
  text: "文本",
  image: "图像",
  video: "视频",
  audio: "配音",
};

/** 写入 TokenFree 渠道的全部预设 id */
export function allPresetChannelModels(): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const cap of CAPABILITY_ORDER) {
    for (const row of PRESET_MODELS[cap]) {
      const id = (row.id || "").trim();
      if (!id || seen.has(id.toLowerCase())) continue;
      seen.add(id.toLowerCase());
      out.push(id);
    }
  }
  return out;
}

/** 历史友好别名 → 预设规范 id（与后端 PRESET_MODEL_ALIASES 对齐） */
const PRESET_MODEL_ALIASES: Record<string, string> = {
  "seedance-2-5": "seedance-2.5",
  "seedance2.5": "seedance-2.5",
  "seedance-2": "seedance-2.0",
  seedance2: "seedance-2.0",
  "seedance-2-0": "seedance-2.0",
  "seedance2.0": "seedance-2.0",
  "seedance-2-0-mini": "seedance-2.0",
  "seedance-2.0-mini": "seedance-2.0",
  "doubao-seedance-2-0-mini-260615": "seedance-2.0",
  "seedance-2-0-fast": "seedance-2.0-fast",
  "seedream-5-0-pro": "seedream-5.0-pro",
  "seedream-5-0": "seedream-5.0",
  "seedream-5": "seedream-5.0",
  "seedream5.0": "seedream-5.0",
  seedream5: "seedream-5.0",
  "seedream-5-0-flash": "seedream-5.0-flash",
  "gpt-image-2-5": "gpt-image-2.5",
  "gpt-image-2.5": "gpt-image-2.5",
  "gpt-image-2.5-sunburst": "gpt-image-2.5",
  "gpt-image-2-5-sunburst": "gpt-image-2.5",
  "gpt-image-2.5-flare": "gpt-image-2.5",
  "gpt-image-2-5-flare": "gpt-image-2.5",
  "gemini-3.1-flash-tts": "qwen-tts-2025-05-22",
};

function resolvePresetAlias(modelId: string): string {
  const key = modelId.trim().toLowerCase().replace(/\s+/g, "");
  for (const [alias, canonical] of Object.entries(PRESET_MODEL_ALIASES)) {
    if (alias.toLowerCase().replace(/\s+/g, "") === key) return canonical;
  }
  return modelId.trim();
}

/** 非法或不空缺省时落到该能力第一项 */
export function clampDefaultToPreset(cap: ModelCapability, modelId: string | null | undefined): string {
  const raw = resolvePresetAlias(modelId || "");
  const opts = PRESET_MODELS[cap];
  const hit = opts.find((row) => row.id.toLowerCase() === raw.toLowerCase());
  if (hit) return hit.id;
  return opts[0]?.id || "";
}

/** 加载时检测「历史默认值被钳到预设」以便提示管理员确认 */
export function detectDefaultRemaps(
  raw: Partial<Record<`${ModelCapability}_model`, string>> | null | undefined,
): Array<{ capability: ModelCapability; from: string; to: string }> {
  const out: Array<{ capability: ModelCapability; from: string; to: string }> = [];
  for (const cap of CAPABILITY_ORDER) {
    const key = `${cap}_model` as `${ModelCapability}_model`;
    const original = String(raw?.[key] || "").trim();
    if (!original) continue;
    const clamped = clampDefaultToPreset(cap, original);
    if (original.toLowerCase() === clamped.toLowerCase()) continue;
    if (resolvePresetAlias(original).toLowerCase() === clamped.toLowerCase()) continue;
    out.push({ capability: cap, from: original, to: clamped });
  }
  return out;
}

/** 默认站点默认值（四类各取第一项） */
export function defaultPresetDefaults(): Record<`${ModelCapability}_model`, string> {
  return {
    text_model: clampDefaultToPreset("text", ""),
    image_model: clampDefaultToPreset("image", ""),
    video_model: clampDefaultToPreset("video", ""),
    audio_model: clampDefaultToPreset("audio", ""),
  };
}
