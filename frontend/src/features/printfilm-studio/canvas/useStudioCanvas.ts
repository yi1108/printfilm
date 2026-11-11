import { useCallback, useEffect, useRef, useState } from 'react'
import { addEdge, useEdgesState, useNodesState, type Connection, type Edge, type Node, type OnEdgesChange, type OnNodesChange } from '@xyflow/react'
import { editLockRequestHeaders } from '../../teams/editLocks'
import { printfilmStudioApi } from '../api'
import { documentFromFlow, flowFromDocument, STUDIO_NODE_LABELS, type StudioAddableType } from './flowAdapter'
import type { CanvasDocument } from './canvasCodec'

const SAVE_DELAY_MS = 800

export type StudioSaveStatus = 'loading' | 'idle' | 'dirty' | 'saving' | 'saved' | 'error'

type UseStudioCanvasArgs = {
  projectId: number
  writable: boolean
  teamLocked: boolean
  refreshToken: number
}

/** 加载工作室画布，并在可写时按版本号防抖保存。 */
export function useStudioCanvas({ projectId, writable, teamLocked, refreshToken }: UseStudioCanvasArgs) {
  /*
   * nodes / edges 当前画布
   * status 保存状态
   * error 最近一次失败原因
   * flowKey 冲突回滚后强制重挂载
   * viewport 当前视口
   */
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
  const [status, setStatus] = useState<StudioSaveStatus>('loading')
  const [error, setError] = useState('')
  const [flowKey, setFlowKey] = useState(0)
  const [viewport, setViewport] = useState<CanvasDocument['viewport']>({ x: 0, y: 0, zoom: 1 })
  const versionRef = useRef(1)
  const dirtyRef = useRef(false)
  const savingRef = useRef(false)
  const queuedRef = useRef(false)
  const readyRef = useRef(false)
  const writableRef = useRef(writable)
  const lastSavedRef = useRef('')
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const nodesRef = useRef(nodes)
  const edgesRef = useRef(edges)
  const viewportRef = useRef(viewport)
  writableRef.current = writable
  nodesRef.current = nodes
  edgesRef.current = edges
  viewportRef.current = viewport
  /** 用服务端文档替换本地画布，不把它记成用户修改。 */
  const applyRemote = useCallback((raw: unknown, version: number) => {
    const next = flowFromDocument(raw)
    readyRef.current = false
    versionRef.current = version
    lastSavedRef.current = JSON.stringify(documentFromFlow(next.nodes, next.edges, next.viewport))
    setNodes(next.nodes as Node[])
    setEdges(next.edges as Edge[])
    setViewport(next.viewport)
    setFlowKey((key) => key + 1)
    dirtyRef.current = false
    setStatus('idle')
    setError('')
  }, [setEdges, setNodes])

  /** 首次进入时创建或读取画布。 */
  const load = useCallback(async () => {
    setStatus('loading')
    setError('')
    const row = await printfilmStudioApi.getCanvas(projectId)
    applyRemote(row.document, row.version)
  }, [applyRemote, projectId])

  useEffect(() => {
    let active = true
    load().catch((err) => {
      if (!active) return
      setStatus('error')
      setError(err instanceof Error ? err.message : '画布加载失败')
    })
    return () => { active = false }
  }, [load])

  /** 助手改完画布后重新读取；本地还有未保存修改时不覆盖。 */
  useEffect(() => {
    if (refreshToken === 0 || dirtyRef.current || savingRef.current) return
    let active = true
    load().catch((err) => {
      if (!active) return
      setStatus('error')
      setError(err instanceof Error ? err.message : '画布刷新失败')
    })
    return () => { active = false }
  }, [load, refreshToken])

  /** 把当前节点写回服务端；版本冲突时改为采用服务端内容。 */
  const flush = useCallback(async () => {
    if (!writableRef.current || !readyRef.current) return
    if (savingRef.current) {
      queuedRef.current = true
      return
    }
    savingRef.current = true
    setStatus('saving')
    try {
      while (true) {
        queuedRef.current = false
        const document = documentFromFlow(nodesRef.current, edgesRef.current, viewportRef.current)
        const payload = JSON.stringify(document)
        if (payload === lastSavedRef.current) {
          dirtyRef.current = false
          setStatus('saved')
          return
        }
        const headers = teamLocked ? editLockRequestHeaders({ projectId, type: 'canvas', resourceId: 0 }) : undefined
        const saved = await printfilmStudioApi.saveCanvas(projectId, document, versionRef.current, headers)
        versionRef.current = saved.version
        lastSavedRef.current = payload
        if (queuedRef.current) continue
        dirtyRef.current = false
        setStatus('saved')
        setError('')
        return
      }
    } catch (err) {
      const failed = err as Error & { status?: number }
      if (failed.status === 409) {
        try {
          const row = await printfilmStudioApi.getCanvas(projectId)
          applyRemote(row.document, row.version)
          setError('画布已在其他位置更新，已刷新为最新内容')
          return
        } catch (reloadError) {
          setStatus('error')
          setError(reloadError instanceof Error ? reloadError.message : '刷新画布失败')
          return
        }
      }
      setStatus('error')
      setError(failed.message || '画布保存失败')
    } finally {
      savingRef.current = false
      if (queuedRef.current) {
        queuedRef.current = false
        void flush()
      }
    }
  }, [applyRemote, projectId, teamLocked])

  /** 标记本地修改，并在停止操作后自动保存。 */
  const markDirty = useCallback(() => {
    if (!readyRef.current || !writableRef.current) return
    dirtyRef.current = true
    setStatus('dirty')
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => { void flush() }, SAVE_DELAY_MS)
  }, [flush])

  useEffect(() => () => { if (timerRef.current) clearTimeout(timerRef.current) }, [])

  /** 忽略选中和尺寸测量，只把真实编辑送去保存。 */
  const handleNodesChange: OnNodesChange<Node> = useCallback((changes) => {
    onNodesChange(changes)
    if (changes.some((change) => change.type !== 'select' && change.type !== 'dimensions')) markDirty()
  }, [markDirty, onNodesChange])

  /** 连线增删同样进入自动保存。 */
  const handleEdgesChange: OnEdgesChange<Edge> = useCallback((changes) => {
    onEdgesChange(changes)
    if (changes.some((change) => change.type !== 'select')) markDirty()
  }, [markDirty, onEdgesChange])

  /** 把新连线写入画布。 */
  const handleConnect = useCallback((connection: Connection) => {
    setEdges((current) => addEdge({ ...connection, id: `${connection.source}->${connection.target}` }, current))
    markDirty()
  }, [markDirty, setEdges])

  /** 记录拖动画布后的视口。 */
  const handleMoveEnd = useCallback((_event: unknown, next: { x: number; y: number; zoom: number }) => {
    viewportRef.current = next
    setViewport(next)
    markDirty()
  }, [markDirty])

  /** 把节点正文写回本地画布并排队保存。 */
  const updateNodeText = useCallback((id: string, text: string) => {
    setNodes((current) => current.map((node) => node.id === id ? { ...node, data: { ...node.data, text } } : node))
    markDirty()
  }, [markDirty, setNodes])

  /** 在指定位置或当前视口附近追加一个节点。 */
  const addNode = useCallback((type: StudioAddableType, position?: { x: number; y: number }) => {
    const id = `n-${crypto.randomUUID()}`
    const offset = nodesRef.current.length * 28
    setNodes((current) => [...current, {
      id,
      type,
      position: position ?? { x: 120 + offset, y: 80 + offset },
      data: { label: STUDIO_NODE_LABELS[type] || type, text: '' },
    }])
    markDirty()
  }, [markDirty, setNodes])

  /** 复制当前选中节点，并错开一格避免完全重叠。 */
  const duplicateSelected = useCallback(() => {
    const selected = nodesRef.current.filter((node) => node.selected)
    if (!selected.length) return
    setNodes((current) => [
      ...current.map((node) => ({ ...node, selected: false })),
      ...selected.map((node) => ({
        id: `n-${crypto.randomUUID()}`,
        type: node.type,
        position: { x: node.position.x + 36, y: node.position.y + 36 },
        data: { ...(node.data as Record<string, unknown>) },
        selected: true,
      })),
    ])
    markDirty()
  }, [markDirty, setNodes])

  /** 删除选中节点，并去掉连接到它们的线。 */
  const removeSelected = useCallback(() => {
    const ids = new Set(nodesRef.current.filter((node) => node.selected).map((node) => node.id))
    if (!ids.size) return
    setNodes((current) => current.filter((node) => !ids.has(node.id)))
    setEdges((current) => current.filter((edge) => !ids.has(edge.source) && !ids.has(edge.target)))
    markDirty()
  }, [markDirty, setEdges, setNodes])

  /** 画布完成首帧后再接受视口变化，避免一打开就保存。 */
  const markReady = useCallback(() => { readyRef.current = true }, [])

  return {
    nodes,
    edges,
    status,
    error,
    flowKey,
    viewport,
    handleNodesChange,
    handleEdgesChange,
    handleConnect,
    handleMoveEnd,
    addNode,
    duplicateSelected,
    removeSelected,
    updateNodeText,
    flush,
    markReady,
  }
}
