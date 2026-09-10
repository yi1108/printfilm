/** 分集编辑：左侧资产栏（本集/全集 + 分类卡片） */
import { resolveDramaMediaUrl, type DramaAsset } from '../../api/drama'
import { CharacterVoicePreviewButton } from '../../components/drama/CharacterVoicePreviewButton'
import { readAssetVoiceBinding } from './CharacterVoiceBindModal'
import {
  ASSET_TABS,
  normalizeAssetTab,
  type AssetScope,
  type AssetTab,
} from './dramaEpisodeEditUtils'

type Props = {
  scope: AssetScope
  tab: AssetTab | null
  assets: DramaAsset[]
  activeIds?: Set<number>
  imageBusyIds?: ReadonlySet<number>
  createBusy?: boolean
  onScopeChange: (scope: AssetScope) => void
  onTabChange: (tab: AssetTab | null) => void
  onOpenCanvas: () => void
  /** 打开资产详情：编辑提示词 / 重新生成 / 上传 */
  onOpenAsset: (asset: DramaAsset) => void
  /** 插入 @asset 到当前分镜脚本 */
  onMention: (asset: DramaAsset) => void
  /** 取消当前分镜对该资产的关联（不删除资产） */
  onUnlinkAsset?: (assetId: number) => void
  onGenerateVoice?: (asset: DramaAsset) => void
  voiceBusyIds?: ReadonlySet<number>
  onVoiceError?: (message: string) => void
  /** 自定义新建当前分类资产 */
  onCreateAsset?: () => void
  /** 从全局资产库导入 */
  onImportAsset?: () => void
}

// 当前分类新建按钮文案
function createLabel(tab: AssetTab | null): string {
  if (tab === 'scene') return '新建场景'
  if (tab === 'prop') return '新建道具'
  return '新建角色'
}

// 渲染分集编辑左侧资产栏
export function EpisodeEditAssetPanel({
  scope,
  tab,
  assets,
  activeIds,
  imageBusyIds,
  createBusy,
  onScopeChange,
  onTabChange,
  onOpenCanvas,
  onOpenAsset,
  onMention,
  onUnlinkAsset,
  onGenerateVoice,
  voiceBusyIds,
  onVoiceError,
  onCreateAsset,
  onImportAsset,
}: Props) {
  return (
    <aside className="drama-ep-assets">
      <div className="drama-ep-assets-top">
        <div className="drama-ep-scope">
          <button
            type="button"
            className={scope === 'episode' ? 'active' : ''}
            onClick={() => onScopeChange('episode')}
          >
            本集
          </button>
          <button
            type="button"
            className={scope === 'series' ? 'active' : ''}
            onClick={() => onScopeChange('series')}
          >
            全集
          </button>
        </div>
        <button
          type="button"
          className="drama-ep-icon-btn solid"
          aria-label="打开分镜故事板画布"
          onClick={onOpenCanvas}
        >
          +
        </button>
      </div>
      <div className="drama-ep-asset-tabs">
        {ASSET_TABS.map((item) => (
          <button
            key={item.key}
            type="button"
            className={tab === item.key ? 'active' : ''}
            onClick={() => onTabChange(tab === item.key ? null : item.key)}
          >
            {item.label}
          </button>
        ))}
      </div>
      {onCreateAsset || onImportAsset ? (
        <div className="drama-ep-asset-actions">
          {onCreateAsset ? (
            <button
              type="button"
              className="drama-ep-asset-action-btn"
              disabled={createBusy}
              onClick={onCreateAsset}
            >
              {createBusy ? '创建中…' : createLabel(tab)}
            </button>
          ) : null}
          {onImportAsset ? (
            <button
              type="button"
              className="drama-ep-asset-action-btn is-ghost"
              disabled={createBusy}
              onClick={onImportAsset}
            >
              导入
            </button>
          ) : null}
        </div>
      ) : null}
      <div className="drama-ep-asset-grid">
        {assets.length === 0 ? (
          <p className="drama-ep-empty">
            {scope === 'episode'
              ? '本集暂无引用资产，可点上方「新建」加入，或切换「全集」查看项目资产'
              : '暂无资产，可点上方「新建 / 导入」添加'}
          </p>
        ) : (
          assets.map((asset) => {
            const cover = resolveDramaMediaUrl(asset.cover || asset.url)
            const isScene = normalizeAssetTab(asset.type) === 'scene'
            const isCharacter = normalizeAssetTab(asset.type) === 'character'
            const voice = isCharacter ? readAssetVoiceBinding(asset) : null
            const isActive = activeIds?.has(asset.id)
            const voiceGenerating = voiceBusyIds?.has(asset.id) ?? false
            const imageBusy = imageBusyIds?.has(asset.id) ?? false
            return (
              <div key={asset.id} className="drama-ep-asset-card-wrap">
                <button
                  type="button"
                  className={`drama-ep-asset-card ${isScene ? 'scene' : ''}${isActive ? ' is-linked' : ''}${
                    imageBusy ? ' is-gen' : ''
                  }`}
                  onClick={() => onOpenAsset(asset)}
                  title="点击设置：编辑提示词、重新生成或上传形象"
                >
                  <div className="drama-ep-asset-thumb">
                    {cover ? (
                      <img src={cover} alt="" loading="lazy" decoding="async" />
                    ) : (
                      <span>{(asset.name || '?')[0]}</span>
                    )}
                    {imageBusy ? <em className="drama-ep-asset-gen-badge">生成中</em> : null}
                  </div>
                  <span className="drama-ep-asset-name">{asset.name || `资产 ${asset.id}`}</span>
                  {isActive ? <span className="drama-ep-asset-linked">已关联</span> : null}
                  {voice ? <span className="drama-ep-asset-voice">音色</span> : null}
                  <span className="drama-ep-asset-settings">设置</span>
                </button>
                <div className="drama-ep-asset-ops">
                  {isActive && onUnlinkAsset ? (
                    <button
                      type="button"
                      className="drama-ep-asset-op-btn"
                      onClick={() => onUnlinkAsset(asset.id)}
                      title="仅取消当前分镜关联，不会删除资产"
                    >
                      取消关联
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="drama-ep-asset-op-btn"
                      onClick={() => onMention(asset)}
                      title="插入到当前分镜脚本"
                    >
                      插入
                    </button>
                  )}
                  {isCharacter && onGenerateVoice ? (
                    voice ? (
                      <CharacterVoicePreviewButton
                        url={voice.url}
                        label={voice.label}
                        variant="inline"
                        className="drama-ep-asset-voice-btn is-bound"
                        onError={onVoiceError}
                      />
                    ) : (
                      <button
                        type="button"
                        className="drama-ep-asset-voice-btn"
                        disabled={voiceGenerating}
                        onClick={() => onGenerateVoice(asset)}
                      >
                        {voiceGenerating ? '生成中…' : '生成音色'}
                      </button>
                    )
                  ) : null}
                </div>
              </div>
            )
          })
        )}
      </div>
    </aside>
  )
}
