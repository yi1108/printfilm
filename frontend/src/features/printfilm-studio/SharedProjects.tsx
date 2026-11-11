import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { projectSharingApi } from './projectSharing'

export default function SharedProjects() {
  const [items, setItems] = useState<{ id: number; title: string }[]>([])
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    void projectSharingApi.shared().then(result => { if (active) setItems(result.items) }).catch(cause => { if (active) setError(cause.message) })
    return () => { active = false }
  }, [])
  if (!items.length && !error) return null
  return <section className="pf-project-list-panel" aria-label="我参与的项目"><div className="pf-project-list-heading"><div><h2>我参与的项目 <span>{items.length}</span></h2><p>通过项目邀请加入，生成费用从你的个人余额扣除。</p></div></div><div className="pf-shared-project-grid">{items.map(item => <Link key={item.id} to={`/drama/projects/${item.id}/canvas`}><strong>{item.title}</strong><span>项目团队 · 打开画布 →</span></Link>)}</div>{error && <p role="alert">{error}</p>}</section>
}
