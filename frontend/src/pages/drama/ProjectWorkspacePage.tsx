/** 漫剧项目工作流：剧情大纲 / 资产库 / 分集视频 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { ChevronLeft } from 'lucide-react'
import BillingErrorNotice from '../../components/billing/BillingErrorNotice'
import AppShell from '../../components/layout/AppShell'
import { dramaApi, type DramaProject } from '../../api/drama'
import {
  buildProjectSteps,
  getInitialProjectStep,
  getNextProjectStep,
  type ProjectStepKey,
} from '../../lib/dramaProjectSteps'
import { formatDramaUsageBrief } from '../../lib/dramaUsage'
import { isCanvasWorkflow } from '../../lib/dramaWorkflow'
import { AssetsStep } from './AssetsStep'
import { EpisodesStep } from './EpisodesStep'
import { OutlineStep } from './OutlineStep'
import RequireAuth from './RequireAuth'
import './drama.css'

export default function ProjectWorkspacePage() {
  return (
    <RequireAuth>
      <WorkspaceInner />
    </RequireAuth>
  )
}

// 项目工作台主体
function WorkspaceInner() {
  const { projectId } = useParams()
  const id = Number(projectId)
  const navigate = useNavigate()
  const location = useLocation()
  /*
   * project 项目详情
   * activeStep 当前步骤
   * outlineReady 大纲是否完成
   * titleDraft 可编辑标题
   * editingTitle 是否在编辑标题
   * loading / error 加载态
   */
  const [project, setProject] = useState<DramaProject | null>(null)
  const [activeStep, setActiveStep] = useState<ProjectStepKey>('outline')
  const [outlineReady, setOutlineReady] = useState(false)
  const [titleDraft, setTitleDraft] = useState('')
  const [editingTitle, setEditingTitle] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const locationApplied = useRef(false)

  const hasScript = Boolean(project?.script)
  const steps = useMemo(() => buildProjectSteps(hasScript), [hasScript])
  const nextStep = useMemo(() => getNextProjectStep(steps, activeStep), [steps, activeStep])
  const canGoNext =
    nextStep !== null && (activeStep === 'outline' ? outlineReady : activeStep === 'assets')

  // 加载项目；自由画布项目强制进入画布页
  async function reload() {
    const p = await dramaApi.getProject(id)
    if (isCanvasWorkflow(p)) {
      navigate(`/drama/projects/${id}/canvas`, { replace: true })
      return null
    }
    setProject(p)
    setTitleDraft(p.title)
    return p
  }

  useEffect(() => {
    if (!Number.isFinite(id) || id <= 0) return
    setLoading(true)
    reload()
      .then((p) => {
        if (!p) return
        if (!locationApplied.current) {
          const state = location.state as
            | { activeStep?: ProjectStepKey; returnStep?: ProjectStepKey }
            | null
          if (state?.activeStep) setActiveStep(state.activeStep)
          else if (state?.returnStep) setActiveStep(state.returnStep)
          else setActiveStep(getInitialProjectStep(Boolean(p.script)))
          locationApplied.current = true
        }
      })
      .catch((err) => setError(err instanceof Error ? err.message : '加载失败'))
      .finally(() => setLoading(false))
  }, [id])

  useEffect(() => {
    const state = location.state as
      | { activeStep?: ProjectStepKey; returnStep?: ProjectStepKey }
      | null
    if (state?.activeStep) setActiveStep(state.activeStep)
    else if (state?.returnStep) setActiveStep(state.returnStep)
  }, [location.state])

  // 切换步骤时刷新用量（生图/生视频后顶栏数字同步）
  useEffect(() => {
    if (!Number.isFinite(id) || id <= 0 || loading || !project) return
    void dramaApi
      .getProject(id)
      .then((p) => {
        setProject((prev) => (prev ? { ...prev, usage: p.usage } : p))
      })
      .catch(() => undefined)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 仅随步骤变化刷新
  }, [activeStep, id])

  // 保存标题
  async function saveTitle() {
    const next = titleDraft.trim()
    if (!next || !project) {
      setEditingTitle(false)
      setTitleDraft(project?.title || '')
      return
    }
    try {
      const updated = await dramaApi.updateProject(id, { title: next })
      setProject(updated)
      setTitleDraft(updated.title)
    } catch (err) {
      setError(err instanceof Error ? err.message : '标题保存失败')
    } finally {
      setEditingTitle(false)
    }
  }

  if (!Number.isFinite(id) || id <= 0) {
    return (
      <AppShell active="drama" flush>
        <div className="drama-workspace-status">项目 ID 无效</div>
      </AppShell>
    )
  }

  if (loading) {
    return (
      <AppShell active="drama" flush>
        <div className="drama-workspace-status">加载中…</div>
      </AppShell>
    )
  }

  if (error && !project) {
    return (
      <AppShell active="drama" flush>
        <div className="drama-workspace-status drama-error">{error}</div>
      </AppShell>
    )
  }

  if (!project) {
    return (
      <AppShell active="drama" flush>
        <div className="drama-workspace-status">项目不存在</div>
      </AppShell>
    )
  }

  return (
    <AppShell active="drama" flush wide>
      <div className="drama-workspace">
        <header className="drama-workspace-top">
          <div className="drama-workspace-top-left">
            <button
              type="button"
              className="drama-icon-btn"
              aria-label="返回"
              onClick={() => navigate('/drama/dramas')}
            >
              <ChevronLeft size={20} strokeWidth={1.75} />
            </button>
            {editingTitle ? (
              <input
                className="drama-title-input"
                value={titleDraft}
                autoFocus
                onChange={(e) => setTitleDraft(e.target.value)}
                onBlur={() => void saveTitle()}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') void saveTitle()
                  if (e.key === 'Escape') {
                    setTitleDraft(project.title)
                    setEditingTitle(false)
                  }
                }}
              />
            ) : (
              <button type="button" className="drama-title-display" onClick={() => setEditingTitle(true)}>
                {project.title}
              </button>
            )}
          </div>

          <nav className="drama-step-bar" aria-label="项目步骤">
            {steps.map((step, index) => {
              const isActive = step.key === activeStep
              const activeIndex = steps.findIndex((s) => s.key === activeStep)
              const isCompleted = activeIndex > index
              return (
                <div key={step.key} className="drama-step-bar-item">
                  <button
                    type="button"
                    className={isActive ? 'active' : isCompleted ? 'done' : ''}
                    onClick={() => setActiveStep(step.key)}
                  >
                    <span className="drama-step-num">{step.order}</span>
                    <span>{step.label}</span>
                  </button>
                  {index < steps.length - 1 ? <span className="drama-step-sep">›</span> : null}
                </div>
              )
            })}
          </nav>

          <div className="drama-workspace-top-right">
            {project.usage ? (
              <span className="drama-usage-chip" title="本剧累计费用与生成次数">
                {formatDramaUsageBrief(project.usage)}
              </span>
            ) : null}
            {nextStep ? (
              <button
                type="button"
                className="drama-next-btn"
                disabled={!canGoNext}
                onClick={() => setActiveStep(nextStep)}
              >
                下一步
              </button>
            ) : null}
          </div>
        </header>

        {error ? <BillingErrorNotice message={error} className="drama-error drama-workspace-banner" /> : null}

        <main className="drama-workspace-main">
          {activeStep === 'outline' ? (
            <OutlineStep
              projectId={id}
              project={project}
              onProjectChange={(p) => {
                setProject(p)
                setTitleDraft(p.title)
              }}
              onOutlineReadyChange={setOutlineReady}
              onError={setError}
            />
          ) : null}
          {activeStep === 'assets' ? <AssetsStep projectId={id} onError={setError} /> : null}
          {activeStep === 'episodes' ? <EpisodesStep projectId={id} onError={setError} /> : null}
        </main>
      </div>
    </AppShell>
  )
}
