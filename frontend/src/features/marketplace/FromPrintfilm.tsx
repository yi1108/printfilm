import { useMarketplaceLocale } from './useMarketplaceLocale'
import { marketText as mt, marketFeedback } from './translate'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { request, type Handoff } from './api'
import { internalReturn, PageHeading, withReturn } from './ui'
import Button from '../../components/ui/Button'
import DramaPublishModal from './DramaPublishModal'

type ProjectSource = { id: number; title: string; updated_at: string; has_cover: boolean; status: string }
type DramaSource = { id: number; title: string; episodes: { id: number; name: string; ready: boolean }[] }
type SeriesOption = { id: number; title: string }
type SeriesStep = { id: number; mode: 'pick' | 'existing' }

// 选了短剧之后，再决定新建一部，或加入已有短剧。
function SeriesStepPanel({ series, busy, mode, onCreate, onExisting, onJoin }: {
  series: SeriesOption[]
  busy: boolean
  mode: 'pick' | 'existing'
  onCreate: () => void
  onExisting: () => void
  onJoin: (id: number) => void
}) {
  useMarketplaceLocale()
  const [existingId, setExistingId] = useState('')
  return <div className="pf-market-series-step">
    <p>{mt("这部成片会作为短剧的一集，不改已经发布过的旧版本。")}</p>
    {mode === 'pick' ? <div>
      <Button type="button" variant="lime" disabled={busy} onClick={onCreate}>{mt("新建短剧")}</Button>
      <button type="button" disabled={busy} onClick={onExisting}>{mt("加入已有短剧")}</button>
    </div> : series.length === 0 ? <div>
      <p>{mt("还没有短剧，请新建。")}</p>
      <Button type="button" variant="lime" disabled={busy} onClick={onCreate}>{mt("新建短剧")}</Button>
    </div> : <div>
      <label>{mt("已有短剧")}<select value={existingId} onChange={event => setExistingId(event.target.value)} disabled={busy}><option value="">{mt("请选择短剧")}</option>{series.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>
      <button type="button" disabled={busy || !existingId} onClick={() => onJoin(Number(existingId))}>{mt("添加到这部短剧")}</button>
    </div>}
  </div>
}

// 从 PRINTFILM 已生成成片发起转存。页面只提交编号，不提交视频地址。
export default function FromPrintfilm() {
  useMarketplaceLocale()
  const navigate = useNavigate()
  const [search] = useSearchParams()
  const focusProject = Number(search.get('project') || 0)
  const focusDrama = Number(search.get('drama') || 0)
  const focusEpisode = Number(search.get('episode') || 0)
  const origin = internalReturn(search.get('from'))
  const [projects, setProjects] = useState<ProjectSource[]>([])
  const [dramas, setDramas] = useState<DramaSource[]>([])
  const [series, setSeries] = useState<SeriesOption[]>([])
  const [dramaId, setDramaId] = useState(focusDrama ? String(focusDrama) : '')
  const [dramaPublishOpen, setDramaPublishOpen] = useState(Boolean(focusDrama))
  const [seriesStep, setSeriesStep] = useState<SeriesStep | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let stop = false
    Promise.all([
      request<{ projects: ProjectSource[]; dramas: DramaSource[] }>('/printfilm/sources'),
      request<{ items: SeriesOption[] }>('/mine/series?page_size=100'),
    ]).then(([sources, mine]) => {
      if (stop) return
      setProjects(sources.projects)
      setDramas(sources.dramas)
      setSeries(mine.items)
      setDramaId(current => current || (sources.dramas[0] ? String(sources.dramas[0].id) : ''))
    }).catch(err => { if (!stop) setError((err as Error).message) }).finally(() => { if (!stop) setLoading(false) })
    return () => { stop = true }
  }, [])

  const drama = dramas.find(item => String(item.id) === dramaId)
  const focused = useMemo(() => projects.find(item => item.id === focusProject), [projects, focusProject])

  async function publishWork(project: ProjectSource) {
    setBusy(true); setError('')
    try {
      const handoff = await request<Handoff>('/works/from-printfilm', 'POST', {
        project_id: project.id,
        idempotency_key: `kepu-${project.id}-${project.updated_at}`,
      })
      navigate(withReturn(`/marketplace/works/${handoff.work_id}/edit?handoff=${handoff.id}`, origin))
    } catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }

  async function addProject(project: ProjectSource, target: 'new' | number) {
    setBusy(true); setError('')
    try {
      const seriesTarget = target === 'new' ? (await request<SeriesOption>('/series', 'POST', {
        title: project.title || mt("未命名短剧"), category: '其他', sale_type: 'copyright_contact', copyright_price_fen: 0, description: '',
      })).id : target
      const result = await request<{ handoffs: Handoff[] }>(`/series/${seriesTarget}/episodes/import-printfilm`, 'POST', {
        project_id: project.id,
        idempotency_key: `kepu-${project.id}-${project.updated_at}`,
      })
      const handoff = result.handoffs[0]
      navigate(withReturn(`/marketplace/series/${seriesTarget}/edit${handoff ? `?handoff=${handoff.id}` : ''}`, origin))
    } catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }

  if (loading) return <p role="status">{mt("正在读取已生成的成片…")}</p>
  const heading = <PageHeading title={mt("发布到数字资产市场")} description={focusProject ? mt("这部成片可以发布为单视频，或作为一集加入短剧。同步后补充资料并提交审核。") : mt("选择 PRINTFILM 已生成的成片，同步到市场后补充资料并提交审核。已签署有效授权函的账号会自动关联，未签署的请在提交前完成一次签署。")} back="/marketplace/works/new" backLabel={mt("返回发布作品")} />
  if (focusProject) return <>
    {heading}
    {error && <p role="alert">{marketFeedback(error)}</p>}
    <section className="pf-market-form">
      <h2>{focused?.title || mt("当前成片")}</h2>
      {focused ? <>
        <p className="pf-market-notice">{mt("先选择发布成一条视频，或作为一集放进短剧。")}</p>
        <div className="pf-market-publish-actions">
          <Button variant="lime" type="button" disabled={busy} onClick={() => void publishWork(focused)}>{mt("发布为单视频")}</Button>
          <button type="button" disabled={busy} onClick={() => setSeriesStep({ id: focused.id, mode: 'pick' })}>{mt("发布为短剧")}</button>
        </div>
        {seriesStep?.id === focused.id && <SeriesStepPanel series={series} busy={busy} mode={seriesStep.mode} onCreate={() => void addProject(focused, 'new')} onExisting={() => setSeriesStep({ id: focused.id, mode: 'existing' })} onJoin={id => void addProject(focused, id)} />}
      </> : <p role="status">{mt("这部成片还没有生成完成，暂时不能发布。")}</p>}
    </section>
  </>
  return <>
    {heading}
    {error && <p role="alert">{marketFeedback(error)}</p>}
    <section className="pf-market-form">
      <h2>{mt("科普成片")}</h2>
      <p className="pf-market-notice">{mt("每部成片先选择发布为单视频或短剧。选短剧后，再决定新建或加入已有短剧。")}</p>
      {projects.length === 0 ? <p>{mt("还没有可发布的科普成片。")}</p> : projects.map(project => <article key={project.id} className="pf-market-handoff">
        <strong>{project.title}</strong>
        <div className="pf-market-publish-actions">
          <Button variant="lime" type="button" disabled={busy} onClick={() => void publishWork(project)}>{mt("发布为单视频")}</Button>
          <button type="button" disabled={busy} onClick={() => setSeriesStep({ id: project.id, mode: 'pick' })}>{mt("发布为短剧")}</button>
        </div>
        {seriesStep?.id === project.id && <SeriesStepPanel series={series} busy={busy} mode={seriesStep.mode} onCreate={() => void addProject(project, 'new')} onExisting={() => setSeriesStep({ id: project.id, mode: 'existing' })} onJoin={id => void addProject(project, id)} />}
      </article>)}
    </section>
    <section className="pf-market-form">
      <h2>{mt("漫剧分集")}</h2>
      <p className="pf-market-notice">{mt("只同步勾选的完整分集。完成后，在短剧编辑页补充封面、价格和作品介绍，再提交审核；有效账号授权函会自动关联。")}</p>
      {dramas.length === 0 ? <p>{mt("还没有可导入的漫剧分集。")}</p> : <>
        <label>{mt("漫剧项目")}<select value={dramaId} onChange={event => setDramaId(event.target.value)}>{dramas.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>
        <button type="button" disabled={busy || !drama} onClick={() => setDramaPublishOpen(true)}>{mt("选择完整分集并发布")}</button>
      </>}
    </section>
    {dramaPublishOpen && drama && <DramaPublishModal projectId={drama.id} initialEpisodeId={focusEpisode || undefined} onClose={() => setDramaPublishOpen(false)} />}
  </>
}
