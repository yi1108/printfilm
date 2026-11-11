import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useParams } from 'react-router-dom'
import AppShell from '../../components/layout/AppShell'
import Button from '../../components/ui/Button'
import { createJsonRequester } from '../../api/client'
import { syncProjectWorkspace, type EditTarget } from './editLocks'
import { useTeamEditLock } from './useTeamEditLock'
import { subscribeWorkspace } from './workspaceScope'
import { TeamReadOnlyContext } from './readOnlyContext'

/** 团队内容只读边界：禁用表单控件，服务端 token 检查仍是最终保护。 */
export function TeamEditingBoundary({ projectId, type, resourceId = 0, enabled = true, children, onAcquired, readOnlyActions, interactiveReadOnly = false, showReadOnlyNotice = true, allowReadOnlyNavigation = false }: EditTarget & { enabled?: boolean; children: ReactNode; onAcquired?: (isCurrent: () => boolean) => Promise<void>; readOnlyActions?: ReactNode; interactiveReadOnly?: boolean; showReadOnlyNotice?: boolean; allowReadOnlyNavigation?: boolean }) {
  const lock = useTeamEditLock({ projectId, type, resourceId }, enabled, onAcquired)
  /* 检查占用期间保持工作区挂载（字段先禁用），不整页替换，避免内容反复重挂载。 */
  return <TeamReadOnlyContext.Provider value={lock.readOnly}>{showReadOnlyNotice && <div role="status" className="pf-team-alert" style={{ display: lock.readOnly && !lock.checking ? 'block' : 'none', marginBottom: 12 }}>{lock.error} · 当前只读 <Button size="sm" onClick={lock.retry}>重新尝试编辑</Button>{readOnlyActions}</div>}{interactiveReadOnly ? children : <fieldset disabled={lock.readOnly} inert={lock.readOnly && !allowReadOnlyNavigation} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>{children}</fieldset>}</TeamReadOnlyContext.Provider>
}
/** 旧分镜编辑路由使用数据库分集 ID，先解析稳定集号再进入编辑界面。 */
export function TeamEpisodeEditingBoundary({ children }: { children: ReactNode }) {
  const { projectId, episodeId } = useParams()
  const [target, setTarget] = useState<EditTarget | null>(null)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  /* 首代解析完成前的空间事件来自本组件自身同步，忽略以免二次整页刷新。 */
  const settled = useRef(false)
  useEffect(() => {
    let active = true; setError(''); settled.current = false
    void syncProjectWorkspace(Number(projectId)).then(() => createJsonRequester()<{ project_id: number; params?: { episodeNumber?: number } }>(`/api/drama/episodes/${Number(episodeId)}`)).then((episode) => { if (episode.project_id !== Number(projectId)) throw new Error('分集不属于当前项目'); if (!active) return; settled.current = true; setTarget({ projectId: episode.project_id, type: 'episode', resourceId: Number(episode.params?.episodeNumber || episodeId) }) }).catch((cause) => { if (active) setError(cause instanceof Error ? cause.message : '分集加载失败') })
    const unsubscribe = subscribeWorkspace(() => { if (active && settled.current) setRetry((n) => n + 1) })
    return () => { active = false; unsubscribe() }
  }, [projectId, episodeId, retry])
  /* 错误态在 AppShell 内展示；加载态仅首次进入出现，用壳内骨架屏过渡。 */
  if (error) return (
    <AppShell active="drama" flush>
      <div role="alert" className="drama-workspace-status drama-error">{error}<Button onClick={() => setRetry((n) => n + 1)}>重试</Button></div>
    </AppShell>
  )
  if (!target) return (
    <AppShell active="drama" flush>
      <div role="status" aria-label="正在读取分集与编辑权限" className="drama-workspace-skeleton"><span /><span /><span /></div>
    </AppShell>
  )
  return <TeamEditingBoundary {...target} interactiveReadOnly>{children}</TeamEditingBoundary>
}
