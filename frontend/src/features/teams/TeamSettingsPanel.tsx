import { useState, type FormEvent } from 'react'
import { ArrowRightLeft, Check, LogOut, ShieldCheck, Trash2 } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import Button from '../../components/ui/Button'
import { dialog } from '../../lib/dialog'
import { useTeamPreview } from './useTeamPreview'
import { teamsApi } from '../../api/teams'
import { useTeamPage } from './useTeamPage'
import { TeamPagination } from './TeamPagination'
import { TEAM_COLORS, type PreviewTeam, type TeamRole } from './types'

/** 团队资料与所有权管理；真实权限仍需后续服务端校验。 */
export default function TeamSettingsPanel({ team, role }: { team: PreviewTeam; role: TeamRole }) {
  const { updateTeam, transferOwnership, leaveTeam, deleteTeam } = useTeamPreview()
  const navigate = useNavigate()
  /* name/description/color 编辑草稿；success/error 提交反馈；target 所有权转让对象。 */
  const [name, setName] = useState(team.name)
  const [description, setDescription] = useState(team.description)
  const [color, setColor] = useState(team.color)
  const [target, setTarget] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [success, setSuccess] = useState(false)
  const [error, setError] = useState('')
  const [memberQuery, setMemberQuery] = useState('')
  const [memberPage, setMemberPage] = useState(1)
  const candidates = useTeamPage(`${team.id}:owner-candidates:${memberQuery}:${memberPage}`, (signal) => role === 'owner' ? teamsApi.members(team.id, { page: memberPage, page_size: 12, q: memberQuery }, signal) : Promise.resolve({ items: [], meta: { total: 0, page: 1, page_size: 12 } }))

  /** 保存资料并在页面内给出可感知反馈。 */
  async function save(event: FormEvent) {
    event.preventDefault()
    try { await updateTeam(team.id, { name, description, color }); setSuccess(true); setError('') }
    catch (cause) { setError(cause instanceof Error ? cause.message : '保存失败') }
  }

  /** 转让前明确说明权限变化。 */
  async function transfer() {
    const member = candidates.items.find((item) => item.id === target)
    if (!member) { setError('请选择接收所有权的成员'); return }
    if (!await dialog.confirm({ title: '转让团队所有权', message: `将团队交给 ${member.name} 后，你将成为管理员，无法再管理资金和任免管理员。新任务将扣除新所有者的个人积分，已受理任务仍由原付款所有者结算。转让后无法自行恢复所有权。`, confirmText: '确认转让', tone: 'danger' })) return
    try { await transferOwnership(team.id, target); setTarget(''); setError(''); setSuccess(false) }
    catch (cause) { setError(cause instanceof Error ? cause.message : '转让失败') }
  }

  /** 成员退出撤销真实团队访问，保留团队项目与账单。 */
  async function leave() {
    if (!await dialog.confirm({ title: '退出团队', message: `退出「${team.name}」后，你将无法访问这个团队；团队内容仍然保留。重新加入需要邀请。`, confirmText: '退出团队', tone: 'danger' })) return
    try { await leaveTeam(team.id); navigate('/teams') }
    catch (cause) { setError(cause instanceof Error ? cause.message : '退出失败') }
  }

  async function removeTeam() {
    if (deleting) return
    if (!await dialog.confirm({ title: '删除团队', message: `确定删除「${team.name}」？所有成员将失去访问权限，未使用的邀请立即失效。历史作品和消费记录仅保留归档，无法通过团队页面访问。此操作无法自行恢复。`, confirmText: '确认删除团队', tone: 'danger' })) return
    setDeleting(true); setError('')
    try { await deleteTeam(team.id); navigate('/teams', { replace: true }) }
    catch (cause) { setError(cause instanceof Error ? cause.message : '删除失败') }
    finally { setDeleting(false) }
  }

  return <div className="pf-team-settings-grid">
    <section className="pf-team-panel"><div className="pf-team-section-head"><div><h2>团队资料</h2><p>一个清晰的名字，让伙伴更容易找到彼此。</p></div><ShieldCheck size={21} /></div>
      <form className="pf-team-form" onSubmit={save}>
        <div className="pf-team-form-intro"><span className="pf-team-mark" style={{ background: color }}>{name.slice(0, 1) || '团'}</span><div><strong>{team.name}</strong><p>{team.memberCount} 位成员 · 团队空间</p></div></div>
        <label className="pf-team-field">团队名称<input value={name} onChange={(event) => { setName(event.target.value); setSuccess(false) }} maxLength={40} required readOnly={role !== 'owner'} /></label>
        <label className="pf-team-field">团队介绍<textarea value={description} onChange={(event) => { setDescription(event.target.value); setSuccess(false) }} rows={3} maxLength={180} readOnly={role !== 'owner'} /></label>
        <fieldset className="pf-team-colors" disabled={role !== 'owner'}><legend>标识颜色</legend>{TEAM_COLORS.map((item, index) => <button type="button" key={item} style={{ background: item }} aria-label={`选择标识颜色 ${index + 1}`} aria-pressed={color === item} disabled={role !== 'owner'} onClick={() => { setColor(item); setSuccess(false) }}>{color === item && <Check size={16} />}</button>)}</fieldset>
        {role === 'owner' ? <div><Button type="submit" variant="dark">保存修改</Button>{success && <span className="pf-team-saved" role="status"><Check size={15} />资料已保存</span>}</div> : <p className="pf-team-form-note">团队资料由所有者管理。</p>}
      </form>
    </section>
    <div className="pf-team-settings-aside"><section className="pf-team-panel"><div className="pf-team-section-head"><div><h2>协作约定</h2><p>让创作有秩序，也有空间。</p></div></div><ul className="pf-team-rules"><li><strong>团队共同拥有作品</strong><span>成员退出后，项目和资产继续留在团队。</span></li><li><strong>分工制作，避免覆盖</strong><span>不同分集可并行，同一内容由一位伙伴编辑。</span></li><li><strong>资产复制后独立修改</strong><span>其他项目的调整不会改变当前项目资产。</span></li><li><strong>所有者个人积分支付费用</strong><span>月度额度按预估拦截，按实际费用结算。</span></li></ul><p className="pf-team-form-note">协作编辑占用由服务端校验；任务完成后按实际用量结算。</p></section>
      <section className="pf-team-panel pf-team-settings-access"><h2>{role === 'owner' ? '转让所有权' : '退出团队'}</h2><p className="pf-team-muted">{role === 'owner' ? '把团队交给另一位伙伴，你将成为管理员。' : '退出后，你的创作内容仍归团队所有。'}</p>{role === 'owner' ? <><label className="pf-team-field">搜索接收成员<input value={memberQuery} onChange={(event) => { setMemberQuery(event.target.value); setMemberPage(1); setTarget('') }} placeholder="输入成员姓名或邮箱" /></label>{candidates.error && <p role="alert">{candidates.error}</p>}<label className="pf-team-field">接收成员<select value={target} onChange={(event) => setTarget(event.target.value)}><option value="">选择一位成员</option>{candidates.items.filter((member) => member.id !== team.viewerId).map((member) => <option key={member.id} value={member.id}>{member.name}</option>)}</select></label><TeamPagination page={memberPage} total={candidates.meta.total} onChange={(page) => { setMemberPage(page); setTarget('') }} /><Button onClick={transfer} disabled={!target}><ArrowRightLeft size={15} />转让所有权</Button></> : <Button onClick={leave}><LogOut size={15} />退出团队</Button>}</section>
      {role === 'owner' && <section className="pf-team-panel pf-team-settings-access"><h2>删除团队</h2><p className="pf-team-muted">删除后所有成员将无法访问团队。历史作品与消费记录保留归档，此操作无法自行恢复。</p><Button disabled={deleting} onClick={() => void removeTeam()}><Trash2 size={15} />{deleting ? '正在删除…' : '删除团队'}</Button></section>}
    </div>
    {error && <p className="pf-team-alert" role="alert">{error}</p>}
  </div>
}
