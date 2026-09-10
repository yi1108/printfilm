import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import Modal from './Modal'
import { useI18n } from '../../i18n'
import { filterHelpFaq } from '../../lib/helpContent'

type Tab = 'guide' | 'faq' | 'tools'

type Props = {
  open: boolean
  onClose: () => void
}

/** 帮助中心抽屉（与 /help 页共用文案） */
export default function HelpCenter({ open, onClose }: Props) {
  const { t, m } = useI18n()
  /*
   * tab 当前分区
   * openFaq 展开的 FAQ
   * q 搜索词
   */
  const [tab, setTab] = useState<Tab>('guide')
  const [openFaq, setOpenFaq] = useState<number | null>(0)
  const [q, setQ] = useState('')

  const faqFiltered = useMemo(() => filterHelpFaq([...m.help.faq], q), [m.help.faq, q])

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t('help.title')}
      variant="drawer"
      className="pf-help-modal"
      footer={
        <>
          <Link to="/help" className="pf-btn pf-btn-ghost pf-btn-sm" onClick={onClose}>
            {t('help.fullPage')}
          </Link>
          <button type="button" className="pf-btn pf-btn-lime pf-btn-sm" onClick={onClose}>
            {t('help.gotIt')}
          </button>
        </>
      }
    >
      <div className="pf-help">
        <label className="pf-help-search">
          <span className="sr-only">{t('help.search')}</span>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t('help.drawerSearch')}
          />
        </label>

        <div className="pf-help-cats">
          {m.help.drawerCats.map((c) => (
            <button
              key={c.id}
              type="button"
              className={`pf-help-cat${tab === c.id ? ' is-active' : ''}`}
              onClick={() => setTab(c.id as Tab)}
            >
              <strong>{c.title}</strong>
              <span>{c.desc}</span>
            </button>
          ))}
        </div>

        {tab === 'guide' ? (
          <ol className="pf-help-steps">
            {m.help.steps.map((s) => (
              <li key={s.n}>
                <span className="pf-help-step-n" aria-hidden>
                  {s.n}
                </span>
                <div>
                  <strong>{s.title}</strong>
                  <p>{s.body}</p>
                </div>
              </li>
            ))}
          </ol>
        ) : null}

        {tab === 'faq' ? (
          <div className="pf-help-faq">
            {faqFiltered.map((item, i) => {
              const expanded = openFaq === i
              return (
                <div key={item.q} className={`pf-help-faq-item${expanded ? ' open' : ''}`}>
                  <button
                    type="button"
                    className="pf-help-faq-q"
                    aria-expanded={expanded}
                    onClick={() => setOpenFaq(expanded ? null : i)}
                  >
                    <span>{item.q}</span>
                    <span className="pf-help-faq-chev" aria-hidden />
                  </button>
                  {expanded ? <p className="pf-help-faq-a">{item.a}</p> : null}
                </div>
              )
            })}
            {faqFiltered.length === 0 ? <p className="pf-muted">{t('help.noFaq')}</p> : null}
          </div>
        ) : null}

        {tab === 'tools' ? (
          <div className="pf-help-tools-note">
            <p>{t('help.toolsNote')}</p>
            <div className="pf-help-tools-actions">
              <Link to="/tools" className="pf-btn pf-btn-lime pf-btn-sm" onClick={onClose}>
                {t('help.openTools')}
              </Link>
              <Link to="/settings?tab=tools" className="pf-btn pf-btn-ghost pf-btn-sm" onClick={onClose}>
                {t('help.toolRecords')}
              </Link>
            </div>
          </div>
        ) : null}
      </div>
    </Modal>
  )
}
