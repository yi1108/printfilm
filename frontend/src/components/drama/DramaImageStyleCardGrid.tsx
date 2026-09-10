/** 画面风格卡片网格：无风格 + 缩略图选项 */
import { Check } from 'lucide-react'
import { DramaImageStylePreviewImg } from './DramaImageStylePreviewImg'
import { IMAGE_STYLE_OPTIONS, type ImageStyleId } from '../../lib/dramaImageStyles'

type Props = {
  value: ImageStyleId | ''
  onChange: (id: ImageStyleId | '') => void
  allowNone?: boolean
  noneLabel?: string
  className?: string
}

// 渲染可点选的画面风格卡片网格
export function DramaImageStyleCardGrid({
  value,
  onChange,
  allowNone = true,
  noneLabel = '无风格',
  className,
}: Props) {
  return (
    <div className={['drama-style-modal-grid', className].filter(Boolean).join(' ')}>
      {allowNone ? (
        <button
          type="button"
          className={`drama-style-modal-none${!value ? ' is-selected' : ''}`}
          onClick={() => onChange('')}
        >
          {!value ? <Check className="drama-style-modal-check" size={12} strokeWidth={2.5} /> : null}
          {noneLabel}
        </button>
      ) : null}
      {IMAGE_STYLE_OPTIONS.map((opt) => {
        const selected = value === opt.id
        return (
          <button
            key={opt.id}
            type="button"
            className={`drama-style-modal-card${selected ? ' is-selected' : ''}`}
            onClick={() => onChange(opt.id)}
          >
            <DramaImageStylePreviewImg styleId={opt.id} alt={opt.label} />
            <span>{opt.label}</span>
            {selected ? (
              <Check className="drama-style-modal-check on-media" size={12} strokeWidth={2.5} />
            ) : null}
          </button>
        )
      })}
    </div>
  )
}
