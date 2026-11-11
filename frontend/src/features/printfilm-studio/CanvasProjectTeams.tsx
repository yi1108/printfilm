import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Users, ArrowUpRight } from 'lucide-react'
import { dramaApi, type DramaProjectListItem } from '../../api/drama'
import Pagination from '../../components/ui/Pagination'
import { SharePanel } from './ProjectSharePanel'
import './projectTeams.css'

/** A team is the membership of one canvas project, with no organization wallet. */
export default function CanvasProjectTeams() {
  const [items, setItems] = useState<DramaProjectListItem[]>([])
  const [page, setPage] = useState(1)
  const [total, setTotal] = useState(0)
  const [relation, setRelation] = useState<'all' | 'owned' | 'joined'>('all')
  const [selected, setSelected] = useState<number>()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    let active = true
    setLoading(true); setError('')
    void dramaApi.listProjects({ workflow: 'canvas', relation, page, page_size: 8 }).then(result => {
      if (!active) return
      setItems(result.items); setTotal(result.meta.total); setPage(result.meta.page)
    }).catch(cause => { if (active) setError(cause instanceof Error ? cause.message : '项目加载失败') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [page, relation, retry])
  return <section className="pf-project-teams">
    <header><div><h2>项目团队</h2><p>每个画布项目独立管理成员，通过项目分享邀请伙伴。</p></div><Link className="pf-btn" to="/canvas">我的项目 <ArrowUpRight size={16} /></Link></header>
    <nav aria-label="项目团队分类">{(['all', 'owned', 'joined'] as const).map(value => <button key={value} aria-pressed={value === relation} onClick={() => { setRelation(value); setPage(1) }}>{({ all: '全部项目', owned: '我创建的', joined: '我参与的' })[value]}</button>)}</nav>
    <p className="pf-muted">成员权限仅限所属画布项目。生成费用从发起人的个人余额扣除。</p>
    {loading ? <p role="status">正在加载项目…</p> : error ? <p role="alert">{error} <button onClick={() => setRetry(value => value + 1)}>重试</button></p> : <>
      <div className="pf-project-teams-grid">{items.map(item => <article key={item.id}>
        <Users size={22} /><span>{item.is_owner ? '我创建的' : '我参与的'}</span><h3>{item.title}</h3>
        <footer><Link to={`/drama/projects/${item.id}/canvas`}>打开画布</Link><button onClick={() => setSelected(item.id)}>{item.is_owner ? '管理成员与邀请' : '查看项目成员'}</button></footer>
      </article>)}</div>
      {!items.length && <p>暂无此类项目。创建画布项目或接受项目邀请后，将显示在这里。</p>}
      <Pagination page={page} pageCount={Math.max(1, Math.ceil(total / 8))} total={total} pageSize={8} onChange={setPage} />
    </>}
    {selected !== undefined && <SharePanel projectId={selected} onClose={() => setSelected(undefined)} />}
  </section>
}
