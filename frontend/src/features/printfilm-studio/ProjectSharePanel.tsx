import { useEffect, useState } from 'react'
import { Check, Copy, Link, UserPlus } from 'lucide-react'
import { WorkspaceDialog } from './WorkspacePanels'
import { projectSharingApi, type ProjectSharing } from './projectSharing'

export function SharePanel({ projectId, onClose }: { projectId: number; onClose: () => void }) {
  const [data, setData] = useState<ProjectSharing>()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [days, setDays] = useState(7)
  const [created, setCreated] = useState<{ id: string; url: string }>()
  const [copied, setCopied] = useState('')
  const [removing, setRemoving] = useState<number>()
  const projectUrl = `${location.origin}/drama/projects/${projectId}/canvas`
  useEffect(() => {
    let active = true
    void projectSharingApi.get(projectId).then(value => { if (active) setData(value) }).catch(cause => { if (active) setError(cause.message) })
    return () => { active = false }
  }, [projectId])
  async function refresh() { setData(await projectSharingApi.get(projectId)) }
  async function run(action: () => Promise<void>) {
    setBusy(true); setError('')
    try { await action(); await refresh() } catch (cause) { setError(cause instanceof Error ? cause.message : '操作失败，请重试') } finally { setBusy(false) }
  }
  async function copy(url: string) {
    try { await navigator.clipboard.writeText(url); setCopied(url) } catch { setError('复制失败，请选中链接手动复制') }
  }
  return <WorkspaceDialog title="项目团队与分享" onClose={onClose}>
    <div className="pf-share-heading"><div><h3>项目链接</h3><p className="pf-muted">已加入本项目的成员登录后可打开画布</p></div><button onClick={() => void copy(projectUrl)}>{copied === projectUrl ? <Check size={16} /> : <Copy size={16} />}复制链接</button></div>
    <input aria-label="项目链接" readOnly value={projectUrl} />
    <p className="pf-panel-note">每个项目独立组队，成员权限仅限本项目画布。图片、视频、音频和 AI 写作费用均从点击生成者的个人余额扣除。</p>
    {!data && !error && <p role="status">正在加载项目成员…</p>}
    {data?.is_owner && <section className="pf-invite-card">
      <h3><UserPlus size={17} /> 邀请加入项目</h3>
      <p>获得邀请链接的人可在登录后加入本项目并编辑画布。</p>
      <div className="pf-share-heading"><label>链接有效期 <select aria-label="邀请链接有效期" value={days} onChange={event => setDays(Number(event.target.value))}><option value={1}>1 天</option><option value={7}>7 天</option><option value={30}>30 天</option></select></label><button className="pf-primary" disabled={busy} onClick={() => void run(async () => { const invite = await projectSharingApi.invite(projectId, days); setCreated({ id: invite.id, url: `${location.origin}/canvas/join#token=${invite.token}` }); setCopied('') })}><Link size={16} />创建邀请链接</button></div>
      {created && <div><label>新邀请链接<input aria-label="新邀请链接" readOnly value={created.url} /></label><button className="pf-primary" onClick={() => void copy(created.url)}>{copied === created.url ? '已复制' : '复制邀请链接'}</button><p className="pf-muted">请在关闭窗口前复制；之后可撤销链接或创建新链接。</p></div>}
    </section>}
    {data?.is_owner && data.invitations.length > 0 && <section><h3>邀请链接管理</h3><p className="pf-muted">撤销链接会阻止新成员加入；已加入的成员需在下方移除。</p><div className="pf-member-list">{data.invitations.map((invite, index) => <article key={invite.id}><span>邀请链接 {data.invitations.length - index}<small>{new Date(invite.expires_at).toLocaleString()} 到期</small></span><em>{{ active: '有效', expired: '已过期', revoked: '已撤销' }[invite.status]}</em>{invite.status === 'active' && <button disabled={busy} onClick={() => void run(async () => { await projectSharingApi.revoke(projectId, invite.id); if (created?.id === invite.id) setCreated(undefined) })}>撤销</button>}</article>)}</div></section>}
    {data && <section><h3>项目成员 · {data.members.length}</h3><div className="pf-member-list">{data.members.map(member => <article key={member.id}><span className="pf-avatar">{member.name.slice(0, 1)}</span><span>{member.name}</span><em>{member.role === 'owner' ? '所有者' : '协作成员'}</em>{data.is_owner && member.role !== 'owner' && <button disabled={busy} onClick={() => setRemoving(member.id)}>移除</button>}</article>)}</div>{removing !== undefined && <div role="alert" className="pf-invite-card"><p>移除后，该成员将无法访问本项目画布。如需防止再次加入，请同时撤销有效邀请链接。</p><button disabled={busy} className="pf-primary" onClick={() => void run(async () => { await projectSharingApi.remove(projectId, removing); setRemoving(undefined) })}>确认移除</button> <button disabled={busy} onClick={() => setRemoving(undefined)}>取消</button></div>}{!data.is_owner && <p className="pf-muted">邀请链接和成员由项目所有者管理。</p>}</section>}
    {error && <p role="alert">{error}</p>}
  </WorkspaceDialog>
}
