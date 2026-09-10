/** 剧情大纲步骤：自动摘要 + 分集剧本流水线 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { BookOpen } from 'lucide-react'
import {
  dramaApi,
  type DramaProject,
  type DramaScript,
} from '../../api/drama'
import { getImageStyleLabel, type ImageStyleId } from '../../lib/dramaImageStyles'
import {
  getEpisodeContentStatus,
  getImageStyleId,
  getSummaryStatus,
  parseEpisodeBodies,
  buildEpisodeContentUpdate,
} from './dramaWorkspaceUtils'
import { dialog } from '../../lib/dialog'
import { DramaImageStyleModal } from './DramaImageStyleModal'

type OutlineSectionKey = 'source' | 'summary' | 'episodes'

export type OutlineStepProps = {
  projectId: number
  project: DramaProject
  onProjectChange: (p: DramaProject) => void
  onOutlineReadyChange: (ready: boolean) => void
  onError: (msg: string) => void
}

// 渲染剧情大纲步骤
export function OutlineStep({
  projectId,
  project,
  onProjectChange,
  onOutlineReadyChange,
  onError,
}: OutlineStepProps) {
  const [script, setScript] = useState<DramaScript | null>(project.script || null)
  const [expanded, setExpanded] = useState<Set<OutlineSectionKey>>(() => new Set())
  const [expandedEpisodes, setExpandedEpisodes] = useState<Set<number>>(() => new Set())
  const [activeEpisodeNumber, setActiveEpisodeNumber] = useState<number | undefined>()
  const [summaryGenerating, setSummaryGenerating] = useState(false)
  const [episodeGenerating, setEpisodeGenerating] = useState(false)
  const [summaryError, setSummaryError] = useState('')
  const [episodeError, setEpisodeError] = useState('')
  const [progress, setProgress] = useState({ done: 0, total: 0 })
  const [summaryEditing, setSummaryEditing] = useState(false)
  const [summaryDraft, setSummaryDraft] = useState<Record<string, unknown> | null>(null)
  const [summarySaving, setSummarySaving] = useState(false)
  const [editingEpisodeNum, setEditingEpisodeNum] = useState<number | null>(null)
  const [episodeBodyDraft, setEpisodeBodyDraft] = useState('')
  const [episodeSaving, setEpisodeSaving] = useState(false)
  const pipelineRef = useRef(0)

  const summary = (script?.summary || null) as Record<string, unknown> | null
  const summaryStatus = getSummaryStatus(script)
  const episodeStatus = getEpisodeContentStatus(script)
  const episodeBodies = parseEpisodeBodies(script)
  const episodeCount =
    Number(
      summary?.episodeCount ||
        (script?.params || {}).episode_count ||
        project.params?.episode_count,
    ) || 0
  const imageStyleId = getImageStyleId(script, project)

  const directoryEpisodes = useMemo(() => {
    // 按目标集数铺满目录；已生成的用正文标题，未生成的显示占位
    const byNumber = new Map(
      episodeBodies.map((ep, i) => {
        const num = ep.episodeNumber || i + 1
        return [num, ep.title || `第 ${num} 集`] as const
      }),
    )
    const total = Math.max(episodeCount, episodeBodies.length, 0)
    if (total <= 0) return []
    return Array.from({ length: total }, (_, i) => {
      const episodeNumber = i + 1
      return {
        episodeNumber,
        title: byNumber.get(episodeNumber) || `第 ${episodeNumber} 集`,
      }
    })
  }, [episodeBodies, episodeCount])

  // 切换折叠区块
  function toggleSection(key: OutlineSectionKey) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  // 目录点击：展开分集剧本并滚动
  function selectEpisode(episodeNumber: number) {
    setExpanded((prev) => new Set(prev).add('episodes'))
    setExpandedEpisodes((prev) => new Set(prev).add(episodeNumber))
    setActiveEpisodeNumber(episodeNumber)
    window.requestAnimationFrame(() => {
      document.getElementById(`outline-episode-${episodeNumber}`)?.scrollIntoView({
        behavior: 'smooth',
        block: 'start',
      })
    })
  }

  // 轮询剧本直到条件满足（worker 异步任务）
  async function pollScriptUntil(
    predicate: (s: DramaScript) => boolean,
    runToken?: number,
  ): Promise<DramaScript | null> {
    const started = Date.now()
    while (Date.now() - started < 45 * 60 * 1000) {
      if (runToken !== undefined && runToken !== pipelineRef.current) return null
      const s = await dramaApi.getScript(projectId)
      setScript(s)
      const prog = (s.params || {}).episode_content_progress as
        | { done?: number; total?: number }
        | undefined
      if (prog && (prog.total || prog.done)) {
        setProgress({
          done: Number(prog.done) || 0,
          total: Number(prog.total) || 0,
        })
      }
      if (predicate(s)) return s
      await new Promise((r) => setTimeout(r, 2000))
    }
    throw new Error('等待生成超时，请刷新后重试')
  }

  // 入队并等待剧本摘要完成
  async function runSummary(runToken?: number) {
    setSummaryGenerating(true)
    setSummaryError('')
    try {
      const res = await dramaApi.scriptSummary({ project_id: projectId })
      setScript(res.script)
      const finished = await pollScriptUntil((s) => {
        const st = getSummaryStatus(s)
        return st === 'completed' || st === 'failed'
      }, runToken)
      if (!finished) return null
      if (getSummaryStatus(finished) === 'failed') {
        const msg =
          String((finished.params || {}).summary_error || '') || '剧本摘要生成失败'
        setSummaryError(msg)
        onError(msg)
        throw new Error(msg)
      }
      const p = await dramaApi.getProject(projectId)
      onProjectChange(p)
      return finished
    } catch (err) {
      const msg = err instanceof Error ? err.message : '剧本摘要生成失败'
      setSummaryError(msg)
      onError(msg)
      throw err
    } finally {
      setSummaryGenerating(false)
    }
  }

  // 入队并轮询分集剧本直到完成
  async function runEpisodeScripts(runToken?: number, force = false) {
    setEpisodeGenerating(true)
    setEpisodeError('')
    try {
      const res = await dramaApi.episodeScript({
        project_id: projectId,
        batch_size: 1,
        force,
      })
      setScript(res.script)
      setProgress({ done: res.total_generated, total: res.total_target })
      const finished = await pollScriptUntil((s) => {
        const st = getEpisodeContentStatus(s)
        return st === 'completed' || st === 'failed'
      }, runToken)
      if (!finished) return
      if (getEpisodeContentStatus(finished) === 'failed') {
        const msg =
          String((finished.params || {}).episode_content_error || '') ||
          '分集剧本生成失败'
        setEpisodeError(msg)
        onError(msg)
        onOutlineReadyChange(false)
        return
      }
      onOutlineReadyChange(true)
      const p = await dramaApi.getProject(projectId)
      onProjectChange(p)
    } catch (err) {
      const msg = err instanceof Error ? err.message : '分集剧本生成失败'
      setEpisodeError(msg)
      onError(msg)
      onOutlineReadyChange(false)
    } finally {
      setEpisodeGenerating(false)
    }
  }

  // 手动强制重写全部分集正文
  async function handleRegenerateEpisodes() {
    if (episodeGenerating) return
    const ok = await dialog.confirm({
      title: '重新生成分集剧本',
      message:
        '将清空当前分集正文并按最新剧本摘要重新生成全部集数，已有编辑将丢失。是否继续？',
      confirmText: '重新生成',
      tone: 'danger',
    })
    if (!ok) return
    onOutlineReadyChange(false)
    await runEpisodeScripts(undefined, true)
  }

  // 挂载自动流水线：无摘要 → 摘要 → 分集（未满目标集数会续跑；已在 worker 中则只轮询）
  useEffect(() => {
    const token = ++pipelineRef.current
    async function pipeline() {
      let current = script
      const status = getSummaryStatus(current)
      if (!current?.summary && status !== 'completed') {
        try {
          if (status === 'generating') {
            setSummaryGenerating(true)
            current = await pollScriptUntil((s) => {
              const st = getSummaryStatus(s)
              return st === 'completed' || st === 'failed'
            }, token)
            setSummaryGenerating(false)
            if (!current || getSummaryStatus(current) === 'failed') {
              const msg =
                String((current?.params || {}).summary_error || '') || '剧本摘要生成失败'
              setSummaryError(msg)
              onError(msg)
              return
            }
          } else {
            current = await runSummary(token)
          }
        } catch {
          return
        }
        if (!current || token !== pipelineRef.current) return
      }
      const target =
        Number(
          (current?.summary as Record<string, unknown> | null)?.episodeCount ||
            (current?.params || {}).episode_count ||
            project.params?.episode_count,
        ) || 0
      const bodies = parseEpisodeBodies(current)
      const epStatus = getEpisodeContentStatus(current)
      // 与后端阈值对齐：过短正文视为未完成，刷新后会续写/重写
      const substantial = bodies.filter(
        (b) => (b.body || '').replace(/\s/g, '').length >= 500,
      ).length
      const complete =
        epStatus === 'completed' && target > 0 && substantial >= target
      if (complete) {
        onOutlineReadyChange(true)
        return
      }
      if (current?.summary || getSummaryStatus(current) === 'completed') {
        if (epStatus === 'generating') {
          setEpisodeGenerating(true)
          const finished = await pollScriptUntil((s) => {
            const st = getEpisodeContentStatus(s)
            return st === 'completed' || st === 'failed'
          }, token)
          setEpisodeGenerating(false)
          if (!finished) return
          if (getEpisodeContentStatus(finished) === 'failed') {
            const msg =
              String((finished.params || {}).episode_content_error || '') ||
              '分集剧本生成失败'
            setEpisodeError(msg)
            onError(msg)
            onOutlineReadyChange(false)
            return
          }
          onOutlineReadyChange(true)
          const p = await dramaApi.getProject(projectId)
          onProjectChange(p)
          return
        }
        await runEpisodeScripts(token)
      }
    }
    void pipeline()
    return () => {
      pipelineRef.current += 1
      onOutlineReadyChange(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  // 更新画面风格
  async function handleStyleChange(styleId: string) {
    try {
      const updated = await dramaApi.updateScript(projectId, {
        image_style_id: styleId || undefined,
      })
      setScript(updated)
      const p = await dramaApi.getProject(projectId)
      onProjectChange(p)
    } catch (err) {
      onError(err instanceof Error ? err.message : '风格更新失败')
    }
  }

  // 进入剧本摘要编辑
  function startSummaryEdit() {
    if (!summary) return
    setSummaryDraft(structuredClone(summary) as Record<string, unknown>)
    setSummaryEditing(true)
    setExpanded((prev) => new Set(prev).add('summary'))
  }

  // 保存手动编辑的剧本摘要
  async function saveSummaryEdit() {
    if (!summaryDraft) return
    setSummarySaving(true)
    try {
      const updated = await dramaApi.updateScript(projectId, { summary: summaryDraft })
      setScript(updated)
      setSummaryEditing(false)
      setSummaryDraft(null)
      const p = await dramaApi.getProject(projectId)
      onProjectChange(p)
    } catch (err) {
      onError(err instanceof Error ? err.message : '摘要保存失败')
    } finally {
      setSummarySaving(false)
    }
  }

  // 开始编辑某一集正文
  function startEpisodeEdit(episodeNumber: number, body: string) {
    setEditingEpisodeNum(episodeNumber)
    setEpisodeBodyDraft(body)
    setExpandedEpisodes((prev) => new Set(prev).add(episodeNumber))
  }

  // 保存分集正文修改
  async function saveEpisodeEdit() {
    if (editingEpisodeNum == null || !script) return
    setEpisodeSaving(true)
    try {
      const bodies = parseEpisodeBodies(script).map((ep) =>
        (ep.episodeNumber || 0) === editingEpisodeNum
          ? { ...ep, body: episodeBodyDraft }
          : ep,
      )
      const updated = await dramaApi.updateScript(projectId, {
        episode_content: buildEpisodeContentUpdate(script, bodies),
      })
      setScript(updated)
      setEditingEpisodeNum(null)
      setEpisodeBodyDraft('')
      const p = await dramaApi.getProject(projectId)
      onProjectChange(p)
    } catch (err) {
      onError(err instanceof Error ? err.message : '分集保存失败')
    } finally {
      setEpisodeSaving(false)
    }
  }

  const characters = Array.isArray(summary?.characters)
    ? (summary.characters as Array<Record<string, unknown>>)
    : []

  return (
    <div className="drama-outline">
      {directoryEpisodes.length > 0 ? (
        <aside className="drama-episode-dir">
          <h3>分集目录</h3>
          <ul>
            {directoryEpisodes.map((ep) => (
              <li key={ep.episodeNumber}>
                <button
                  type="button"
                  className={activeEpisodeNumber === ep.episodeNumber ? 'active' : ''}
                  onClick={() => selectEpisode(ep.episodeNumber)}
                >
                  <span>第 {ep.episodeNumber} 集</span>
                  <small>{ep.title}</small>
                </button>
              </li>
            ))}
          </ul>
        </aside>
      ) : null}

      <div className="drama-outline-main">
        <header className="drama-outline-hero">
          <div className="drama-step-hero-main">
            <div className="drama-step-hero-icon" aria-hidden>
              <BookOpen size={22} strokeWidth={1.75} />
            </div>
            <div>
              <h2>剧情大纲</h2>
              <p className="drama-step-hero-sub">
                {episodeCount ? `共 ${episodeCount} 集` : '集数待定'}
                {imageStyleId
                  ? ` · ${getImageStyleLabel(imageStyleId) || '已选风格'}`
                  : ' · 未选画面风格'}
              </p>
            </div>
          </div>
          <div className="drama-outline-style">
            <DramaImageStyleModal
              variant="field"
              fieldLabel="项目风格"
              title="选择项目风格"
              emptyLabel="未选择"
              value={(imageStyleId as ImageStyleId | '') || ''}
              onChange={(id) => void handleStyleChange(id)}
            />
          </div>
        </header>

        <div className="drama-accordions">
          <Accordion
            title="原始创意"
            open={expanded.has('source')}
            onToggle={() => toggleSection('source')}
          >
            <p className="drama-pre">{script?.source?.trim() || '暂无原始创意'}</p>
          </Accordion>

          <Accordion
            title="剧本摘要"
            open={expanded.has('summary')}
            onToggle={() => toggleSection('summary')}
            action={
              summary && summaryStatus === 'completed' && !summaryEditing ? (
                <button
                  type="button"
                  className="drama-regen-btn"
                  onClick={(e) => {
                    e.stopPropagation()
                    startSummaryEdit()
                  }}
                >
                  编辑摘要
                </button>
              ) : null
            }
          >
            {summaryGenerating || summaryStatus === 'generating' ? (
              <p className="drama-loader">剧本摘要生成中，请稍候…</p>
            ) : null}
            {summaryError || summaryStatus === 'failed' ? (
              <div className="drama-retry-block">
                <p className="drama-error">{summaryError || '剧本摘要生成失败'}</p>
                <button type="button" className="drama-btn-primary" onClick={() => void runSummary()}>
                  重新生成
                </button>
              </div>
            ) : null}
            {summaryEditing && summaryDraft ? (
              <div className="drama-outline-edit">
                <EditableSummaryField
                  label="自定义集数"
                  value={String(summaryDraft.episodeCount ?? '')}
                  onChange={(v) =>
                    setSummaryDraft((prev) =>
                      prev ? { ...prev, episodeCount: v ? Number(v) || v : '' } : prev,
                    )
                  }
                />
                <EditableSummaryField
                  label="故事类型"
                  value={String(summaryDraft.storyType || '')}
                  onChange={(v) =>
                    setSummaryDraft((prev) => (prev ? { ...prev, storyType: v } : prev))
                  }
                />
                <EditableSummaryField
                  label="目标受众"
                  value={String(summaryDraft.targetAudience || '')}
                  onChange={(v) =>
                    setSummaryDraft((prev) => (prev ? { ...prev, targetAudience: v } : prev))
                  }
                />
                <EditableSummaryField
                  label="核心梗"
                  value={String(summaryDraft.coreHook || '')}
                  onChange={(v) =>
                    setSummaryDraft((prev) => (prev ? { ...prev, coreHook: v } : prev))
                  }
                  multiline
                />
                <EditableSummaryField
                  label="一句话故事"
                  value={String(summaryDraft.oneLineStory || '')}
                  onChange={(v) =>
                    setSummaryDraft((prev) => (prev ? { ...prev, oneLineStory: v } : prev))
                  }
                  multiline
                />
                <EditableSummaryField
                  label="故事梗概"
                  value={String(summaryDraft.synopsis || '')}
                  onChange={(v) =>
                    setSummaryDraft((prev) => (prev ? { ...prev, synopsis: v } : prev))
                  }
                  multiline
                />
                <section className="drama-summary-field">
                  <h4>人物小传</h4>
                  <p className="drama-muted drama-outline-edit-hint">
                    可直接修改各字段；保存后资产库「重新抽取」会同步引用新摘要。
                  </p>
                  <div className="drama-character-list">
                    {(Array.isArray(summaryDraft.characters)
                      ? (summaryDraft.characters as Array<Record<string, unknown>>)
                      : []
                    ).map((ch, i) => (
                      <article key={`edit-${ch.name}-${i}`} className="drama-character-card">
                        <EditableSummaryField
                          label="姓名"
                          value={String(ch.name || '')}
                          onChange={(v) =>
                            setSummaryDraft((prev) => {
                              if (!prev) return prev
                              const list = [...(Array.isArray(prev.characters) ? prev.characters : [])]
                              list[i] = { ...(list[i] as Record<string, unknown>), name: v }
                              return { ...prev, characters: list }
                            })
                          }
                        />
                        {(
                          [
                            ['称谓', 'title'],
                            ['角色类型', 'roleType'],
                            ['视觉形象', 'visualImage'],
                            ['核心标签', 'coreTags'],
                            ['身份背景', 'identityBackground'],
                            ['性格特点', 'personality'],
                          ] as const
                        ).map(([label, key]) => (
                          <EditableSummaryField
                            key={key}
                            label={label}
                            value={String(ch[key] || '')}
                            onChange={(v) =>
                              setSummaryDraft((prev) => {
                                if (!prev) return prev
                                const list = [
                                  ...(Array.isArray(prev.characters) ? prev.characters : []),
                                ]
                                list[i] = { ...(list[i] as Record<string, unknown>), [key]: v }
                                return { ...prev, characters: list }
                              })
                            }
                            multiline={key === 'visualImage' || key === 'identityBackground'}
                          />
                        ))}
                      </article>
                    ))}
                  </div>
                </section>
                <div className="drama-outline-edit-actions">
                  <button
                    type="button"
                    className="drama-btn-primary"
                    disabled={summarySaving}
                    onClick={() => void saveSummaryEdit()}
                  >
                    {summarySaving ? '保存中…' : '保存摘要'}
                  </button>
                  <button
                    type="button"
                    className="pf-btn"
                    disabled={summarySaving}
                    onClick={() => {
                      setSummaryEditing(false)
                      setSummaryDraft(null)
                    }}
                  >
                    取消
                  </button>
                </div>
              </div>
            ) : null}
            {!summaryEditing && summary && summaryStatus === 'completed' ? (
              <div className="drama-summary-structured">
                <SummaryField label="自定义集数" value={String(summary.episodeCount ?? '')} />
                <SummaryField label="故事类型" value={String(summary.storyType || '')} />
                <SummaryField label="目标受众" value={String(summary.targetAudience || '')} />
                <SummaryField label="核心梗" value={String(summary.coreHook || '')} />
                <SummaryField label="一句话故事" value={String(summary.oneLineStory || '')} />
                <section>
                  <h4>人物小传</h4>
                  <div className="drama-character-list">
                    {characters.map((ch, i) => (
                      <article key={`${ch.name}-${i}`} className="drama-character-card">
                        <h5>
                          {String(ch.name || '角色')}
                          {ch.title ? `，${String(ch.title)}` : ''}
                        </h5>
                        {(
                          [
                            ['角色类型', 'roleType'],
                            ['视觉形象', 'visualImage'],
                            ['核心标签', 'coreTags'],
                            ['身份背景', 'identityBackground'],
                            ['性格特点', 'personality'],
                          ] as const
                        ).map(([label, key]) =>
                          ch[key] ? (
                            <div key={key} className="drama-character-field">
                              <span>{label}</span>
                              <p>{String(ch[key])}</p>
                            </div>
                          ) : null,
                        )}
                      </article>
                    ))}
                  </div>
                </section>
                <SummaryField label="故事梗概" value={String(summary.synopsis || '')} />
              </div>
            ) : null}
            {!summaryGenerating && summaryStatus !== 'completed' && summaryStatus !== 'failed' ? (
              <p className="drama-muted">等待生成剧本摘要…</p>
            ) : null}
          </Accordion>

          <Accordion
            title="分集剧本"
            open={expanded.has('episodes')}
            onToggle={() => toggleSection('episodes')}
            action={
              summaryStatus === 'completed' || summary ? (
                <button
                  type="button"
                  className="drama-regen-btn"
                  disabled={episodeGenerating || summaryGenerating}
                  onClick={(e) => {
                    e.stopPropagation()
                    void handleRegenerateEpisodes()
                  }}
                >
                  {episodeGenerating ? '生成中…' : '重新生成'}
                </button>
              ) : null
            }
          >
            {summaryStatus !== 'completed' && !summary ? (
              <p className="drama-muted">请先完成剧本摘要</p>
            ) : null}
            {episodeGenerating || episodeStatus === 'generating' ? (
              <p className="drama-loader">
                分集剧本生成中
                {progress.total > 0 ? `（${progress.done}/${progress.total} 集）` : '…'}
              </p>
            ) : null}
            {episodeError || episodeStatus === 'failed' ? (
              <div className="drama-retry-block">
                <p className="drama-error">{episodeError || '分集剧本生成失败'}</p>
                <button
                  type="button"
                  className="drama-btn-primary"
                  disabled={episodeGenerating}
                  onClick={() => void handleRegenerateEpisodes()}
                >
                  重新生成
                </button>
              </div>
            ) : null}
            {!episodeGenerating &&
            episodeStatus !== 'failed' &&
            (summaryStatus === 'completed' || summary) &&
            episodeBodies.length > 0 ? (
              <div className="drama-regen-inline">
                <button
                  type="button"
                  className="drama-btn-primary"
                  onClick={() => void handleRegenerateEpisodes()}
                >
                  重新生成分集剧本
                </button>
                <span className="drama-muted">正文过短或不满意时，可清空后按新提示词重写</span>
              </div>
            ) : null}
            {episodeBodies.length > 0 ? (
              <div className="drama-episode-bodies">
                {episodeBodies
                  .slice()
                  .sort((a, b) => (a.episodeNumber || 0) - (b.episodeNumber || 0))
                  .map((ep) => {
                    const num = ep.episodeNumber || 0
                    const open = expandedEpisodes.has(num)
                    return (
                      <div key={num} id={`outline-episode-${num}`} className="drama-episode-body-item">
                        <button
                          type="button"
                          className="drama-episode-body-toggle"
                          onClick={() =>
                            setExpandedEpisodes((prev) => {
                              const next = new Set(prev)
                              if (next.has(num)) next.delete(num)
                              else next.add(num)
                              return next
                            })
                          }
                        >
                          <span>
                            第 {num} 集 · {ep.title || ''}
                          </span>
                          <span>{open ? '▾' : '▸'}</span>
                        </button>
                        {open ? (
                          editingEpisodeNum === num ? (
                            <div className="drama-outline-edit">
                              <textarea
                                className="drama-outline-edit-body"
                                rows={16}
                                value={episodeBodyDraft}
                                onChange={(e) => setEpisodeBodyDraft(e.target.value)}
                              />
                              <div className="drama-outline-edit-actions">
                                <button
                                  type="button"
                                  className="drama-btn-primary"
                                  disabled={episodeSaving}
                                  onClick={() => void saveEpisodeEdit()}
                                >
                                  {episodeSaving ? '保存中…' : '保存本集'}
                                </button>
                                <button
                                  type="button"
                                  className="pf-btn"
                                  disabled={episodeSaving}
                                  onClick={() => {
                                    setEditingEpisodeNum(null)
                                    setEpisodeBodyDraft('')
                                  }}
                                >
                                  取消
                                </button>
                              </div>
                            </div>
                          ) : (
                            <>
                              <div className="drama-episode-body-toolbar">
                                <button
                                  type="button"
                                  className="drama-regen-btn"
                                  onClick={() => startEpisodeEdit(num, ep.body || '')}
                                >
                                  编辑正文
                                </button>
                              </div>
                              <pre className="drama-pre">{ep.body || ''}</pre>
                            </>
                          )
                        ) : null}
                      </div>
                    )
                  })}
              </div>
            ) : null}
          </Accordion>
        </div>
      </div>
    </div>
  )
}

// 折叠面板
function Accordion({
  title,
  open,
  onToggle,
  action,
  children,
}: {
  title: string
  open: boolean
  onToggle: () => void
  action?: ReactNode
  children: ReactNode
}) {
  return (
    <div className={`drama-accordion ${open ? 'open' : ''}`}>
      <div className="drama-accordion-head-row">
        <button type="button" className="drama-accordion-head" onClick={onToggle}>
          <span>{title}</span>
          <span aria-hidden>{open ? '▾' : '▸'}</span>
        </button>
        {action}
      </div>
      {open ? <div className="drama-accordion-body">{children}</div> : null}
    </div>
  )
}

// 摘要字段块
function SummaryField({ label, value }: { label: string; value: string }) {
  if (!value) return null
  return (
    <section className="drama-summary-field">
      <h4>{label}</h4>
      <p className="drama-pre">{value}</p>
    </section>
  )
}

// 可编辑摘要字段
function EditableSummaryField({
  label,
  value,
  onChange,
  multiline = false,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  multiline?: boolean
}) {
  return (
    <label className="drama-outline-edit-field">
      <span>{label}</span>
      {multiline ? (
        <textarea rows={3} value={value} onChange={(e) => onChange(e.target.value)} />
      ) : (
        <input type="text" value={value} onChange={(e) => onChange(e.target.value)} />
      )}
    </label>
  )
}
