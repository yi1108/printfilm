import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import AppShell from '../components/layout/AppShell'
import UserAvatar from '../components/UserAvatar'
import { api, type User, type Wallet } from '../api'
import { dramaApi, type DramaProjectListItem } from '../api/drama'
import MonthlyUsageCard from '../components/billing/MonthlyUsageCard'
import UsageChargeRecords from '../components/billing/UsageChargeRecords'
import ApiKeysPanel from './settings/ApiKeysPanel'
import AccountProfileCard from './settings/AccountProfileCard'
import ChangePasswordCard from './settings/ChangePasswordCard'
import ComingSoon from '../components/ui/ComingSoon'
import { dramaProjectEntryPath, formatDramaCardMeta } from '../lib/dramaWorkflow'
import { STATUS_CN } from '../lib/status'
import SettingsToolRunsPanel from './SettingsToolRunsPanel'
import { formatDateTime, useI18n } from '../i18n'

type SettingsTab =
  | 'account'
  | 'projects'
  | 'kepu'
  | 'tools'
  | 'assets'
  | 'subscription'
  | 'team'
  | 'api'
  | 'notify'
  | 'security'

type KepuItem = {
  id: number
  title: string
  status: string
  updated_at?: string
  created_at: string
}

/*
 * SIDE_ITEMS 侧栏导航项
 * TAB_IDS 合法 tab 集合（用于 URL 校验）
 */
const SIDE_ITEMS: { id: SettingsTab; soon?: boolean; group?: 'work' | 'account' }[] = [
  { id: 'account', group: 'account' },
  { id: 'projects', group: 'work' },
  { id: 'kepu', group: 'work' },
  { id: 'tools', group: 'work' },
  { id: 'assets', group: 'work' },
  { id: 'subscription', group: 'account' },
  { id: 'team', soon: true, group: 'account' },
  { id: 'api', group: 'account' },
  { id: 'notify', soon: true, group: 'account' },
  { id: 'security', group: 'account' },
]

const TAB_IDS = new Set(SIDE_ITEMS.map((i) => i.id))

// 解析 URL tab，非法时回落到账号信息
function parseTab(raw: string | null): SettingsTab {
  if (raw && TAB_IDS.has(raw as SettingsTab)) return raw as SettingsTab
  return 'account'
}

// 格式化相对时间展示
function formatWhen(iso: string | undefined, locale: 'zh' | 'en') {
  return formatDateTime(iso, locale)
}

export default function SettingsPage() {
  const nav = useNavigate()
  const { t, locale } = useI18n()
  const [params, setParams] = useSearchParams()
  /*
   * tab 当前侧栏分区
   * user 当前登录用户
   * wallet 钱包余额
   * dramaItems 最近漫剧项目
   * kepuItems 最近科普项目
   * listError 列表加载错误
   * listLoading 列表加载中
   */
  const [tab, setTab] = useState<SettingsTab>(() => parseTab(params.get('tab')))
  const [user, setUser] = useState<User | null>(null)
  const [wallet, setWallet] = useState<Wallet | null>(null)
  const [dramaItems, setDramaItems] = useState<DramaProjectListItem[]>([])
  const [kepuItems, setKepuItems] = useState<KepuItem[]>([])
  const [listError, setListError] = useState('')
  const [listLoading, setListLoading] = useState(false)

  useEffect(() => {
    if (!localStorage.getItem('token')) {
      nav('/auth')
      return
    }
    api
      .me()
      .then(setUser)
      .catch(() => {
        localStorage.removeItem('token')
        nav('/auth')
      })
    api.wallet().then(setWallet).catch(() => undefined)
  }, [nav])

  useEffect(() => {
    const next = parseTab(params.get('tab'))
    setTab(next)
  }, [params])

  useEffect(() => {
    if (tab !== 'projects' && tab !== 'kepu') return
    let cancelled = false
    setListLoading(true)
    setListError('')
    const load = async () => {
      try {
        if (tab === 'projects') {
          const rows = await dramaApi.listProjects()
          if (!cancelled) setDramaItems(rows.slice(0, 8))
        } else {
          const res = await api.listProjects({ page: 1, page_size: 8 })
          if (!cancelled) setKepuItems(res.items)
        }
      } catch (e) {
        if (!cancelled) setListError(e instanceof Error ? e.message : t('common.loadFailed'))
      } finally {
        if (!cancelled) setListLoading(false)
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [tab])

  // 切换侧栏并同步到 URL
  function selectTab(next: SettingsTab) {
    setTab(next)
    const sp = new URLSearchParams(params)
    if (next === 'account') sp.delete('tab')
    else sp.set('tab', next)
    setParams(sp, { replace: true })
  }

  function logout() {
    localStorage.removeItem('token')
    nav('/')
  }

  return (
    <AppShell>
      <div className="pf-settings">
        <aside className="pf-settings-side">
          <div className="pf-settings-profile">
            <UserAvatar user={user} size="lg" className="pf-settings-avatar" />
            <div>
              <strong>{user?.nickname || t('common.creator')}</strong>
              <p className="pf-muted">ID: {user?.id ?? '—'}</p>
            </div>
          </div>
          <nav className="pf-settings-nav" aria-label={t('settings.nav')}>
            {SIDE_ITEMS.map((item) => (
              <button
                key={item.id}
                type="button"
                className={tab === item.id ? 'active' : ''}
                onClick={() => selectTab(item.id)}
              >
                {t(`settings.tabs.${item.id}`)}
                {item.soon ? <ComingSoon /> : null}
              </button>
            ))}
          </nav>
          <button type="button" className="pf-btn pf-btn-ghost pf-btn-sm pf-settings-logout" onClick={logout}>
            {t('settings.logout')}
          </button>
        </aside>

        <main className="pf-settings-main">
          {tab === 'account' ? <AccountProfileCard user={user} onUserChange={setUser} /> : null}

          {tab === 'projects' ? (
            <section className="pf-settings-card">
              <div className="pf-settings-card-head">
                <div>
                  <h1>{t('settings.tabs.projects')}</h1>
                  <p className="pf-muted">{t('settings.dramaLead')}</p>
                </div>
                <div className="pf-settings-actions">
                  <Link className="pf-btn pf-btn-lime pf-btn-sm" to="/drama">
                    {t('settings.allProjects')}
                  </Link>
                  <Link className="pf-btn pf-btn-ghost pf-btn-sm" to="/drama">
                    {t('settings.newDrama')}
                  </Link>
                </div>
              </div>
              {listLoading ? <p className="pf-muted">{t('common.loading')}</p> : null}
              {listError ? <p className="pf-error">{listError}</p> : null}
              {!listLoading && !listError && dramaItems.length === 0 ? (
                <div className="pf-settings-empty">
                  <p>{t('settings.noDrama')}</p>
                  <Link className="pf-btn pf-btn-lime pf-btn-sm" to="/drama">
                    {t('settings.goCreate')}
                  </Link>
                </div>
              ) : null}
              {dramaItems.length > 0 ? (
                <ul className="pf-settings-list">
                  {dramaItems.map((item) => (
                    <li key={item.id}>
                      <Link to={dramaProjectEntryPath(item)} className="pf-settings-list-row">
                        <span className="pf-settings-list-main">
                          <strong>{item.title || t('settings.projectFallback', { id: item.id })}</strong>
                          <em className="pf-muted">{formatDramaCardMeta(item)}</em>
                        </span>
                        <span className="pf-settings-list-meta pf-muted">
                          {formatWhen(item.updated_at || item.created_at, locale)}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : null}
            </section>
          ) : null}

          {tab === 'kepu' ? (
            <section className="pf-settings-card">
              <div className="pf-settings-card-head">
                <div>
                  <h1>{t('settings.tabs.kepu')}</h1>
                  <p className="pf-muted">{t('settings.kepuLead')}</p>
                </div>
                <div className="pf-settings-actions">
                  <Link className="pf-btn pf-btn-lime pf-btn-sm" to="/history">
                    {t('settings.allHistory')}
                  </Link>
                  <Link className="pf-btn pf-btn-ghost pf-btn-sm" to="/studio/new">
                    {t('settings.newKepu')}
                  </Link>
                </div>
              </div>
              {listLoading ? <p className="pf-muted">{t('common.loading')}</p> : null}
              {listError ? <p className="pf-error">{listError}</p> : null}
              {!listLoading && !listError && kepuItems.length === 0 ? (
                <div className="pf-settings-empty">
                  <p>{t('settings.noKepu')}</p>
                  <Link className="pf-btn pf-btn-lime pf-btn-sm" to="/studio/new">
                    {t('settings.goCreate')}
                  </Link>
                </div>
              ) : null}
              {kepuItems.length > 0 ? (
                <ul className="pf-settings-list">
                  {kepuItems.map((item) => (
                    <li key={item.id}>
                      <Link to={`/studio/${item.id}`} className="pf-settings-list-row">
                        <span className="pf-settings-list-main">
                          <strong>{item.title || t('settings.projectFallback', { id: item.id })}</strong>
                          <em className="pf-muted">{STATUS_CN[item.status] || item.status}</em>
                        </span>
                        <span className="pf-settings-list-meta pf-muted">
                          {formatWhen(item.updated_at || item.created_at, locale)}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : null}
            </section>
          ) : null}

          {tab === 'tools' ? <SettingsToolRunsPanel /> : null}

          {tab === 'assets' ? (
            <section className="pf-settings-card">
              <h1>{t('settings.tabs.assets')}</h1>
              <p className="pf-muted">{t('settings.assetsLead')}</p>
              <div className="pf-settings-actions">
                <Link className="pf-btn pf-btn-lime pf-btn-sm" to="/assets">
                  {t('settings.openAssets')}
                </Link>
                <Link className="pf-btn pf-btn-ghost pf-btn-sm" to="/drama">
                  {t('settings.tabs.projects')}
                </Link>
                <Link className="pf-btn pf-btn-ghost pf-btn-sm" to="/history">
                  {t('settings.tabs.kepu')}
                </Link>
              </div>
            </section>
          ) : null}

          {tab === 'subscription' ? (
            <section className="pf-settings-card">
              <h1>{t('settings.tabs.subscription')}</h1>
              <p className="pf-muted">{t('settings.subLead')}</p>
              <div className="pf-settings-balance">
                <div>
                  <span className="pf-muted">{t('settings.balance')}</span>
                  <strong>¥{(wallet?.balance_yuan ?? 0).toFixed(2)}</strong>
                </div>
                <div>
                  <span className="pf-muted">{t('settings.frozen')}</span>
                  <em>¥{(wallet?.frozen_yuan ?? 0).toFixed(2)}</em>
                </div>
              </div>
              <MonthlyUsageCard variant="compact" showTopup={false} />
              <UsageChargeRecords variant="compact" />
              <div className="pf-settings-actions">
                <Link className="pf-btn pf-btn-lime pf-btn-sm" to="/pricing">
                  {t('settings.goTopup')}
                </Link>
              </div>
            </section>
          ) : null}

          {tab === 'security' ? <ChangePasswordCard email={user?.email || ''} /> : null}

          {tab === 'api' ? <ApiKeysPanel /> : null}

          {tab === 'team' || tab === 'notify' ? (
            <section className="pf-settings-card">
              <h1>{t(`settings.tabs.${tab}`)}</h1>
              <p className="pf-muted">{t('settings.soonModule')}</p>
              <ComingSoon />
            </section>
          ) : null}
        </main>
      </div>
    </AppShell>
  )
}
