import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity } from "lucide-react";
import { toast } from "sonner";
import { api, type AdminModelSettings } from "@/api/client";
import {
  LabeledControl,
  SettingsLoading,
  SettingsPanel,
  SettingsStatusBar,
  SettingsTabShell,
} from "@/components/settings/SettingsPanel";
import { Switch } from "@/components/ui/switch";

// 运行参数配置（并发、质量、Mock 等 flat 字段）
export function RuntimeSettingsPanel() {
  const [form, setForm] = useState<AdminModelSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api<AdminModelSettings>("/api/admin/settings/models");
      setForm(data);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const statusItems = useMemo(
    () =>
      (form?.readiness ?? []).map((item) => ({
        id: item.capability,
        label: item.label,
        ready: item.ready,
        readyText: item.model || "就绪",
        pendingText: "未就绪",
      })),
    [form?.readiness],
  );

  function patchField<K extends keyof AdminModelSettings>(key: K, value: AdminModelSettings[K]) {
    setForm((prev) => (prev ? { ...prev, [key]: value } : prev));
  }

  async function handleSave() {
    if (!form) return;
    setSaving(true);
    try {
      const body = {
        ark_image_size: form.ark_image_size,
        ark_video_resolution: form.ark_video_resolution,
        ark_video_ratio: form.ark_video_ratio,
        seedance_duration_min: form.seedance_duration_min,
        seedance_duration_max: form.seedance_duration_max,
        ark_video_poll_interval: form.ark_video_poll_interval,
        ark_video_poll_timeout: form.ark_video_poll_timeout,
        pipeline_image_concurrency: form.pipeline_image_concurrency,
        pipeline_video_concurrency: form.pipeline_video_concurrency,
        pipeline_audio_concurrency: form.pipeline_audio_concurrency,
        task_runtime_max_concurrency: form.task_runtime_max_concurrency,
        task_user_max_concurrency: form.task_user_max_concurrency,
        task_poll_max_concurrency: form.task_poll_max_concurrency,
        drama_user_video_job_limit: form.drama_user_video_job_limit,
        drama_fragment_max_attempts: form.drama_fragment_max_attempts,
        ark_mock: form.ark_mock,
      };
      await api("/api/admin/settings/models", { method: "PATCH", body: JSON.stringify(body) });
      await load();
      toast.success("运行参数已保存");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  if (loading || !form) {
    return <SettingsLoading />;
  }

  return (
    <SettingsTabShell onSave={() => void handleSave()} saving={saving}>
      <SettingsStatusBar
        title="路由就绪状态"
        items={
          statusItems.length > 0
            ? statusItems
            : [{ id: "empty", label: "能力路由", ready: false, pendingText: "请先配置模型路由" }]
        }
        extra={
          <span className="settings-status-extra">
            {form.readiness?.every((item) => item.ready) ? "四类能力已就绪" : "请在「模型路由」补全渠道"}
          </span>
        }
      />

      <div className="settings-routing-grid">
        <SettingsPanel
          className="settings-panel--compact"
          title="1. 质量与默认值"
          description="生图尺寸、视频清晰度、Seedance 时长与轮询"
        >
          <div className="settings-field-grid">
            <LabeledControl label="默认生图尺寸">
              <input
                className="settings-input"
                value={form.ark_image_size}
                onChange={(e) => patchField("ark_image_size", e.target.value)}
              />
            </LabeledControl>
            <LabeledControl label="默认视频清晰度">
              <input
                className="settings-input"
                value={form.ark_video_resolution}
                onChange={(e) => patchField("ark_video_resolution", e.target.value)}
              />
            </LabeledControl>
            <LabeledControl label="默认视频比例">
              <input
                className="settings-input"
                value={form.ark_video_ratio}
                onChange={(e) => patchField("ark_video_ratio", e.target.value)}
              />
            </LabeledControl>
            <LabeledControl label="Seedance 最小时长（秒）">
              <input
                className="settings-input"
                type="number"
                min={1}
                value={form.seedance_duration_min}
                onChange={(e) => patchField("seedance_duration_min", Number(e.target.value))}
              />
            </LabeledControl>
            <LabeledControl label="Seedance 最大时长（秒）">
              <input
                className="settings-input"
                type="number"
                min={1}
                value={form.seedance_duration_max}
                onChange={(e) => patchField("seedance_duration_max", Number(e.target.value))}
              />
            </LabeledControl>
            <LabeledControl label="视频轮询间隔（秒）">
              <input
                className="settings-input"
                type="number"
                step="0.5"
                value={form.ark_video_poll_interval}
                onChange={(e) => patchField("ark_video_poll_interval", Number(e.target.value))}
              />
            </LabeledControl>
            <LabeledControl label="视频轮询超时（秒）">
              <input
                className="settings-input"
                type="number"
                value={form.ark_video_poll_timeout}
                onChange={(e) => patchField("ark_video_poll_timeout", Number(e.target.value))}
              />
            </LabeledControl>
          </div>
        </SettingsPanel>

        <SettingsPanel
          className="settings-panel--compact"
          title="2. 并发与限制"
          description="管线并发、任务槽位与漫剧分镜上限"
        >
          <div className="settings-field-grid">
            <LabeledControl label="生图并发">
              <input
                className="settings-input"
                type="number"
                min={1}
                value={form.pipeline_image_concurrency}
                onChange={(e) => patchField("pipeline_image_concurrency", Number(e.target.value))}
              />
            </LabeledControl>
            <LabeledControl label="视频并发">
              <input
                className="settings-input"
                type="number"
                min={1}
                value={form.pipeline_video_concurrency}
                onChange={(e) => patchField("pipeline_video_concurrency", Number(e.target.value))}
              />
            </LabeledControl>
            <LabeledControl label="配音并发">
              <input
                className="settings-input"
                type="number"
                min={1}
                value={form.pipeline_audio_concurrency}
                onChange={(e) => patchField("pipeline_audio_concurrency", Number(e.target.value))}
              />
            </LabeledControl>
            <LabeledControl label="任务平台槽位（全站）">
              <input
                className="settings-input"
                type="number"
                min={1}
                value={form.task_runtime_max_concurrency}
                onChange={(e) => patchField("task_runtime_max_concurrency", Number(e.target.value))}
              />
            </LabeledControl>
            <LabeledControl label="单用户任务槽位">
              <input
                className="settings-input"
                type="number"
                min={1}
                value={form.task_user_max_concurrency}
                onChange={(e) => patchField("task_user_max_concurrency", Number(e.target.value))}
              />
            </LabeledControl>
            <LabeledControl label="Selector 轮询并发">
              <input
                className="settings-input"
                type="number"
                min={1}
                value={form.task_poll_max_concurrency}
                onChange={(e) => patchField("task_poll_max_concurrency", Number(e.target.value))}
              />
            </LabeledControl>
            <LabeledControl label="单用户漫剧视频在途上限">
              <input
                className="settings-input"
                type="number"
                min={1}
                value={form.drama_user_video_job_limit}
                onChange={(e) => patchField("drama_user_video_job_limit", Number(e.target.value))}
              />
            </LabeledControl>
            <LabeledControl label="分镜视频最大尝试次数">
              <input
                className="settings-input"
                type="number"
                min={1}
                value={form.drama_fragment_max_attempts}
                onChange={(e) => patchField("drama_fragment_max_attempts", Number(e.target.value))}
              />
            </LabeledControl>
          </div>
          <div className="settings-toggle-row mt-3">
            <div>
              <strong>ARK Mock 模式</strong>
              <span>开发环境模拟生成，不调用真实上游</span>
            </div>
            <Switch checked={form.ark_mock} onCheckedChange={(v) => patchField("ark_mock", v)} />
          </div>
        </SettingsPanel>
      </div>

      <SettingsPanel className="settings-panel--compact" title="3. 运行时摘要" description="当前生效的 Worker / Selector 槽位">
        <div className="settings-runtime-summary">
          <div className="settings-runtime-summary-row">
            <Activity className="h-4 w-4 text-[var(--admin-forest)]" />
            <span>
              Worker 槽位 <strong>{form.task_runtime_max_concurrency}</strong> · 单用户{" "}
              <strong>{form.task_user_max_concurrency}</strong>
            </span>
          </div>
          <p className="settings-runtime-summary-hint">
            Selector 每轮最多 {form.task_poll_max_concurrency} 路上游非阻塞查询；awaiting_poll 不计入 Worker 占用。
          </p>
        </div>
      </SettingsPanel>
    </SettingsTabShell>
  );
}
