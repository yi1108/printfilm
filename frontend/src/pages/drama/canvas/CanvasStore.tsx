/** 画布状态上下文：节点/边、历史、UI 开关与增删操作 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import {
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
  type OnConnect,
  type OnEdgesChange,
  type OnNodesChange,
} from '@xyflow/react'
import { dramaApi, resolveDramaMediaUrl } from '../../../api/drama'
import type { DramaAsset } from '../../../api/drama'
import { enqueueDramaImageGen, resumeDramaImageGensFromAssets } from '../../../lib/dramaImageGenQueue'
import { enqueueDramaVideoGen, resumeDramaVideoGensFromAssets } from '../../../lib/dramaVideoGenQueue'
import type { ImageGenerationOptions } from '../../../lib/dramaGenerationOptions'
import type { VideoGenerationOptions } from '../../../lib/dramaVideoGenerationOptions'
import { readEditableVisualPrompt } from '../../../lib/dramaVisualPrompt'
import { getImageStyleId } from '../dramaWorkspaceUtils'
import { isCanvasWorkflow } from '../../../lib/dramaWorkflow'
import {
  createEmptyCanvasHistory,
  pushHistory,
  redoHistory,
  undoHistory,
  type CanvasHistoryState,
} from './canvasHistory'
import { mergeAssetsWithCanvasLayout, buildNodeDataFromAsset } from './assetsToCanvasNodes'
import {
  CANVAS_NODE_DEFAULT_LABEL,
  canvasKindToAssetType,
  type CanvasAssetNodeData,
  type CanvasNodeKind,
} from './canvasTypes'
import { useCanvasAutoSave } from './useCanvasAutoSave'
import { CanvasStoreContext, useCanvasStore as useCanvasStoreBase } from './canvasStoreContext'

type CanvasStoreValue = {
  projectId: number
  nodes: Node<CanvasAssetNodeData>[]
  edges: Edge[]
  loading: boolean
  errorMessage: string
  saveStatusVisible: boolean
  snapToGrid: boolean
  showMinimap: boolean
  canUndo: boolean
  canRedo: boolean
  showNodeSelector: boolean
  setErrorMessage: (msg: string) => void
  toggleSnapToGrid: () => void
  toggleMinimap: () => void
  onNodesChange: OnNodesChange
  onEdgesChange: OnEdgesChange
  onConnect: OnConnect
  addNodeOfKind: (kind: CanvasNodeKind, position: { x: number; y: number }) => Promise<void>
  undo: () => void
  redo: () => void
  pushSnapshot: () => void
  focusNodeId: string | null
  requestFocusNode: (id: string) => void
  clearFocusNode: () => void
  ensureNodeAsset: (nodeId: string) => Promise<number>
  uploadNodeMedia: (nodeId: string, file: File) => Promise<void>
  applyLibraryMediaToNode: (nodeId: string, source: DramaAsset) => Promise<void>
  /** 用最新资产字段同步节点（音色绑定等） */
  syncNodeFromAsset: (nodeId: string, asset: DramaAsset) => void
  /** 写回节点提示词（本地） */
  updateNodePrompt: (nodeId: string, prompt: string) => void
  /** 写回视频节点生成参数 */
  updateNodeVideoOptions: (nodeId: string, options: Record<string, unknown>) => void
  /** 重命名节点（同步资产 name） */
  renameNode: (nodeId: string, name: string) => Promise<void>
  generateNodeImage: (
    nodeId: string,
    prompt: string,
    options?: Partial<ImageGenerationOptions>,
  ) => Promise<void>
  generateNodeVideo: (
    nodeId: string,
    prompt: string,
    options?: Partial<VideoGenerationOptions>,
  ) => Promise<void>
  updateNodeTextContent: (nodeId: string, textContent: string) => void
  /** 可供 @ 引用的画布节点（角色/场景/图片等） */
  mentionableNodes: Array<{
    nodeId: string
    assetId: number
    kind: CanvasNodeKind
    label: string
    mediaUrl?: string | null
  }>
  /** 项目级内置画面风格 ID */
  projectImageStyleId: string
  /** 是否自由画布工作流（非大纲分集） */
  freeCanvasMode: boolean
}

type CanvasStoreProviderProps = {
  projectId: number
  children: ReactNode
}

/** 提供画布受控状态与历史操作 */
export function CanvasStoreProvider({ projectId, children }: CanvasStoreProviderProps) {
  const [nodes, setNodes] = useState<Node<CanvasAssetNodeData>[]>([])
  const [edges, setEdges] = useState<Edge[]>([])
  const [history, setHistory] = useState<CanvasHistoryState>(createEmptyCanvasHistory)
  const [loading, setLoading] = useState(true)
  const [errorMessage, setErrorMessage] = useState('')
  const [dirty, setDirty] = useState(false)
  const [saveStatusVisible, setSaveStatusVisible] = useState(false)
  const [snapToGrid, setSnapToGrid] = useState(false)
  const [showMinimap, setShowMinimap] = useState(false)
  const [focusNodeId, setFocusNodeId] = useState<string | null>(null)
  // projectImageStyleId 项目内置画面风格
  // freeCanvasMode 是否自由画布项目
  const [projectImageStyleId, setProjectImageStyleId] = useState('')
  const [freeCanvasMode, setFreeCanvasMode] = useState(false)
  const readyRef = useRef(false)
  const nodesRef = useRef(nodes)
  const edgesRef = useRef(edges)
  const historyRef = useRef(history)
  const freeCanvasModeRef = useRef(freeCanvasMode)
  const flushRef = useRef<
    (override?: { nodes: Node<CanvasAssetNodeData>[]; edges: Edge[] }) => Promise<void>
  >(async () => undefined)
  nodesRef.current = nodes
  edgesRef.current = edges
  historyRef.current = history
  freeCanvasModeRef.current = freeCanvasMode

  useEffect(() => {
    let cancelled = false
    readyRef.current = false
    setLoading(true)
    setDirty(false)
    setSaveStatusVisible(false)
    setErrorMessage('')

    Promise.all([
      dramaApi.getCanvas(projectId),
      dramaApi.listAssets(projectId),
      dramaApi.getProject(projectId).catch(() => null),
    ])
      .then(([canvas, assets, project]) => {
        if (cancelled) return
        const free = project ? isCanvasWorkflow(project) : false
        setFreeCanvasMode(free)
        const { nodes: mergedNodes, edges: mergedEdges } = mergeAssetsWithCanvasLayout(
          assets,
          canvas.nodes,
          canvas.edges,
          { freeCanvas: free },
        )
        setNodes(mergedNodes)
        setEdges(mergedEdges)
        setHistory(createEmptyCanvasHistory())
        setDirty(false)
        if (project) {
          setProjectImageStyleId(getImageStyleId(project.script, project))
        }
        resumeDramaImageGensFromAssets(projectId, assets)
        resumeDramaVideoGensFromAssets(projectId, assets)
        readyRef.current = true
      })
      .catch((err) => {
        if (cancelled) return
        setErrorMessage(err instanceof Error ? err.message : '加载画布失败')
        readyRef.current = true
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
      readyRef.current = false
    }
  }, [projectId])

  const markDirty = useCallback(() => {
    if (!readyRef.current) return
    setDirty(true)
    setSaveStatusVisible(false)
  }, [])

  const pushSnapshot = useCallback(() => {
    setHistory((prev) =>
      pushHistory(prev, {
        nodes: nodesRef.current,
        edges: edgesRef.current,
      }),
    )
  }, [])

  const onNodesChange: OnNodesChange = useCallback(
    (changes: NodeChange[]) => {
      const removeChanges = changes.filter((c) => c.type === 'remove')
      const hasRemove = removeChanges.length > 0
      /*
       * removedAssetIds 待删后端资产
       * nextNodes / nextEdges 删除后的布局（立刻落盘，避免刷新复现）
       */
      const removedAssetIds: number[] = []
      if (hasRemove) {
        setHistory((prev) =>
          pushHistory(prev, {
            nodes: nodesRef.current,
            edges: edgesRef.current,
          }),
        )
        for (const change of removeChanges) {
          const node = nodesRef.current.find((n) => n.id === change.id)
          const assetId = node?.data.assetId
          if (typeof assetId === 'number' && assetId > 0) {
            removedAssetIds.push(assetId)
          }
        }
      }

      const nextNodes = applyNodeChanges(changes, nodesRef.current) as Node<CanvasAssetNodeData>[]
      nodesRef.current = nextNodes
      setNodes(nextNodes)

      /* 同步剪掉指向已删节点的边，避免布局脏边刷新后异常 */
      let nextEdges = edgesRef.current
      if (hasRemove) {
        const removedIds = new Set(removeChanges.map((c) => c.id))
        nextEdges = edgesRef.current.filter(
          (e) => !removedIds.has(e.source) && !removedIds.has(e.target),
        )
        if (nextEdges.length !== edgesRef.current.length) {
          edgesRef.current = nextEdges
          setEdges(nextEdges)
        }
      }

      const structural = changes.some(
        (c) => c.type === 'remove' || c.type === 'add' || c.type === 'replace' || c.type === 'position',
      )
      if (structural) markDirty()

      if (hasRemove && freeCanvasModeRef.current) {
        for (const assetId of removedAssetIds) {
          void dramaApi.deleteAsset(assetId).catch(() => undefined)
        }
        void flushRef.current({
          nodes: nextNodes,
          edges: nextEdges,
        })
      }
    },
    [markDirty],
  )

  const onEdgesChange: OnEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      const hasRemove = changes.some((c) => c.type === 'remove')
      if (hasRemove) {
        setHistory((prev) =>
          pushHistory(prev, {
            nodes: nodesRef.current,
            edges: edgesRef.current,
          }),
        )
      }
      setEdges((current) => {
        const next = applyEdgeChanges(changes, current)
        edgesRef.current = next
        return next
      })
      if (changes.some((c) => c.type === 'remove' || c.type === 'add' || c.type === 'replace')) {
        markDirty()
      }
    },
    [markDirty],
  )

  const onConnect: OnConnect = useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target || connection.source === connection.target) {
        return
      }
      setHistory((prev) =>
        pushHistory(prev, {
          nodes: nodesRef.current,
          edges: edgesRef.current,
        }),
      )
      setEdges((current) => {
        const next = addEdge({ ...connection, id: `e-${Date.now()}` }, current)
        edgesRef.current = next
        return next
      })
      markDirty()
    },
    [markDirty],
  )

  const addNodeOfKind = useCallback(
    async (kind: CanvasNodeKind, position: { x: number; y: number }) => {
      const label = CANVAS_NODE_DEFAULT_LABEL[kind]
      let assetId: number | undefined
      try {
        const asset = await dramaApi.createAsset({
          project_id: projectId,
          type: kind,
          asset_type: canvasKindToAssetType(kind),
          name: label,
          params: { on_canvas: true },
        })
        assetId = asset.id
      } catch (err) {
        setErrorMessage(err instanceof Error ? err.message : '创建资产失败')
        return
      }

      const id = `asset-${assetId}`
      const node: Node<CanvasAssetNodeData> = {
        id,
        type: 'asset',
        position,
        data: {
          kind,
          label,
          assetId,
          textContent: kind === 'text' ? '' : undefined,
          mediaUrl: null,
        },
      }
      /* 回写 canvas_node_id，刷新后仍能识别为画布节点 */
      void dramaApi
        .updateAsset(assetId, { params: { canvas_node_id: id, on_canvas: true } })
        .catch(() => undefined)

      setHistory((prev) =>
        pushHistory(prev, {
          nodes: nodesRef.current,
          edges: edgesRef.current,
        }),
      )
      const nextNodes = [...nodesRef.current, node]
      nodesRef.current = nextNodes
      setNodes(nextNodes)
      markDirty()
      /* 立刻落盘，避免刷新丢失新建节点 */
      void flushRef.current({
        nodes: nextNodes,
        edges: edgesRef.current,
      })
    },
    [markDirty, projectId],
  )

  /** 确保节点已绑定后端资产，返回 assetId */
  const ensureNodeAsset = useCallback(
    async (nodeId: string) => {
      const node = nodesRef.current.find((n) => n.id === nodeId)
      if (!node) throw new Error('节点不存在')
      if (typeof node.data.assetId === 'number' && node.data.assetId > 0) {
        return node.data.assetId
      }
      const asset = await dramaApi.createAsset({
        project_id: projectId,
        type: node.data.kind,
        asset_type: canvasKindToAssetType(node.data.kind),
        name: node.data.label,
        cover: node.data.mediaUrl || undefined,
        url: node.data.mediaUrl || undefined,
        params: { canvas_node_id: nodeId },
      })
      setNodes((current) =>
        current.map((n) =>
          n.id === nodeId ? { ...n, data: { ...n.data, assetId: asset.id } } : n,
        ),
      )
      markDirty()
      return asset.id
    },
    [markDirty, projectId],
  )

  /** 本地上传图片到节点 */
  const uploadNodeMedia = useCallback(
    async (nodeId: string, file: File) => {
      pushSnapshot()
      const assetId = await ensureNodeAsset(nodeId)
      const asset = await dramaApi.uploadAssetMedia(assetId, file)
      const mediaUrl = asset.url || asset.cover || ''
      setNodes((current) =>
        current.map((n) =>
          n.id === nodeId
            ? { ...n, data: { ...n.data, assetId, mediaUrl, generating: false } }
            : n,
        ),
      )
      markDirty()
    },
    [ensureNodeAsset, markDirty, pushSnapshot],
  )

  /** 从全局资产库选用图片并写回节点，保留可编辑提示词以便再次生成 */
  const applyLibraryMediaToNode = useCallback(
    async (nodeId: string, source: DramaAsset) => {
      if (!source.url && !source.cover) {
        throw new Error('所选资产没有可用图片')
      }
      pushSnapshot()
      const node = nodesRef.current.find((n) => n.id === nodeId)
      if (!node) throw new Error('节点不存在')
      const assetId = await ensureNodeAsset(nodeId)
      const promptHint = readEditableVisualPrompt(source)
      const nextName = (source.name || '').trim() || node.data.label
      const currentAsset = await dramaApi.listAssets(projectId).then(
        (list) => list.find((a) => a.id === assetId) || null,
        () => null,
      )
      const prevParams =
        currentAsset?.params && typeof currentAsset.params === 'object'
          ? (currentAsset.params as Record<string, unknown>)
          : {}
      const sourceParams =
        source.params && typeof source.params === 'object'
          ? (source.params as Record<string, unknown>)
          : {}
      const visualImage = String(
        sourceParams.visualImage || sourceParams.visualPrompt || promptHint || '',
      ).trim()
      const updated = await dramaApi.updateAsset(assetId, {
        name: nextName,
        url: source.url || source.cover,
        cover: source.cover || source.url,
        params: {
          ...prevParams,
          importedFromAssetId: source.id,
          importedFromProjectId: source.project_id,
          visualPrompt: promptHint || visualImage || prevParams.visualPrompt,
          visualImage: visualImage || promptHint || prevParams.visualImage,
          canvas: {
            ...(typeof prevParams.canvas === 'object' && prevParams.canvas
              ? (prevParams.canvas as Record<string, unknown>)
              : {}),
            generation: promptHint ? { prompt: promptHint } : undefined,
          },
          canvas_node_id: nodeId,
        },
      })
      const mediaUrl = updated.url || updated.cover || source.url || source.cover || ''
      setNodes((current) =>
        current.map((n) =>
          n.id === nodeId
            ? {
                ...n,
                data: {
                  ...n.data,
                  assetId,
                  mediaUrl,
                  generating: false,
                  label: nextName,
                  characterName: n.data.kind === 'character' ? nextName : n.data.characterName,
                  promptHint,
                },
              }
            : n,
        ),
      )
      markDirty()
    },
    [ensureNodeAsset, markDirty, pushSnapshot],
  )

  /** 用最新资产字段同步节点展示（音色、封面、提示词等） */
  const syncNodeFromAsset = useCallback(
    (nodeId: string, asset: DramaAsset) => {
      const next = buildNodeDataFromAsset(asset)
      setNodes((current) =>
        current.map((n) =>
          n.id === nodeId
            ? {
                ...n,
                data: {
                  ...n.data,
                  ...next,
                  // 保留本地 generating 状态，避免绑定时闪断
                  generating: n.data.generating,
                },
              }
            : n,
        ),
      )
      markDirty()
    },
    [markDirty],
  )

  /** AI 生图并写回节点 */
  const generateNodeImage = useCallback(
    async (nodeId: string, prompt: string, options?: Partial<ImageGenerationOptions>) => {
      const trimmed = prompt.trim()
      if (!trimmed) throw new Error('请输入提示词')
      pushSnapshot()
      const node = nodesRef.current.find((n) => n.id === nodeId)
      if (!node) throw new Error('节点不存在')
      if (node.data.kind === 'video') throw new Error('视频节点请使用视频生成')

      setNodes((current) =>
        current.map((n) =>
          n.id === nodeId
            ? { ...n, data: { ...n.data, generating: true, promptHint: trimmed } }
            : n,
        ),
      )

      try {
        const assetId = await ensureNodeAsset(nodeId)
        /* 把 @asset:id 展开为可读名称再送生图 API；本地仍保留 token */
        const expandedPrompt = trimmed.replace(/@asset:(\d+)/g, (token, idStr: string) => {
          const refId = Number(idStr)
          const ref = nodesRef.current.find((n) => n.data.assetId === refId)
          if (!ref) return token
          const kindLabel =
            ref.data.kind === 'character'
              ? '角色'
              : ref.data.kind === 'scene'
                ? '场景'
                : ref.data.kind === 'image'
                  ? '图片'
                  : '资产'
          return `${kindLabel}「${ref.data.label}」`
        })
        const latest = await enqueueDramaImageGen({
          projectId,
          assetId,
          assetName: node.data.label,
          assetType: node.data.kind,
          prompt: expandedPrompt,
          options: {
            image_style_id: options?.image_style_id || projectImageStyleId || undefined,
            model_id: options?.model_id,
            aspect_ratio: options?.aspect_ratio,
            resolution: options?.resolution,
          },
        })
        const mediaUrl = latest.url || latest.cover || ''
        if (!mediaUrl) throw new Error('生图超时，请重试')
        setNodes((current) =>
          current.map((n) =>
            n.id === nodeId
              ? {
                  ...n,
                  data: {
                    ...n.data,
                    assetId,
                    mediaUrl,
                    generating: false,
                    promptHint: trimmed,
                  },
                }
              : n,
          ),
        )
        markDirty()
      } catch (err) {
        setNodes((current) =>
          current.map((n) =>
            n.id === nodeId ? { ...n, data: { ...n.data, generating: false } } : n,
          ),
        )
        throw err
      }
    },
    [ensureNodeAsset, markDirty, projectId, projectImageStyleId, pushSnapshot],
  )

  /** 收集连入当前节点的参考资产 ID */
  const collectIncomingAssetIds = useCallback((nodeId: string) => {
    const ids: number[] = []
    const seen = new Set<number>()
    for (const edge of edgesRef.current) {
      if (edge.target !== nodeId) continue
      const source = nodesRef.current.find((n) => n.id === edge.source)
      const assetId = source?.data.assetId
      if (typeof assetId !== 'number' || assetId <= 0 || seen.has(assetId)) continue
      seen.add(assetId)
      ids.push(assetId)
    }
    return ids
  }, [])

  /** AI 生视频并写回节点（Seedance，保留 @asset:id） */
  const generateNodeVideo = useCallback(
    async (nodeId: string, prompt: string, options?: Partial<VideoGenerationOptions>) => {
      const trimmed = prompt.trim()
      if (!trimmed) throw new Error('请输入提示词')
      pushSnapshot()
      const node = nodesRef.current.find((n) => n.id === nodeId)
      if (!node) throw new Error('节点不存在')

      setNodes((current) =>
        current.map((n) =>
          n.id === nodeId
            ? {
                ...n,
                data: {
                  ...n.data,
                  generating: true,
                  promptHint: trimmed,
                  videoOptions: { ...(n.data.videoOptions || {}), ...(options || {}) },
                },
              }
            : n,
        ),
      )

      try {
        const assetId = await ensureNodeAsset(nodeId)
        const latest = await enqueueDramaVideoGen({
          projectId,
          assetId,
          assetName: node.data.label,
          prompt: trimmed,
          options: {
            image_style_id: options?.image_style_id || projectImageStyleId || undefined,
            model_id: options?.model_id,
            aspect_ratio: options?.aspect_ratio,
            resolution: options?.resolution,
            duration_sec: options?.duration_sec,
          },
          referenceAssetIds: collectIncomingAssetIds(nodeId),
        })
        const mediaUrl = resolveDramaMediaUrl(latest.url || latest.cover || '')
        if (!mediaUrl) throw new Error('生视频超时，请重试')
        setNodes((current) =>
          current.map((n) =>
            n.id === nodeId
              ? {
                  ...n,
                  data: {
                    ...n.data,
                    assetId,
                    mediaUrl,
                    generating: false,
                    promptHint: trimmed,
                  },
                }
              : n,
          ),
        )
        markDirty()
      } catch (err) {
        setNodes((current) =>
          current.map((n) =>
            n.id === nodeId ? { ...n, data: { ...n.data, generating: false } } : n,
          ),
        )
        throw err
      }
    },
    [
      collectIncomingAssetIds,
      ensureNodeAsset,
      markDirty,
      projectId,
      projectImageStyleId,
      pushSnapshot,
    ],
  )

  /** 更新节点提示词（不触发生成） */
  const updateNodePrompt = useCallback(
    (nodeId: string, prompt: string) => {
      setNodes((current) =>
        current.map((n) =>
          n.id === nodeId ? { ...n, data: { ...n.data, promptHint: prompt } } : n,
        ),
      )
      markDirty()
    },
    [markDirty],
  )

  /** 更新视频节点 Seedance 参数 */
  const updateNodeVideoOptions = useCallback(
    (nodeId: string, options: Record<string, unknown>) => {
      setNodes((current) =>
        current.map((n) =>
          n.id === nodeId ? { ...n, data: { ...n.data, videoOptions: options } } : n,
        ),
      )
      markDirty()
    },
    [markDirty],
  )

  /** 重命名节点并同步资产 name */
  const renameNode = useCallback(
    async (nodeId: string, name: string) => {
      const trimmed = name.trim()
      if (!trimmed) return
      const node = nodesRef.current.find((n) => n.id === nodeId)
      if (!node || node.data.label === trimmed) return
      pushSnapshot()
      setNodes((current) =>
        current.map((n) =>
          n.id === nodeId
            ? {
                ...n,
                data: {
                  ...n.data,
                  label: trimmed,
                  characterName: n.data.kind === 'character' ? trimmed : n.data.characterName,
                },
              }
            : n,
        ),
      )
      markDirty()
      const assetId =
        typeof node.data.assetId === 'number' && node.data.assetId > 0
          ? node.data.assetId
          : await ensureNodeAsset(nodeId).catch(() => null)
      if (typeof assetId === 'number' && assetId > 0) {
        await dramaApi.updateAsset(assetId, { name: trimmed }).catch(() => undefined)
      }
    },
    [ensureNodeAsset, markDirty, pushSnapshot],
  )

  /** 更新文本节点内容 */
  const updateNodeTextContent = useCallback(
    (nodeId: string, textContent: string) => {
      setNodes((current) =>
        current.map((n) =>
          n.id === nodeId
            ? { ...n, data: { ...n.data, textContent, label: textContent.slice(0, 24) || n.data.label } }
            : n,
        ),
      )
      markDirty()
    },
    [markDirty],
  )

  const undo = useCallback(() => {
    const result = undoHistory(
      { nodes: nodesRef.current, edges: edgesRef.current },
      historyRef.current,
    )
    if (!result) return
    setNodes(result.snapshot.nodes)
    setEdges(result.snapshot.edges)
    setHistory(result.history)
    markDirty()
  }, [markDirty])

  const redo = useCallback(() => {
    const result = redoHistory(
      { nodes: nodesRef.current, edges: edgesRef.current },
      historyRef.current,
    )
    if (!result) return
    setNodes(result.snapshot.nodes)
    setEdges(result.snapshot.edges)
    setHistory(result.history)
    markDirty()
  }, [markDirty])

  const { flush } = useCanvasAutoSave({
    projectId,
    nodes,
    edges,
    dirty,
    enabled: !loading,
    onSaved: () => {
      setDirty(false)
      setSaveStatusVisible(true)
    },
    onError: (msg) => setErrorMessage(msg),
  })
  flushRef.current = flush

  /* 页面关闭前尽量刷一次保存 */
  useEffect(() => {
    const onBeforeUnload = () => {
      if (dirty) void flush()
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [dirty, flush])

  const mentionableNodes = useMemo(
    () =>
      nodes
        .filter(
          (n) =>
            typeof n.data.assetId === 'number' &&
            n.data.assetId > 0 &&
            (n.data.kind === 'character' ||
              n.data.kind === 'scene' ||
              n.data.kind === 'image' ||
              n.data.kind === 'video'),
        )
        .map((n) => ({
          nodeId: n.id,
          assetId: n.data.assetId as number,
          kind: n.data.kind,
          label: n.data.label || CANVAS_NODE_DEFAULT_LABEL[n.data.kind],
          mediaUrl: n.data.mediaUrl,
        })),
    [nodes],
  )

  const value = useMemo<CanvasStoreValue>(
    () => ({
      projectId,
      nodes,
      edges,
      loading,
      errorMessage,
      saveStatusVisible,
      snapToGrid,
      showMinimap,
      canUndo: history.past.length > 0,
      canRedo: history.future.length > 0,
      showNodeSelector: !loading && nodes.length === 0,
      setErrorMessage,
      toggleSnapToGrid: () => setSnapToGrid((v) => !v),
      toggleMinimap: () => setShowMinimap((v) => !v),
      onNodesChange,
      onEdgesChange,
      onConnect,
      addNodeOfKind,
      undo,
      redo,
      pushSnapshot,
      focusNodeId,
      requestFocusNode: (id: string) => setFocusNodeId(id),
      clearFocusNode: () => setFocusNodeId(null),
      ensureNodeAsset,
      uploadNodeMedia,
      applyLibraryMediaToNode,
      syncNodeFromAsset,
      updateNodePrompt,
      updateNodeVideoOptions,
      renameNode,
      generateNodeImage,
      generateNodeVideo,
      updateNodeTextContent,
      mentionableNodes,
      projectImageStyleId,
      freeCanvasMode,
    }),
    [
      projectId,
      nodes,
      edges,
      loading,
      errorMessage,
      saveStatusVisible,
      snapToGrid,
      showMinimap,
      history.past.length,
      history.future.length,
      onNodesChange,
      onEdgesChange,
      onConnect,
      addNodeOfKind,
      undo,
      redo,
      pushSnapshot,
      focusNodeId,
      ensureNodeAsset,
      uploadNodeMedia,
      applyLibraryMediaToNode,
      syncNodeFromAsset,
      updateNodePrompt,
      updateNodeVideoOptions,
      renameNode,
      generateNodeImage,
      generateNodeVideo,
      updateNodeTextContent,
      mentionableNodes,
      projectImageStyleId,
      freeCanvasMode,
    ],
  )

  return <CanvasStoreContext.Provider value={value}>{children}</CanvasStoreContext.Provider>
}

/** 读取画布状态上下文 */
export function useCanvasStore() {
  return useCanvasStoreBase<CanvasStoreValue>()
}
