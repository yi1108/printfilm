import { points, parsePoints } from '../../lib/points'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { CreditCard, LockKeyhole, Search, Wallet } from 'lucide-react'
import Button from '../../components/ui/Button'
import Modal from '../../components/ui/Modal'
import { teamsApi } from '../../api/teams'
import { useTeamPreview } from './useTeamPreview'
import { useTeamPage } from './useTeamPage'
import { TeamPagination } from './TeamPagination'
import type { Team, TeamRole, UsageSummary } from './types'
import './team-management.css'

/** 金额以人民币元展示。 */
const money = points
/** 所有者付款、两级消费上限及真实用量明细。 */
export default function TeamBillingPanel({ team, role }: { team: Team; role: TeamRole }) {
  /* 查询条件全部传给服务端；summary 账户/用量；limit 月上限；busy/error 操作反馈。 */
  const [search, setSearch] = useState('')
  const [member, setMember] = useState('')
  const [project, setProject] = useState('')
  const [period, setPeriod] = useState('')
  const [page, setPage] = useState(1)
  const [summary, setSummary] = useState<UsageSummary | undefined>(team.usage)
  const [budgetOpen, setBudgetOpen] = useState(false)
  const [limit, setLimit] = useState('')
  const [unlimited, setUnlimited] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  const { loadTeam } = useTeamPreview()
  const isOwner = role === 'owner'
  const listing = useTeamPage(`${team.id}:charges:${page}:${search}:${member}:${project}:${period}`, (signal) => teamsApi.charges(team.id, { page, page_size: 12, q: search, member_id: isOwner && member ? member : undefined, project_id: project || undefined, period: period || undefined }, signal), refresh)
  useEffect(() => { let active = true; void teamsApi.summary(team.id).then((data) => { if (active) setSummary(data) }).catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : '用量加载失败') }); return () => { active = false } }, [team.id, refresh])
  /** 打开编辑器，空值不限额；零额度停止新的付费任务。 */
  function openBudget() { setLimit(String(summary?.team_monthly_limit_fen ?? 0)); setUnlimited(summary?.team_monthly_limit_fen == null); setError(''); setBudgetOpen(true) }
  /** 金额精确转为分后提交真实接口，已消费和在途任务保留。 */
  async function saveBudget() {
    if (busy || !isOwner) return
    if (!unlimited && parsePoints(limit, 100000000) === null) { setError('请输入不超过 100,000,000 的整数积分'); return }
    const value = unlimited ? null : parsePoints(limit, 100000000)
    if (value !== null && (!Number.isSafeInteger(value) || value > 100000000)) { setError('额度不得超过 100,000,000 积分'); return }
    setBusy(true); setError('')
    try { await teamsApi.update(team.id, { monthly_limit_fen: value }); setBudgetOpen(false); setRefresh((n) => n + 1); await loadTeam(team.id) }
    catch (cause) { setError(cause instanceof Error ? cause.message : '额度保存失败') }
    finally { setBusy(false) }
  }
  return <div className="pf-team-billing"><div className="pf-team-billing-summary"><section className="pf-team-billing-wallet"><div className="pf-team-billing-wallet-top"><span><Wallet size={17} />{isOwner ? '所有者个人账户' : '我的本月消费'}</span><span className="pf-team-billing-wallet-badge">{isOwner ? '团队费用由此支付' : '仅本人可见'}</span></div><div className="pf-team-billing-wallet-amount"><span>{isOwner ? '可用积分' : '已结算消费'}</span><strong>{summary ? money(isOwner ? summary.balance_fen ?? 0 : summary.spent_fen) : '—'}</strong></div><div className="pf-team-billing-wallet-bottom"><span><LockKeyhole size={13} />{isOwner ? '任务冻结' : '在途预留'} <strong>{summary ? money(isOwner ? summary.frozen_fen ?? 0 : summary.reserved_fen) : '—'}</strong></span>{isOwner && <Button variant="lime" size="sm" disabled={busy || !summary} onClick={openBudget}>设置总上限</Button>}</div><div className="pf-team-billing-wallet-pattern" aria-hidden="true">P/F</div></section><section className="pf-team-panel pf-team-billing-stat"><span className="pf-team-muted">{isOwner ? '团队本月消费' : '我的月度额度'}</span><strong>{summary ? isOwner ? money(summary.spent_fen) : summary.monthly_limit_fen === null ? '不限额' : money(summary.monthly_limit_fen) : '—'}</strong><p>{summary?.period || '正在读取统计'}</p></section><section className="pf-team-panel pf-team-billing-stat"><span className="pf-team-muted">{isOwner ? '团队月度上限' : '我的在途预留'}</span><strong>{isOwner ? summary?.team_monthly_limit_fen == null ? '不限额' : money(summary.team_monthly_limit_fen) : summary ? money(summary.reserved_fen) : '—'}</strong><p>{isOwner ? summary ? '已预留 ' + money(summary.reserved_fen) : '在成员管理中设置个人上限' : '任务完成后按实际用量结算'}</p></section></div><div className="pf-team-billing-info"><p>{isOwner ? '团队消费直接扣除你的个人积分，记录实际操作成员；总上限与成员上限同时生效。' : '团队费用由所有者个人积分支付。你可查看自己的消费及额度。'}{summary && !summary.billing_enabled && ' 当前未启用计费，不产生扣款。'}</p>{isOwner && <Link className="pf-link" to="/pricing">个人账户充值 →</Link>}</div>{error && <div className="pf-team-alert" role="alert">{error}</div>}
    <section className="pf-team-panel"><div className="pf-team-section-head"><h2>{isOwner ? '团队消费明细' : '我的消费明细'}</h2><span className="pf-team-tag">积分</span></div><div className="pf-team-billing-toolbar"><label className="pf-team-billing-search"><Search size={16} /><input aria-label="搜索消费" value={search} onChange={(event) => { setSearch(event.target.value); setPage(1) }} placeholder="搜索内容或模型" /></label>{isOwner && <label className="pf-team-field">成员 ID<input inputMode="numeric" value={member} onChange={(event) => { setMember(event.target.value); setPage(1) }} placeholder="全部成员" /></label>}<label className="pf-team-field">项目 ID<input inputMode="numeric" value={project} onChange={(event) => { setProject(event.target.value); setPage(1) }} placeholder="全部项目" /></label><label className="pf-team-field">月份<input type="month" value={period} onChange={(event) => { setPeriod(event.target.value); setPage(1) }} /></label></div>{listing.loading ? <p role="status">正在加载消费明细…</p> : listing.error ? <div className="pf-team-alert" role="alert">{listing.error}<Button onClick={listing.retry}>重试</Button></div> : listing.items.length ? <div className="pf-team-table-wrap"><table className="pf-team-table"><thead><tr><th>创作内容</th>{isOwner && <th>成员</th>}<th>项目</th><th>时间</th><th>消耗积分</th></tr></thead><tbody>{listing.items.map((charge) => <tr key={charge.id}><td><div className="pf-team-billing-charge"><CreditCard size={17} /><div><strong>{charge.label}</strong><small>{charge.model}</small></div></div></td>{isOwner && <td>{team.members.find((m) => m.id === charge.memberId)?.name || `成员 #${charge.memberId}`}</td>}<td>#{charge.projectId}</td><td>{new Date(charge.createdAt).toLocaleString('zh-CN')}</td><td>{money(charge.amountFen)}</td></tr>)}</tbody></table></div> : <div className="pf-team-empty">暂无符合条件的消费记录。</div>}<TeamPagination page={page} total={listing.meta.total} onChange={setPage} /></section>
    <Modal open={budgetOpen && isOwner} onClose={() => setBudgetOpen(false)} dismissible={!busy} title="团队月度消费上限"><div className="pf-team-form"><p>按上海时区自然月统计，已消费与在途预留共同占用额度。0 积分停止新消费，降低上限不会取消已受理任务。</p><label><input type="checkbox" checked={unlimited} disabled={busy} onChange={(event) => setUnlimited(event.target.checked)} /> 不限额</label><label className="pf-team-field">每月上限（积分）<input inputMode="numeric" disabled={unlimited || busy} value={limit} onChange={(event) => setLimit(event.target.value)} /></label>{error && <p className="pf-team-alert" role="alert">{error}</p>}<Button variant="lime" onClick={saveBudget} disabled={busy}>{busy ? '正在保存…' : '保存消费上限'}</Button></div></Modal>
  </div>
}
