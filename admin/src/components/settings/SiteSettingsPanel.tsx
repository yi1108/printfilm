import {
  LabeledControl,
  SettingsLoading,
  SettingsPanel,
  SettingsStatusBar,
  SettingsTabShell,
} from "@/components/settings/SettingsPanel";
import { Switch } from "@/components/ui/switch";
import { useAdminModelSettings } from "@/hooks/useAdminModelSettings";

/** 站点公网地址与媒体工具路径 */
export function SiteSettingsPanel() {
  const { form, loading, saving, patchField, save } = useAdminModelSettings();

  async function handleSave() {
    if (!form) return;
    await save(
      {
        public_base_url: form.public_base_url,
        ffmpeg_path: form.ffmpeg_path,
        ffprobe_path: form.ffprobe_path,
        marketplace_enabled: form.marketplace_enabled,
        marketplace_app_enabled: form.marketplace_app_enabled,
        marketplace_social_initialization_enabled: form.marketplace_social_initialization_enabled,
        marketplace_sharing_enabled: form.marketplace_sharing_enabled,
        marketplace_share_base_url: (form.marketplace_share_base_url || '').trim(),
        marketplace_share_apple_team_id: (form.marketplace_share_apple_team_id || '').trim(),
        marketplace_max_duration_seconds: form.marketplace_max_duration_seconds,
      },
      "站点配置已保存",
    );
  }

  if (loading || !form) {
    return <SettingsLoading />;
  }

  const hasPublic = Boolean(form.public_base_url?.trim());
  const hasFfmpeg = Boolean(form.ffmpeg_path?.trim());
  const hasFfprobe = Boolean(form.ffprobe_path?.trim());

  return (
    <SettingsTabShell onSave={handleSave} saving={saving} saveLabel="保存站点设置">
      <SettingsStatusBar
        title="站点工具状态"
        items={[
          {
            id: "public",
            label: "公网地址",
            ready: hasPublic,
            readyText: "已配置",
            pendingText: "未填写",
          },
          {
            id: "ffmpeg",
            label: "ffmpeg",
            ready: hasFfmpeg,
            readyText: form.ffmpeg_path || "已配置",
            pendingText: "使用默认 PATH",
          },
          {
            id: "ffprobe",
            label: "ffprobe",
            ready: hasFfprobe,
            readyText: form.ffprobe_path || "已配置",
            pendingText: "使用默认 PATH",
          },
          {
            id: "marketplace",
            label: "数字资产市场",
            ready: form.marketplace_enabled,
            readyText: "已启用",
            pendingText: "未启用",
          },
          {
            id: "marketplace-app",
            label: "App 视频",
            ready: form.marketplace_app_enabled,
            readyText: "已启用",
            pendingText: "未启用",
          },
        ]}
      />

      <div className="settings-routing-grid">
        <SettingsPanel
          className="settings-panel--compact"
          title="站点访问地址"
          description="供支付回调、分享链接和媒体地址回填使用，填写可从公网访问的后端地址。"
        >
          <div className="settings-field-grid">
            <LabeledControl
              label="后端公网基址"
              hint="例如 https://www.printfilm.com；留空使用服务器默认配置。"
              optional
              className="settings-field-span-full"
            >
              <input
                className="settings-input"
                type="url"
                placeholder="https://www.printfilm.com"
                autoComplete="url"
                value={form.public_base_url}
                onChange={(e) => patchField("public_base_url", e.target.value)}
              />
            </LabeledControl>
          </div>
          <p className="settings-panel-footnote">
            数据库、Redis、SECRET_KEY 等基础设施仍通过服务器环境变量配置，不在此页修改。
          </p>
        </SettingsPanel>

        <SettingsPanel
          className="settings-panel--compact"
          title="媒体处理工具"
          description="视频合成与抽帧使用服务器上的工具。已加入服务器 PATH 时，可保持默认名称。"
        >
          <div className="settings-field-grid">
            <LabeledControl label="视频处理工具（ffmpeg）" hint="可填写命令名或服务器上的完整路径。" optional>
              <input
                className="settings-input"
                placeholder="ffmpeg"
                value={form.ffmpeg_path}
                onChange={(e) => patchField("ffmpeg_path", e.target.value)}
              />
            </LabeledControl>
            <LabeledControl label="媒体信息工具（ffprobe）" hint="与 ffmpeg 使用同一安装目录。" optional>
              <input
                className="settings-input"
                placeholder="ffprobe"
                value={form.ffprobe_path}
                onChange={(e) => patchField("ffprobe_path", e.target.value)}
              />
            </LabeledControl>
          </div>
        </SettingsPanel>

        <SettingsPanel
          className="settings-panel--compact"
          title="3. 数字资产市场"
          description="线上没有环境文件时，在这里打开入口"
        >
          <div className="settings-toggle-row">
            <div>
              <strong>启用数字资产市场</strong>
              <span>保存后用户端出现「数字资产市场」，管理端「业务」出现「数字资产平台运营」。上传仍使用「存储 OSS」。</span>
            </div>
            <Switch
              checked={form.marketplace_enabled}
              onCheckedChange={(value) => patchField("marketplace_enabled", value)}
            />
          </div>
          <div className="settings-toggle-row">
            <div>
              <strong>启用 App 视频服务</strong>
              <span>保存后开放 App 视频列表和播放。在这里开关即可，不需要改容器环境变量。需要同时启用数字资产市场。</span>
            </div>
            <Switch
              checked={form.marketplace_app_enabled}
              onCheckedChange={(value) => patchField("marketplace_app_enabled", value)}
            />
          </div>
          <LabeledControl
            label="完整视频最长时长"
            hint="单位为秒。默认 1800，即 30 分钟。上传、合成和 App 完整播放共用。试看仍最多 15 秒，且不超过原片时长的 30%。"
          >
            <input
              className="settings-input"
              type="number"
              min={1}
              max={86400}
              step={1}
              value={form.marketplace_max_duration_seconds}
              onChange={(e) => patchField("marketplace_max_duration_seconds", Number(e.target.value))}
            />
          </LabeledControl>
        </SettingsPanel>
        <SettingsPanel className="settings-panel--compact" title="4. App 互动与作品分享" description="初始化数量、真实分享与 Apple 链接关联均在这里配置，无需修改环境文件。">
          <div className="settings-toggle-row"><div><strong>自动初始化互动数量</strong><span>为新上架且符合 App 展示条件的单视频和分集生成一次初始数量。历史作品请到数字资产平台运营的互动运营页批量补齐；关闭不会清除已保存数量。</span></div><Switch checked={form.marketplace_social_initialization_enabled ?? false} onCheckedChange={value => patchField("marketplace_social_initialization_enabled", value)} /></div>
          <div className="settings-toggle-row"><div><strong>启用作品分享</strong><span>允许分享单视频和当前短剧分集的业务链接。需要有效的公网 HTTPS 域名，不能填写 localhost 或局域网地址。</span></div><Switch checked={form.marketplace_sharing_enabled ?? false} onCheckedChange={value => patchField("marketplace_sharing_enabled", value)} /></div>
          <div className="settings-field-grid">
            <LabeledControl label="分享公网基址" hint="例如 https://www.printfilm.com；域名应将 /s/ 和 /.well-known/apple-app-site-association 转发至后端，其余作品页面交给 Web。" className="settings-field-span-full"><input className="settings-input" type="url" value={form.marketplace_share_base_url ?? ''} onChange={event => patchField("marketplace_share_base_url", event.target.value)} placeholder="https://www.printfilm.com" /></LabeledControl>
            <LabeledControl label="Apple Team ID" hint="Apple 开发者账号中的 Team ID，用于 Universal Links 关联。"><input className="settings-input" value={form.marketplace_share_apple_team_id ?? ''} maxLength={10} onChange={event => patchField("marketplace_share_apple_team_id", event.target.value)} placeholder="ABCDEFGHIJ" /></LabeledControl>
            <LabeledControl label="App Bundle ID" hint="复用“支付与通知 → Apple 服务器连接”中的 Bundle ID；如需调整，请到该处保存。"><input className="settings-input" readOnly value={form.apple_bundle_id || '尚未配置，请到 Apple 服务器连接填写'} /></LabeledControl>
          </div>
          <p className="settings-panel-footnote">App 还需配置 Associated Domains 并完成真机验证。保存域名不会自动修改 DNS、反向代理或 iOS 工程。</p>
        </SettingsPanel>
      </div>
    </SettingsTabShell>
  );
}
