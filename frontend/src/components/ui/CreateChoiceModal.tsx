import { Link, useNavigate } from 'react-router-dom'
import { Clapperboard, Video } from 'lucide-react'
import { useI18n } from '../../i18n'
import Modal from './Modal'

type Props = {
  open: boolean
  onClose: () => void
}

/** 开始创作：在漫剧与科普之间选择入口 */
export default function CreateChoiceModal({ open, onClose }: Props) {
  const nav = useNavigate()
  const { t } = useI18n()

  // 跳转到目标产品并关闭弹层
  function go(path: string) {
    onClose()
    nav(path)
  }

  return (
    <Modal open={open} onClose={onClose} title={t('create.title')} size="md">
      <p className="pf-muted" style={{ marginTop: 0 }}>
        {t('create.hint')}
      </p>
      <div className="pf-create-choice">
        <button type="button" className="pf-create-choice-card" onClick={() => go('/drama')}>
          <span className="pf-ws-product-icon" aria-hidden>
            <Clapperboard size={24} strokeWidth={1.6} />
          </span>
          <strong>{t('create.drama')}</strong>
          <span className="pf-muted">{t('create.dramaHint')}</span>
        </button>
        <button type="button" className="pf-create-choice-card" onClick={() => go('/studio/new')}>
          <span className="pf-ws-product-icon" aria-hidden>
            <Video size={24} strokeWidth={1.6} />
          </span>
          <strong>{t('create.kepu')}</strong>
          <span className="pf-muted">{t('create.kepuHint')}</span>
        </button>
      </div>
      <p className="pf-create-choice-foot">
        {t('create.toolsFootPrefix')}{' '}
        <Link to="/tools" onClick={onClose}>
          {t('create.toolsFootLink')}
        </Link>
        {t('create.toolsFootSuffix') ? ` ${t('create.toolsFootSuffix')}` : ''}
      </p>
    </Modal>
  )
}
