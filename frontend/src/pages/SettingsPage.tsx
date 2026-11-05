import { points, pointText } from '../lib/points'
import { useEffect, useState } from 'react'
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import AppShell from '../components/layout/AppShell'
import UserAvatar from '../components/UserAvatar'
import { api, type User, type Wallet } from '../api'
import MonthlyUsageCard from '../components/billing/MonthlyUsageCard'
import UsageChargeRecords from '../components/billing/UsageChargeRecords'
import AccountProfileCard from './settings/AccountProfileCard'
import ChangePasswordCard from './settings/ChangePasswordCard'
import ComingSoon from '../components/ui/ComingSoon'
import { useI18n } from '../i18n'
import TeamDirectory from '../features/teams/TeamDirectory'
import { USER_UPDATED_EVENT } from '../lib/userEvents'

type SettingsTab = 'account' | 'subscription' | 'team' | 'notify' | 'security'

/* 侧栏只保留账户设置；余额与账单通过头像菜单独立进入。 */
const SIDE_ITEMS: { id: Exclude<SettingsTab, 'subscription'>; soon?: boolean }[] = [
  { id: 'account' },
  { id: 'team' },
  { id: 'notify', soon: true },
  { id: 'security' },
]
const TAB_IDS = new Set<string>([...SIDE_ITEMS.map((item) => item.id), 'subscription'])
const LEGACY_TAB_PATHS = new Map([
  ['projects', '/drama'],
  ['kepu', '/history'],
  ['tools', '/tasks'],
  ['assets', '/assets'],
])

/** 解析账户分区，保留头像余额入口，未知 tab 回落到账号信息。 */
function parseTab(raw: string | null): SettingsTab {
  return raw && TAB_IDS.has(raw) ? raw as SettingsTab : 'account'
}

/** 旧项目与记录分区直接转到统一页面，不再加载重复列表。 */
export default function SettingsPage() {
  const [params] = useSearchParams()
  const legacyPath = LEGACY_TAB_PATHS.get(params.get('tab') || '')
  return legacyPath ? <Navigate to={legacyPath} replace /> : <AccountSettings />
}

/** 个人中心维护账户资料、安全和团队设置，账单保留专用直达视图。 */
function AccountSettings() {
  const nav = useNavigate()
  const { t } = useI18n()
  const [params, setParams] = useSearchParams()
  /* tab 由地址决定；user 当前账户；wallet 为账单直达视图提供余额。 */
  const tab = parseTab(params.get('tab'))
  const [user, setUser] = useState<User | null>(null)
  const [wallet, setWallet] = useState<Wallet | null>(null)

  useEffect(() => {
    if (!localStorage.getItem('token')) {
      nav('/auth')
      return
    }
    api.me().then(setUser).catch(() => {
      localStorage.removeItem('token')
      nav('/auth')
    })
  }, [nav])

  useEffect(() => {
    if (tab !== 'subscription' || !localStorage.getItem('token')) return
    let active = true
    api.wallet().then((value) => { if (active) setWallet(value) }).catch(() => undefined)
    return () => { active = false }
  }, [tab])

  /** 切换账户分区并同步到 URL。 */
  function selectTab(next: SettingsTab) {
    const sp = new URLSearchParams(params)
    if (next === 'account') sp.delete('tab')
    else sp.set('tab', next)
    setParams(sp, { replace: true })
  }

  /** 退出后同步所有会话订阅者并回到首页。 */
  function logout() {
    localStorage.removeItem('token')
    window.dispatchEvent(new Event(USER_UPDATED_EVENT))
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
              <button key={item.id} type="button" className={tab === item.id ? 'active' : ''} onClick={() => selectTab(item.id)}>
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

          {tab === 'subscription' ? (
            <section className="pf-settings-card">
              <h1>{t('nav.balanceBilling')}</h1>
              <p className="pf-muted">{t('settings.subLead')}</p>
              <div className="pf-settings-balance">
                <div><span className="pf-muted">{t('settings.balance')}</span><strong>{points(wallet?.balance_fen)}</strong></div>
                <div><span className="pf-muted">{t('settings.frozen')}</span><em>{points(wallet?.frozen_fen)}</em></div>
                {wallet?.debt_fen !== undefined && <div><span>{pointText('欠费', 'Debt')}</span><em>{points(wallet.debt_fen)}</em></div>}
                {wallet?.spendable_fen !== undefined && <div><span>{pointText('实际可消费', 'Spendable')}</span><em>{points(wallet.spendable_fen)}</em></div>}
              </div>
              <MonthlyUsageCard variant="compact" showTopup={false} />
              <UsageChargeRecords variant="compact" />
              <div className="pf-settings-actions"><Link className="pf-btn pf-btn-lime pf-btn-sm" to="/pricing">{t('settings.goTopup')}</Link></div>
            </section>
          ) : null}

          {tab === 'security' ? <ChangePasswordCard email={user?.email || ''} /> : null}
          {tab === 'team' ? <TeamDirectory compact /> : null}
          {tab === 'notify' ? (
            <section className="pf-settings-card">
              <h1>{t('settings.tabs.notify')}</h1>
              <p className="pf-muted">{t('settings.soonModule')}</p>
              <ComingSoon />
            </section>
          ) : null}
        </main>
      </div>
    </AppShell>
  )
}
