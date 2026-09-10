import { useCallback, useMemo, useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api/client";
import { LabeledControl, SettingsPanel } from "@/components/settings/SettingsPanel";
import { SecretField } from "@/components/settings/SecretField";

export const ARK_VOLC_CHANNEL_ID = "ark-volc-media";
export const ARK_BASE = "https://ark.cn-beijing.volces.com/api/v3";
export const DEFAULT_VIDEO_MODEL = "doubao-seedance-2-5-260628";
export const DEFAULT_IMAGE_MODEL = "doubao-seedream-5-0-260128";

type ArkModelOption = { id: string; label: string; capability: string };

export type VolcMediaDraft = {
  imageModel: string;
  image45Model: string;
  videoModel: string;
};

type ArkVolcMediaPanelProps = {
  channelId: string;
  hasApiKey: boolean;
  apiKeyInput: string;
  onApiKeyChange: (value: string) => void;
  draft: VolcMediaDraft;
  onDraftChange: (patch: Partial<VolcMediaDraft>) => void;
};

function modelOptions(
  fetched: ArkModelOption[],
  current: string,
  capability: string,
): ArkModelOption[] {
  if (fetched.length > 0) return fetched;
  if (!current) return [];
  return [{ id: current, label: current, capability }];
}

/** 火山方舟生图/视频：固定渠道 + 手动拉取模型 */
export function ArkVolcMediaPanel({
  channelId: _channelId,
  hasApiKey,
  apiKeyInput,
  onApiKeyChange,
  draft,
  onDraftChange,
}: ArkVolcMediaPanelProps) {
  const [imageModels, setImageModels] = useState<ArkModelOption[]>([]);
  const [videoModels, setVideoModels] = useState<ArkModelOption[]>([]);
  const [fetching, setFetching] = useState(false);

  const canFetch = useMemo(
    () => hasApiKey || apiKeyInput.trim().length > 0,
    [apiKeyInput, hasApiKey],
  );

  const fetchModels = useCallback(async () => {
    if (!canFetch) {
      toast.error("请先填写方舟 API Key");
      return;
    }
    setFetching(true);
    try {
      const body: { capability: string; api_key?: string } = { capability: "image" };
      const videoBody: { capability: string; api_key?: string } = { capability: "video" };
      if (apiKeyInput.trim()) {
        body.api_key = apiKeyInput.trim();
        videoBody.api_key = apiKeyInput.trim();
      }
      const [imageRes, videoRes] = await Promise.all([
        api<{ models: ArkModelOption[] }>("/api/admin/settings/ark/models", {
          method: "POST",
          body: JSON.stringify(body),
        }),
        api<{ models: ArkModelOption[] }>("/api/admin/settings/ark/models", {
          method: "POST",
          body: JSON.stringify(videoBody),
        }),
      ]);
      setImageModels(imageRes.models);
      setVideoModels(videoRes.models);
      toast.success(`已拉取 ${imageRes.models.length} 个生图、${videoRes.models.length} 个视频模型`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "拉取模型失败");
    } finally {
      setFetching(false);
    }
  }, [apiKeyInput, canFetch]);

  const imageOptions = modelOptions(imageModels, draft.imageModel, "image");
  const videoOptions = modelOptions(videoModels, draft.videoModel, "video");

  return (
    <SettingsPanel
      className="settings-panel--compact"
      title="2. 火山方舟媒体专区"
      description={`固定 Base URL · ${ARK_BASE}`}
      actions={
        <button
          type="button"
          className="admin-btn admin-btn-secondary settings-mini-btn"
          disabled={fetching || !canFetch}
          onClick={() => void fetchModels()}
        >
          {fetching ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          拉取模型
        </button>
      }
    >
      <div className="settings-ark-compact">
        <div className="settings-ark-key-row">
          <SecretField
            label="方舟 API Key"
            value={apiKeyInput}
            configured={hasApiKey}
            onChange={onApiKeyChange}
            onClear={() => onApiKeyChange("")}
          />
          {!canFetch ? (
            <p className="settings-ark-hint">填写 Key 后可拉取上游模型列表；未拉取时仍可使用已保存的模型 ID。</p>
          ) : imageModels.length === 0 && videoModels.length === 0 ? (
            <p className="settings-ark-hint">尚未拉取模型，点击右上角「拉取模型」更新下拉选项。</p>
          ) : null}
        </div>

        <div className="settings-field-grid settings-field-grid--3">
          <LabeledControl label="默认生图（Seedream）">
            <select
              className="settings-select font-mono text-xs"
              value={draft.imageModel}
              onChange={(e) => onDraftChange({ imageModel: e.target.value })}
            >
              <option value="">— 请选择 —</option>
              {imageOptions.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label !== item.id ? `${item.label} · ${item.id}` : item.id}
                </option>
              ))}
            </select>
          </LabeledControl>
          <LabeledControl label="Seedream 4.5（可选）">
            <select
              className="settings-select font-mono text-xs"
              value={draft.image45Model}
              onChange={(e) => onDraftChange({ image45Model: e.target.value })}
            >
              <option value="">— 不单独配置 —</option>
              {imageOptions.map((item) => (
                <option key={`45-${item.id}`} value={item.id}>
                  {item.label !== item.id ? `${item.label} · ${item.id}` : item.id}
                </option>
              ))}
            </select>
          </LabeledControl>
          <LabeledControl label="默认视频（Seedance）" hint="视频生成依赖此模型">
            <select
              className="settings-select font-mono text-xs"
              value={draft.videoModel}
              onChange={(e) => onDraftChange({ videoModel: e.target.value })}
            >
              <option value="">— 请选择 —</option>
              {videoOptions.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label !== item.id ? `${item.label} · ${item.id}` : item.id}
                </option>
              ))}
            </select>
          </LabeledControl>
        </div>
      </div>
    </SettingsPanel>
  );
}

/** 从渠道 models 推断生图/视频草稿 */
export function inferVolcMediaDraft(
  models: string[],
  inferCapability: (model: string, protocol: string) => "text" | "image" | "video" | "audio",
): VolcMediaDraft {
  const images = models.filter((m) => inferCapability(m, "ark") === "image");
  const videos = models.filter((m) => inferCapability(m, "ark") === "video");
  const imageModel = images.find((m) => m.includes("5-0") || m.includes("5.0")) ?? images[0] ?? DEFAULT_IMAGE_MODEL;
  const image45Model = images.find((m) => m !== imageModel && (m.includes("4-5") || m.includes("4.5"))) ?? "";
  const videoModel = videos[0] ?? DEFAULT_VIDEO_MODEL;
  return { imageModel, image45Model, videoModel };
}

/** 合并为单一方舟渠道，移除多余 ARK 渠道 */
export function consolidateArkVolcChannels<
  T extends { id: string; protocol: string; models: string[]; name: string; base_url: string; api_format: string; enabled: boolean; sort_order: number },
>(channels: T[], volcDraft: VolcMediaDraft, existing?: T): { channels: T[]; volcChannelId: string } {
  const models = [...new Set([volcDraft.imageModel, volcDraft.image45Model, volcDraft.videoModel].filter(Boolean))];
  const otherArk = channels.filter((c) => c.protocol === "ark");
  const base = existing ?? otherArk[0];
  const volcChannel = {
    ...(base as T),
    id: ARK_VOLC_CHANNEL_ID,
    name: "火山方舟（生图/视频）",
    base_url: ARK_BASE,
    api_format: "ark",
    protocol: "ark",
    models,
    enabled: true,
    sort_order: base?.sort_order ?? 1,
  } as T;
  const rest = channels.filter((c) => c.protocol !== "ark" || c.id === ARK_VOLC_CHANNEL_ID);
  const withoutDup = rest.filter((c) => c.id !== ARK_VOLC_CHANNEL_ID);
  return { channels: [volcChannel, ...withoutDup], volcChannelId: ARK_VOLC_CHANNEL_ID };
}

export function resolveDefaultModelsFromUpstream(
  settings: {
    logical_models: Array<{
      id: string;
      capability: string;
      bindings: Array<{ upstream_model: string }>;
    }>;
    default_models: { image_model: string; video_model: string; text_model: string; audio_model: string };
  },
  draft: VolcMediaDraft,
) {
  const findLogical = (capability: string, upstream: string) =>
    settings.logical_models.find(
      (m) => m.capability === capability && m.bindings.some((b) => b.upstream_model === upstream),
    )?.id ?? "";

  const next = { ...settings.default_models };
  if (draft.imageModel) {
    const id = findLogical("image", draft.imageModel);
    if (id) next.image_model = id;
  }
  if (draft.videoModel) {
    const id = findLogical("video", draft.videoModel);
    if (id) next.video_model = id;
  }
  return next;
}
