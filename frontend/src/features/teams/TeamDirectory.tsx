import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowUpRight, Clapperboard, Plus, UsersRound } from 'lucide-react'
import Button from '../../components/ui/Button'
import { CreateTeamModal } from './TeamForms'
import { useTeamPreview } from './useTeamPreview'
import { teamsApi } from '../../api/teams'
import { useTeamPage } from './useTeamPage'
import { TeamPagination } from './TeamPagination'
import { TEAM_ROLE_LABELS, viewerRole } from './types'

/** 团队目录同时用于独立入口和个人设置里的团队管理。 */
export default function TeamDirectory({ compact = false }: { compact?: boolean }) {
  const { revision } = useTeamPreview()
  const [page, setPage] = useState(1)
  const listing = useTeamPage(`directory:${page}`, (signal) => teamsApi.list({ page, page_size: 12 }, signal), revision)
  const teams = listing.items
  /* createOpen 团队创建表单的显示状态。 */
  const [createOpen, setCreateOpen] = useState(false)

  return <div className={`pf-team-directory${compact ? ' pf-team-directory--compact' : ''}`}>
    <div className="pf-team-directory-heading"><div><span className="pf-team-eyebrow">CREATE TOGETHER</span><h1>{compact ? '我的团队' : '一个团队，一起出片。'}</h1><p className="pf-team-muted">把项目、伙伴和创作资产放在一起，让每一份灵感都有接力。</p></div><Button variant="lime" onClick={() => setCreateOpen(true)}><Plus size={17} />创建团队</Button></div>
    {listing.loading && <p role="status" className="pf-team-muted">正在加载团队…</p>}
    {listing.error && <div className="pf-team-alert" role="alert">{listing.error}<Button onClick={listing.retry}>重试</Button></div>}
    <div className="pf-team-directory-grid">
      {teams.map((team) => <Link key={team.id} to={`/teams/${team.id}`} className="pf-team-directory-card">
        <div className="pf-team-directory-card-top"><span className="pf-team-mark" style={{ background: team.color }}>{team.name.slice(0, 1)}</span><span className="pf-team-tag">{TEAM_ROLE_LABELS[viewerRole(team)]}</span></div>
        <h2>{team.name}</h2><p>{team.description || '新的故事，从这里开始。'}</p>
        <div className="pf-team-directory-counts"><span><UsersRound size={15} />{team.memberCount} 位成员</span><span><Clapperboard size={15} />{team.projectCount} 个项目</span></div>
        <div className="pf-team-directory-card-bottom"><div className="pf-team-avatar-stack">{team.members.slice(0, 4).map((member) => <span key={member.id} className="pf-team-avatar" style={{ background: member.color }} title={member.name}>{member.name.slice(0, 1)}</span>)}</div><span>进入团队 <ArrowUpRight size={16} /></span></div>
      </Link>)}
      <button type="button" className="pf-team-directory-new" onClick={() => setCreateOpen(true)}><span><Plus size={25} /></span><strong>组建你的创作团队</strong><p>邀请伙伴，从第一个故事开始</p></button>
    </div>
    <TeamPagination page={page} total={listing.meta.total} onChange={setPage} />
    {!compact && <div className="pf-team-directory-foot"><UsersRound size={20} /><p><strong>个人创作与团队协作，自由切换。</strong><br />个人项目保持私有，团队项目由所有伙伴共同完成。团队消费由所有者个人积分支付。</p></div>}
    <CreateTeamModal open={createOpen} onClose={() => setCreateOpen(false)} />
  </div>
}
