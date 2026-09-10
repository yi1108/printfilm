/** 资产库「音色」Tab 单卡：描述编辑、试听与合成 */
import { AudioLines, Trash2, Volume2 } from 'lucide-react'
import { resolveDramaMediaUrl, type DramaAsset } from '../../api/drama'
import { CharacterVoicePreviewButton } from '../../components/drama/CharacterVoicePreviewButton'

type Props = {
  asset: DramaAsset
  promptValue: string
  synthBusy: boolean
  onPromptChange: (value: string) => void
  onPromptBlur: () => void
  onSynth: () => void
  onDelete: () => void
  onError: (message: string) => void
}

// 渲染音色资产卡片
export function DramaVoiceAssetCard({
  asset,
  promptValue,
  synthBusy,
  onPromptChange,
  onPromptBlur,
  onSynth,
  onDelete,
  onError,
}: Props) {
  const audioSrc = resolveDramaMediaUrl(asset.url)
  const hasAudio = Boolean(audioSrc)

  return (
    <article className="drama-voice-card">
      <header className="drama-voice-card-head">
        <div className="drama-voice-card-badge" aria-hidden>
          <AudioLines size={18} strokeWidth={1.75} />
        </div>
        <div className="drama-voice-card-title">
          <h3>{asset.name || '未命名音色'}</h3>
          <span className={`drama-voice-card-status${hasAudio ? ' is-ready' : ' is-pending'}`}>
            {hasAudio ? '已合成' : '待合成'}
          </span>
        </div>
        <button
          type="button"
          className="drama-voice-card-delete"
          aria-label={`删除 ${asset.name || '音色'}`}
          disabled={synthBusy}
          onClick={onDelete}
        >
          <Trash2 size={15} strokeWidth={1.75} />
        </button>
      </header>

      <div className="drama-voice-card-body">
        <label className="drama-voice-card-field">
          <span>音色描述</span>
          <textarea
            rows={3}
            value={promptValue}
            disabled={synthBusy}
            onChange={(e) => onPromptChange(e.target.value)}
            onBlur={onPromptBlur}
            placeholder="描述音色：年龄、性别、语气、语速…"
          />
        </label>

        <div className={`drama-voice-card-player${hasAudio ? '' : ' is-empty'}`}>
          {hasAudio ? (
            <>
              <CharacterVoicePreviewButton
                url={asset.url || ''}
                label={asset.name || undefined}
                variant="button"
                size="sm"
                onError={onError}
              />
              <audio className="drama-voice-card-audio" controls preload="none" src={audioSrc} />
            </>
          ) : (
            <>
              <Volume2 size={16} strokeWidth={1.75} aria-hidden />
              <span>填写描述后合成试听</span>
            </>
          )}
        </div>
      </div>

      <footer className="drama-voice-card-foot">
        <button
          type="button"
          className="pf-btn pf-btn-lime pf-btn-sm drama-voice-card-synth"
          disabled={synthBusy || !promptValue.trim()}
          onClick={onSynth}
        >
          {synthBusy ? '合成中…' : hasAudio ? '重新合成' : '按提示词合成'}
        </button>
      </footer>
    </article>
  )
}
