import { Link } from 'react-router-dom'
import { ArrowRight } from 'lucide-react'
import AppShell from '../components/layout/AppShell'
import ComingSoon from '../components/ui/ComingSoon'
import { useI18n } from '../i18n'
import { PRODUCT_ICONS, localizeToolDefs } from '../lib/toolsCatalog'

export default function ToolsPage() {
  const { t, m } = useI18n()
  const DramaIcon = PRODUCT_ICONS.drama
  const KepuIcon = PRODUCT_ICONS.kepu
  const tools = localizeToolDefs(m)

  return (
    <AppShell active="tools">
      <div className="pf-page-head">
        <div>
          <h1>{t('tools.title')}</h1>
          <p className="pf-muted">{t('tools.lead')}</p>
        </div>
      </div>
      <div className="pf-tools-grid pf-tools-grid-lg">
        {tools.map((tool) => {
          const Icon = tool.icon
          return (
            <Link
              key={tool.id}
              to={`/tools/${tool.id}`}
              className={`pf-tools-card pf-tools-card-lg${tool.soon ? ' is-soon' : ''}`}
            >
              <div className="pf-tools-card-top">
                <span className="pf-ws-tool-icon" aria-hidden>
                  <Icon size={22} strokeWidth={1.6} />
                </span>
                <span className="pf-tools-arrow" aria-hidden>
                  <ArrowRight size={14} strokeWidth={2} />
                </span>
              </div>
              <h3>
                {tool.title}
                {tool.soon ? <ComingSoon /> : null}
              </h3>
              <p>{tool.desc}</p>
            </Link>
          )
        })}
      </div>
      <section className="pf-ws-products" style={{ marginTop: '2.5rem' }}>
        <Link to="/drama" className="pf-ws-product pf-ws-product-drama">
          <span className="pf-ws-product-icon" aria-hidden>
            <DramaIcon size={26} strokeWidth={1.6} />
          </span>
          <span className="pf-ws-product-body">
            <strong>{t('tools.goDrama')}</strong>
            <span>{t('tools.goDramaHint')}</span>
          </span>
          <span className="pf-ws-product-go" aria-hidden>
            <ArrowRight size={16} strokeWidth={2} />
          </span>
        </Link>
        <Link to="/history" className="pf-ws-product pf-ws-product-kepu">
          <span className="pf-ws-product-icon" aria-hidden>
            <KepuIcon size={26} strokeWidth={1.6} />
          </span>
          <span className="pf-ws-product-body">
            <strong>{t('tools.goKepu')}</strong>
            <span>{t('tools.goKepuHint')}</span>
          </span>
          <span className="pf-ws-product-go" aria-hidden>
            <ArrowRight size={16} strokeWidth={2} />
          </span>
        </Link>
      </section>
    </AppShell>
  )
}
