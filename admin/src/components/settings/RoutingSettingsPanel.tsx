import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, Plus, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, type AdminRoutingSettings } from "@/api/client";
import {
  ArkVolcMediaPanel,
  ARK_BASE,
  ARK_VOLC_CHANNEL_ID,
  consolidateArkVolcChannels,
  DEFAULT_VIDEO_MODEL,
  inferVolcMediaDraft,
  resolveDefaultModelsFromUpstream,
  type VolcMediaDraft,
} from "@/components/settings/ArkVolcMediaPanel";
import {
  LabeledControl,
  SettingsLoading,
  SettingsPanel,
  SettingsSurface,
  SettingsTabShell,
} from "@/components/settings/SettingsPanel";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";

type ChannelDraft = AdminRoutingSettings["system_channels"][number] & {
  api_key_input: string;
};

type Capability = "text" | "image" | "video" | "audio";

type UpstreamModelOption = { id: string; label: string; capability: string };

const CAPABILITY_LABELS: Record<Capability, string> = {
  text: "文本",
  image: "图像",
  video: "视频",
  audio: "语音",
};

const PROTOCOL_LABELS: Record<string, string> = {
  auto: "自动",
  openai: "OpenAI 兼容",
  ark: "ARK（生图/视频）",
  volc_tts: "豆包 TTS",
};

// 与后端 infer_model_capability 对齐，用于渠道能力徽标
function inferCapability(model: string, protocol: string): Capability {
  const mid = (model || "").trim().toLowerCase().replace(/\s+/g, "");
  const proto = (protocol || "auto").toLowerCase();
  if (proto === "openai") return "text";
  if (proto === "volc_tts") return "audio";
  if (!mid) return "text";
  if (mid.includes("tts") || mid.startsWith("zh_") || mid.includes("speaker") || mid.startsWith("s_")) {
    return "audio";
  }
  if (mid.includes("seedance") || mid.includes("video") || mid.includes("i2v")) return "video";
  if (mid.includes("seedream") || mid.includes("dream") || mid.includes("image")) return "image";
  if (proto === "ark") return "image";
  return "text";
}

function channelCapabilities(channel: AdminRoutingSettings["system_channels"][number]): Capability[] {
  const caps = new Set<Capability>();
  for (const model of channel.models) {
    caps.add(inferCapability(model, channel.protocol));
  }
  if (caps.size === 0 && channel.protocol === "ark") caps.add("image");
  if (caps.size === 0 && channel.protocol === "volc_tts") caps.add("audio");
  if (caps.size === 0) caps.add("text");
  return Array.from(caps);
}

// 计算路由就绪条
function buildReadiness(data: AdminRoutingSettings | null) {
  const channels = data?.system_channels ?? [];
  const enabled = channels.filter((c) => c.enabled);
  const hasCap = (cap: Capability) =>
    enabled.some(
      (c) =>
        (c.has_api_key || Boolean(c.api_key)) &&
        (channelCapabilities(c).includes(cap) || c.models.some((m) => inferCapability(m, c.protocol) === cap)),
    );
  return [
    { id: "text", label: "文本路由", ready: hasCap("text") || Boolean(data?.default_models.text_model) },
    { id: "image", label: "图像路由", ready: hasCap("image") || Boolean(data?.default_models.image_model) },
    { id: "video", label: "视频路由", ready: hasCap("video") || Boolean(data?.default_models.video_model) },
    { id: "audio", label: "语音路由", ready: hasCap("audio") || Boolean(data?.default_models.audio_model) },
    { id: "secret", label: "密钥加密存储", ready: true },
  ] as const;
}

// 渠道 + 逻辑模型路由配置面板（设计稿：就绪条 + 主从渠道 + 方舟专区 + 逻辑路由表）
export function RoutingSettingsPanel() {
  const [data, setData] = useState<AdminRoutingSettings | null>(null);
  const [apiKeyInputs, setApiKeyInputs] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [selectedChannelId, setSelectedChannelId] = useState("");
  const [upstreamModels, setUpstreamModels] = useState<UpstreamModelOption[]>([]);
  const [fetchingModels, setFetchingModels] = useState(false);
  const [manualModel, setManualModel] = useState("");
  const [volcDraft, setVolcDraft] = useState<VolcMediaDraft>({
    imageModel: "",
    image45Model: "",
    videoModel: "",
  });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api<AdminRoutingSettings>("/api/admin/settings/routing");
      const arkChannel =
        res.system_channels.find((c) => c.id === ARK_VOLC_CHANNEL_ID) ??
        res.system_channels.find((c) => c.protocol === "ark");
      setVolcDraft(inferVolcMediaDraft(arkChannel?.models ?? [], inferCapability));
      setData(res);
      setSelectedChannelId((prev) => prev || res.system_channels[0]?.id || "");
      setApiKeyInputs({});
      setUpstreamModels([]);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "加载路由配置失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const channels = useMemo<ChannelDraft[]>(
    () =>
      (data?.system_channels ?? []).map((channel) => ({
        ...channel,
        api_key_input: apiKeyInputs[channel.id] ?? "",
      })),
    [apiKeyInputs, data],
  );

  const selectedChannel =
    channels.find((item) => item.id === selectedChannelId) ?? channels[0] ?? null;
  const arkVolcChannel =
    channels.find((c) => c.id === ARK_VOLC_CHANNEL_ID) ?? channels.find((c) => c.protocol === "ark");
  const readiness = buildReadiness(data);

  const catalogModels = useMemo(() => {
    if (!selectedChannel) return [] as UpstreamModelOption[];
    const map = new Map<string, UpstreamModelOption>();
    for (const m of upstreamModels) map.set(m.id, m);
    for (const id of selectedChannel.models) {
      if (!map.has(id)) {
        map.set(id, {
          id,
          label: id,
          capability: inferCapability(id, selectedChannel.protocol),
        });
      }
    }
    return Array.from(map.values());
  }, [selectedChannel, upstreamModels]);

  function updateChannel(channelId: string, patch: Partial<AdminRoutingSettings["system_channels"][number]>) {
    setData((prev) =>
      prev
        ? {
            ...prev,
            system_channels: prev.system_channels.map((item) =>
              item.id === channelId ? { ...item, ...patch } : item,
            ),
          }
        : prev,
    );
  }

  function insertChannel(channel: AdminRoutingSettings["system_channels"][number]) {
    setData((prev) =>
      prev
        ? {
            ...prev,
            system_channels: [...prev.system_channels, channel],
          }
        : prev,
    );
    setSelectedChannelId(channel.id);
    setUpstreamModels([]);
  }

  // 新增空白 OpenAI 兼容渠道
  function addChannel() {
    const id = `channel-${Date.now()}`;
    insertChannel({
      id,
      name: "新渠道",
      base_url: "",
      api_key: "",
      has_api_key: false,
      api_format: "openai",
      protocol: "openai",
      models: [],
      enabled: true,
      sort_order: channels.length,
    });
  }

  function removeChannel(channelId: string) {
    if (channelId === ARK_VOLC_CHANNEL_ID) {
      toast.error("火山方舟媒体渠道请通过下方专区管理，不可直接删除");
      return;
    }
    setData((prev) =>
      prev
        ? {
            ...prev,
            system_channels: prev.system_channels.filter((item) => item.id !== channelId),
            logical_models: prev.logical_models
              .map((model) => ({
                ...model,
                bindings: model.bindings.filter((binding) => binding.channel_id !== channelId),
              }))
              .filter((model) => model.bindings.length > 0),
          }
        : prev,
    );
    setUpstreamModels([]);
  }

  // 从上游 /models 拉取可用模型
  async function fetchUpstreamModels() {
    if (!selectedChannel) return;
    const keyInput = apiKeyInputs[selectedChannel.id]?.trim();
    if (!selectedChannel.has_api_key && !keyInput) {
      toast.error("请先填写 API Key");
      return;
    }
    if (selectedChannel.protocol === "volc_tts") {
      toast.error("豆包 TTS 请手动填写音色 ID");
      return;
    }
    setFetchingModels(true);
    try {
      const res = await api<{ models: UpstreamModelOption[] }>("/api/admin/settings/upstream/models", {
        method: "POST",
        body: JSON.stringify({
          channel_id: selectedChannel.id,
          protocol: selectedChannel.protocol,
          base_url: selectedChannel.base_url,
          api_key: keyInput || undefined,
          capability: "all",
        }),
      });
      setUpstreamModels(res.models);
      toast.success(`已拉取 ${res.models.length} 个可用模型`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "拉取模型失败");
    } finally {
      setFetchingModels(false);
    }
  }

  function toggleModel(modelId: string, checked: boolean) {
    if (!selectedChannel) return;
    const next = checked
      ? [...new Set([...selectedChannel.models, modelId])]
      : selectedChannel.models.filter((id) => id !== modelId);
    updateChannel(selectedChannel.id, { models: next });
  }

  function addManualModel() {
    if (!selectedChannel) return;
    const id = manualModel.trim();
    if (!id) return;
    if (!selectedChannel.models.includes(id)) {
      updateChannel(selectedChannel.id, { models: [...selectedChannel.models, id] });
    }
    setManualModel("");
  }

  async function handleSave() {
    if (!data) return;
    setSaving(true);
    try {
      const existingArk = data.system_channels.find((c) => c.id === ARK_VOLC_CHANNEL_ID) ?? arkVolcChannel;
      const { channels: mergedChannels } = consolidateArkVolcChannels(
        data.system_channels,
        volcDraft,
        existingArk,
      );

      const res = await api<{ settings: AdminRoutingSettings }>("/api/admin/settings/routing", {
        method: "PATCH",
        body: JSON.stringify({
          system_channels: mergedChannels.map((channel) => ({
            id: channel.id,
            name: channel.name,
            base_url: channel.base_url,
            api_key: apiKeyInputs[channel.id]?.trim() || undefined,
            api_format: channel.api_format,
            protocol: channel.protocol,
            models:
              channel.id === ARK_VOLC_CHANNEL_ID
                ? [
                    ...new Set(
                      [volcDraft.imageModel, volcDraft.image45Model, volcDraft.videoModel].filter(Boolean),
                    ),
                  ]
                : channel.models,
            enabled: channel.enabled,
            sort_order: channel.sort_order,
          })),
          logical_models: data.logical_models,
          default_models: data.default_models,
        }),
      });

      let nextDefaults = resolveDefaultModelsFromUpstream(res.settings, volcDraft);
      if (!nextDefaults.video_model) {
        const preferred =
          res.settings.logical_models.find((m) => m.capability === "video" && m.id === "seedance-2.5") ??
          res.settings.logical_models.find((m) => m.capability === "video");
        if (preferred) nextDefaults = { ...nextDefaults, video_model: preferred.id };
      }

      const arkKey = apiKeyInputs[ARK_VOLC_CHANNEL_ID]?.trim();
      if (
        nextDefaults.image_model !== res.settings.default_models.image_model ||
        nextDefaults.video_model !== res.settings.default_models.video_model
      ) {
        const res2 = await api<{ settings: AdminRoutingSettings }>("/api/admin/settings/routing", {
          method: "PATCH",
          body: JSON.stringify({
            default_models: nextDefaults,
          }),
        });
        setData(res2.settings);
      } else {
        setData(res.settings);
      }

      if (arkKey || volcDraft.imageModel || volcDraft.videoModel) {
        await api("/api/admin/settings/models", {
          method: "PATCH",
          body: JSON.stringify({
            ark_api_key: arkKey || undefined,
            ark_base_url: ARK_BASE,
            model_image: volcDraft.imageModel || undefined,
            model_image_45: volcDraft.image45Model || undefined,
            model_video: volcDraft.videoModel || undefined,
          }),
        });
      }

      setApiKeyInputs({});
      await load();
      toast.success("路由配置已保存");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  if (loading && !data) {
    return <SettingsLoading label="加载路由配置…" />;
  }

  return (
    <SettingsTabShell onSave={() => void handleSave()} saving={saving} saveLabel="保存">
      <SettingsSurface className="settings-readiness-bar">
        <div className="settings-readiness-title">路由就绪状态</div>
        <div className="settings-readiness-row">
          {readiness.map((item) => (
            <div key={item.id} className={cn("settings-readiness-item", item.ready && "is-ready")}>
              <span className={cn("settings-readiness-dot", item.ready ? "is-on" : "is-off")} />
              <span>{item.label}</span>
              <em>{item.ready ? (item.id === "secret" ? "已启用" : "已配置") : "未就绪"}</em>
            </div>
          ))}
        </div>
      </SettingsSurface>

      {(data?.validation_errors.length ?? 0) > 0 ? (
        <SettingsSurface className="border-[#fde2e2] bg-[#fef0f0]">
          <div className="text-xs font-medium text-[#f56c6c]">配置校验</div>
          <ul className="mt-1 space-y-0.5 text-xs text-[#f56c6c]">
            {data?.validation_errors.map((item) => (
              <li key={item}>· {item}</li>
            ))}
          </ul>
        </SettingsSurface>
      ) : null}

      <div className="settings-routing-grid">
        <SettingsPanel
          className="settings-panel--compact"
          title="1. 渠道管理"
          description="启用上游渠道并维护凭证"
          actions={
            <button type="button" className="admin-btn admin-btn-secondary settings-mini-btn" onClick={addChannel}>
              <Plus className="h-3.5 w-3.5" />
              添加渠道
            </button>
          }
        >
          <div className="settings-channel-list">
            {channels.map((channel) => {
              const caps = channelCapabilities(channel);
              return (
                <button
                  key={channel.id}
                  type="button"
                  className={cn(
                    "settings-channel-item",
                    selectedChannel?.id === channel.id && "is-active",
                  )}
                  onClick={() => {
                    setSelectedChannelId(channel.id);
                    setUpstreamModels([]);
                    setManualModel("");
                  }}
                >
                  <div className="settings-channel-item-top">
                    <strong>{channel.name}</strong>
                    <span
                      onClick={(e) => e.stopPropagation()}
                      onKeyDown={(e) => e.stopPropagation()}
                      role="presentation"
                    >
                      <Switch
                        checked={channel.enabled}
                        onCheckedChange={(checked) => {
                          updateChannel(channel.id, { enabled: checked });
                        }}
                      />
                    </span>
                  </div>
                  <div className="settings-channel-item-meta">
                    {caps.map((cap) => (
                      <span key={cap} className={cn("settings-cap-tag", `is-${cap}`)}>
                        {CAPABILITY_LABELS[cap]}
                      </span>
                    ))}
                    {channel.has_api_key ? (
                      <span className="settings-cap-tag">已有 Key</span>
                    ) : (
                      <span className="settings-cap-tag is-warn">缺 Key</span>
                    )}
                  </div>
                </button>
              );
            })}
            {channels.length === 0 ? (
              <div className="settings-empty-hint">暂无渠道，点击右上角添加</div>
            ) : null}
          </div>
        </SettingsPanel>

        <SettingsPanel
          className="settings-panel--compact"
          title={`渠道配置${selectedChannel ? `（当前: ${selectedChannel.name}）` : ""}`}
          description="密钥留空保存不修改；可用模型从上游拉取"
          actions={
            selectedChannel && selectedChannel.id !== ARK_VOLC_CHANNEL_ID ? (
              <button
                type="button"
                className="admin-btn admin-btn-danger settings-mini-btn"
                onClick={() => removeChannel(selectedChannel.id)}
              >
                <Trash2 className="h-3.5 w-3.5" />
                删除
              </button>
            ) : null
          }
        >
          {selectedChannel ? (
            <div className="settings-field-grid">
              <LabeledControl label="名称">
                <input
                  className="settings-input"
                  value={selectedChannel.name}
                  onChange={(e) => updateChannel(selectedChannel.id, { name: e.target.value })}
                />
              </LabeledControl>
              <LabeledControl label="协议">
                <select
                  className="settings-select"
                  value={selectedChannel.protocol}
                  onChange={(e) =>
                    updateChannel(selectedChannel.id, {
                      protocol: e.target.value as AdminRoutingSettings["system_channels"][number]["protocol"],
                      api_format:
                        e.target.value === "ark"
                          ? "ark"
                          : selectedChannel.api_format === "ark"
                            ? "openai"
                            : selectedChannel.api_format,
                    })
                  }
                >
                  {Object.entries(PROTOCOL_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </LabeledControl>
              <LabeledControl label="Base URL" className="settings-field-span-full">
                <input
                  className="settings-input"
                  value={selectedChannel.base_url}
                  onChange={(e) => updateChannel(selectedChannel.id, { base_url: e.target.value })}
                  placeholder={selectedChannel.protocol === "ark" ? ARK_BASE : "https://api.example.com/v1"}
                />
              </LabeledControl>
              <LabeledControl
                label="API Key"
                hint={selectedChannel.has_api_key ? "已保存，留空不修改" : "未配置"}
                className="settings-field-span-full"
              >
                <div className="settings-secret-row">
                  <input
                    className="settings-input is-secret"
                    type="password"
                    placeholder={selectedChannel.has_api_key ? "已保存，留空则不修改" : "输入 API Key"}
                    value={selectedChannel.api_key_input}
                    onChange={(e) =>
                      setApiKeyInputs((prev) => ({ ...prev, [selectedChannel.id]: e.target.value }))
                    }
                  />
                  {selectedChannel.has_api_key || selectedChannel.api_key_input ? (
                    <button
                      type="button"
                      className="admin-btn admin-btn-secondary settings-mini-btn"
                      onClick={() => setApiKeyInputs((prev) => ({ ...prev, [selectedChannel.id]: "" }))}
                    >
                      清除密钥
                    </button>
                  ) : null}
                </div>
              </LabeledControl>

              <LabeledControl
                className="settings-field-span-full"
                label="可用模型"
                hint={
                  selectedChannel.protocol === "volc_tts"
                    ? "TTS 请手动填写音色 ID"
                    : "点击「从上游拉取」后勾选；也可手动追加"
                }
              >
                <div className="settings-model-toolbar">
                  <button
                    type="button"
                    className="admin-btn admin-btn-secondary settings-mini-btn"
                    disabled={fetchingModels || selectedChannel.protocol === "volc_tts"}
                    onClick={() => void fetchUpstreamModels()}
                  >
                    {fetchingModels ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <RefreshCw className="h-3.5 w-3.5" />
                    )}
                    从上游拉取
                  </button>
                  <span className="settings-model-count">
                    已选 {selectedChannel.models.length}
                    {upstreamModels.length > 0 ? ` / 上游 ${upstreamModels.length}` : ""}
                  </span>
                </div>
                <div className="settings-model-catalog">
                  {catalogModels.length === 0 ? (
                    <div className="settings-empty-hint">
                      {selectedChannel.protocol === "volc_tts"
                        ? "在下方手动添加音色 ID"
                        : "尚未拉取，请先配置 Key 后点击「从上游拉取」"}
                    </div>
                  ) : (
                    catalogModels.map((model) => {
                      const checked = selectedChannel.models.includes(model.id);
                      return (
                        <label key={model.id} className={cn("settings-model-option", checked && "is-checked")}>
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={(e) => toggleModel(model.id, e.target.checked)}
                          />
                          <span className="font-mono text-xs">{model.id}</span>
                          <em className={cn("settings-cap-tag", `is-${model.capability}`)}>
                            {CAPABILITY_LABELS[(model.capability as Capability) || "text"] || model.capability}
                          </em>
                        </label>
                      );
                    })
                  )}
                </div>
                <div className="settings-model-manual">
                  <input
                    className="settings-input"
                    value={manualModel}
                    onChange={(e) => setManualModel(e.target.value)}
                    placeholder={
                      selectedChannel.protocol === "volc_tts"
                        ? "手动添加音色 ID"
                        : `手动追加（如 ${DEFAULT_VIDEO_MODEL}）`
                    }
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        addManualModel();
                      }
                    }}
                  />
                  <button type="button" className="admin-btn admin-btn-secondary settings-mini-btn" onClick={addManualModel}>
                    添加
                  </button>
                </div>
              </LabeledControl>
            </div>
          ) : (
            <div className="settings-empty-hint">请选择左侧渠道</div>
          )}
        </SettingsPanel>
      </div>

      <div className="settings-routing-grid">
        <ArkVolcMediaPanel
          channelId={ARK_VOLC_CHANNEL_ID}
          hasApiKey={Boolean(arkVolcChannel?.has_api_key)}
          apiKeyInput={apiKeyInputs[ARK_VOLC_CHANNEL_ID] ?? ""}
          onApiKeyChange={(value) => setApiKeyInputs((prev) => ({ ...prev, [ARK_VOLC_CHANNEL_ID]: value }))}
          draft={volcDraft}
          onDraftChange={(patch) => setVolcDraft((prev) => ({ ...prev, ...patch }))}
        />

        <SettingsPanel
          className="settings-panel--compact"
          title="3. 逻辑模型路由"
          description="能力 → 默认渠道 / 上游模型"
        >
          <div className="settings-field-grid settings-field-grid--2 mb-3">
            {(["text_model", "image_model", "video_model", "audio_model"] as const).map((key) => {
              const cap = key.replace("_model", "") as Capability;
              const options = (data?.logical_models ?? []).filter((model) => model.capability === cap);
              return (
                <LabeledControl key={key} label={`${CAPABILITY_LABELS[cap]}默认`}>
                  <select
                    className="settings-select"
                    value={data?.default_models[key] ?? ""}
                    onChange={(e) =>
                      setData((prev) =>
                        prev
                          ? {
                              ...prev,
                              default_models: { ...prev.default_models, [key]: e.target.value },
                            }
                          : prev,
                      )
                    }
                  >
                    <option value="">未设置</option>
                    {options.map((model) => (
                      <option key={model.id} value={model.id}>
                        {model.name || model.id}
                      </option>
                    ))}
                  </select>
                </LabeledControl>
              );
            })}
          </div>
          <div className="admin-table-wrap settings-logic-table">
            <table>
              <thead>
                <tr>
                  <th>能力</th>
                  <th>默认渠道</th>
                  <th>上游模型</th>
                  <th>优先级</th>
                </tr>
              </thead>
              <tbody>
                {(data?.logical_models ?? []).flatMap((model) =>
                  model.bindings.map((binding) => {
                    const channel = data?.system_channels.find((item) => item.id === binding.channel_id);
                    return (
                      <tr key={`${model.id}-${binding.id}`}>
                        <td>{CAPABILITY_LABELS[model.capability]}</td>
                        <td>{channel?.name ?? binding.channel_id}</td>
                        <td className="font-mono text-xs">{binding.upstream_model}</td>
                        <td>{binding.priority}</td>
                      </tr>
                    );
                  }),
                )}
                {(data?.logical_models ?? []).every((m) => m.bindings.length === 0) ? (
                  <tr>
                    <td colSpan={4} className="text-center text-[#909399]">
                      保存渠道后将自动同步逻辑路由
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </SettingsPanel>
      </div>
    </SettingsTabShell>
  );
}
