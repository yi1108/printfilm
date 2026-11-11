import { linkedNodeReferences, referenceState } from './canvas/linkedNodeReferences'
import { referenceAssetNode } from './canvas/referenceAssetNode'
import { useCanvasPresence, absoluteNodePosition } from './collaboration'
import { CollaborationOverlay } from './canvas/CollaborationOverlay'
import { WorkspaceToolbar } from './WorkspaceToolbar'
import { WorkspaceTour } from './WorkspaceTour'
import { CanvasAgentButton } from './CanvasAgentButton'
import { StoryboardWorkspace } from './storyboard/StoryboardWorkspace'
import { setStorySequence } from './storyboard/storyboardState'
import { DefaultModelPanel, WalletPanel, WorkspaceUtilityPanel } from './WorkspacePanels'
import { defaultNodeData, storeSnapshot } from './workspacePreferences'
import { writingContext, writingInputSignature, createWritingReferenceResolver, linkedWritingResult, toggleWritingReference, assertWritingParameters } from './canvas/writingContext'
import { WritingRunStore } from './canvas/WritingRunStore'
import { nodeDraft } from './canvas/nodeDraft'
import { plainPrompt, type PromptReference } from './canvas/promptMentions'
import { videoPromptAudio } from './canvas/videoPromptAudio'
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore, type MouseEvent } from 'react'
import { createPortal } from 'react-dom'
import { addEdge, getViewportForBounds, Background, MiniMap, ReactFlow, SelectionMode, useEdgesState, useNodesState, type Connection, type Edge, type Node, type ReactFlowInstance, type Viewport } from '@xyflow/react'
import { Bot, Box, ChevronDown, FolderOpen, Hand, CircleHelp, Scan, LayoutGrid, Link2, Map, MousePointer2, Plus, Redo2, Search, Sparkles, Undo2, X, ZoomIn, ZoomOut } from 'lucide-react'
import '@xyflow/react/dist/style.css'
import { useNavigate, useParams } from 'react-router-dom'
import { dramaApi } from '../../api/drama'
import { decodeCanvasDocument, encodeCanvasDocument } from './canvas/canvasCodec'
import { printfilmStudioApi } from './api'
import type { AgentOptions, MediaOperation, ProjectAsset, FrameAnalysisReport } from './types'
import { AgentPanel, type AgentEvent } from './agent/AgentPanel'
import { eventFromWire, sessionEvents } from './agent/conversation'
import type { AgentReference } from './agent/references'
import { WorkspaceChrome, type WorkspaceMode, type WorkspaceAction } from './WorkspaceChrome'
import { WorkspaceAccessNotice } from './WorkspaceAccessNotice'
import { canEditStudioCanvas, loadStudioCanvas, STUDIO_SESSION_EXPIRED, studioLoginPath, workspaceIssue, type WorkspaceIssue } from './workspaceAccess'
import { WorkspaceDocument } from './canvas/WorkspaceDocument'
import { generationControls } from './canvas/generationControls'
import { CanvasSearch } from './canvas/CanvasSearch'
import { GridSplitEditor } from './canvas/GridSplitEditor'
import { MediaEditor } from './canvas/MediaEditor'
import { FrameAnalysisEditor } from './canvas/FrameAnalysisEditor'
import { VideoNodeSetup } from './canvas/VideoNodeSetup'
import { InlineTextComposer } from './canvas/InlineTextComposer'
import { ImageToolsEditor } from './canvas/ImageToolsEditor'
import type { ImageToolMode } from './canvas/imageToolParameters'
import { readProjectMedia, withProjectMedia } from './canvas/projectMedia'
import { NodeMediaHistory } from './canvas/NodeMediaHistory'
import { replaceNodeMedia, mediaCandidates, adoptMediaCandidate } from './canvas/mediaHistory'
import { MediaComparison } from './canvas/MediaComparison'
import { CompositionEditor } from './canvas/CompositionEditor'
import { compositionClips, compositionError } from './canvas/composition'
import { disconnectStudioEdge } from './canvas/connections'
import { api, type Wallet } from '../../api'
import { editLockRequestHeaders, type EditTarget } from '../../features/teams/editLocks'
import { setWorkspaceTeam, subscribeWorkspace, workspaceScope } from '../teams/workspaceScope'
import { SharePanel } from './ProjectSharePanel'
import { projectSharingApi } from './projectSharing'
import { tasksApi, type TaskRunOut } from '../../api/tasks'
import { createStudioDragCopy, moveStudioDragCopy, type StudioDragCopy, arrangeStudioNodes, captureStudioSelection, pasteStudioSelection, mergeStudioGroups, createStudioGroup, groupStudioNodes, ungroupStudioNodes, duplicateStudioNodes, nodeMediaKind, removeStudioNodes, updateStudioNode, validateStudioConnection } from './canvas/nodeOperations'
import { organizeCanvas, nodeWorldPositions } from './canvas/organizeCanvas'
import { studioEdgeTypes } from './canvas/StudioEdge'
import { CanvasTidyMotion, type CanvasTidyRun } from './canvas/CanvasTidyMotion'
import { clampMediaIndex, collectMediaUrls } from './canvas/imageVariants'
import { cropImageToDataUrl } from './canvas/nodeMedia'
import { DirectorEditor } from './canvas/DirectorEditor'
import { MaskEditor } from './canvas/MaskEditor'
import { finishInpaint, type InpaintData } from './canvas/maskMedia'
import { InpaintAspectMismatchError } from './canvas/maskPixels'
import { RecipeLibrary } from './canvas/RecipeLibrary'
import { captureRecipe, instantiateRecipe } from './canvas/recipeGraph'
import type { CanvasDocument } from './canvas/canvasCodec'
import { ASSET_DRAG_TYPE, AssetLibraryPanel, assetMediaKind } from './canvas/AssetLibraryPanel'
import { videoFileReferences, videoReferenceError, VIDEO_MODES, type StudioVideoMode, type MediaKind } from './canvas/generationReferences'
import { storyVideoInputs, storyAssetPrompt } from './canvas/storyGenerationInputs'
import { applyProposal, type AgentProposal, type ProposalAction, type ProposalStates } from './agent/proposals'
import { type BatchSettings, type BatchQuote } from './agent/batchGeneration'
import { dependencyPlan, nodeResultReady, writingNode } from './agent/dependencyRun'
import { BatchRunDialog, batchDefaults } from './agent/BatchRunDialog'
import { visibleStoryEdges } from './canvas/storyEdgeVisibility'
import { StudioContextMenu, StudioInspector, type InspectorDraft } from './canvas/NodePanels'
import { AddNodeMenu } from './canvas/AddNodeMenu'
import { HistoryPicker } from './canvas/HistoryPicker'
import { NODE_TYPE_LABEL, type NodeCatalogItem } from './canvas/nodeCatalog'
import { StudioNodeCard } from './canvas/StudioNodeCard'
import { imageNodeSize, mediaNodeWidth } from './canvas/nodePresentation'
import { newNodePosition, nodeMenuPosition } from './canvas/nodePlacement'
import { canvasShortcut, isCanvasKeyboardTarget } from './canvas/canvasShortcuts'
import { StudioComposerContext, StudioNodeActionsContext, type StudioComposerState, type StudioNodeActions } from './canvas/studioNodeContext'
import type { ComposerAction } from './canvas/PromptComposer'
import { estimateStudioTool, queryStudioTasks, resolveToolMediaUrl, runStudioTool, type ToolReferenceInput, type ToolRunRecord } from '../../api/tools'
import { catalogImageModels, catalogModelLabel, catalogVideoModels, resolveCatalogModelSelection, useMediaModelsCatalog } from '../../hooks/useMediaModelsCatalog'
import './printfilmStudio.css'
import './studioEditors.css'
import './sourceParity.css'
import './agent/agentPanel.css'
import './canvas/canvasRefinements.css'
import './workspaceChrome.css'

type Data = { label?: string; name?: string; mediaUrl?: string; url?: string; cover?: string; prompt?: string; status?: string; assetId?: number; taskId?: string; [key: string]: unknown }
type Asset = ProjectAsset


type NodeContextMenu = { left: number; top: number; id: string; kind?: 'edge' }
type GraphSnapshot = { nodes: Node<Data>[]; edges: Edge[] }

/** 已知类型注册表；未知 type 也回落到 StudioNodeCard，避免 React Flow #003 + 测量抖动。 */
const registeredNodeTypes = Object.fromEntries(Object.keys(NODE_TYPE_LABEL).map((type) => [type, StudioNodeCard])) as Record<string, typeof StudioNodeCard>
const nodeTypes = new Proxy(registeredNodeTypes, {
  get(target, prop, receiver) {
    if (typeof prop !== 'string') return Reflect.get(target, prop, receiver)
    return target[prop] ?? StudioNodeCard
  },
})
const nodeLabel = NODE_TYPE_LABEL

function writingReference(node: Node<Data>) {
  const image = nodeMediaKind(node) === 'image' ? collectMediaUrls(node.data)[0] : undefined
  return { id: node.id, label: String(node.data.label || '素材'), mediaKind: nodeMediaKind(node), text: nodeDraft(node) + (image ? `\n参考图片地址：${image}` : ''), url: image }
}

function newNode(type: string, index: number, extras: Record<string, unknown> = {}): Node<Data> {
  return { id: `node-${Date.now()}-${index}`, type, position: { x: 90 + (index % 3) * 300, y: 130 + Math.floor(index / 3) * 210 }, data: { ...defaultNodeData(type), label: `新${nodeLabel[type] || '节点'}`, ...extras } }
}

export default function PrintfilmStudioPage() {
  const { projectId } = useParams()
  return <PrintfilmStudioWorkspace key={projectId} />
}

function PrintfilmStudioWorkspace() {
  const navigate = useNavigate()
  const [projectTitle, setProjectTitle] = useState('')
  const [projectOwner, setProjectOwner] = useState(false)
  const importCanvasRef = useRef<HTMLInputElement | null>(null)
  const projectId = Number(useParams().projectId)
  const validProjectId = Number.isInteger(projectId) && projectId > 0
  const workspaceEpoch = useSyncExternalStore(subscribeWorkspace, () => workspaceScope.epoch)
  const writingRuns = useMemo(() => new WritingRunStore(id => printfilmStudioApi.stopSession(id)), [projectId, workspaceEpoch])
  useEffect(() => () => writingRuns.dispose(), [writingRuns])
  const [canvasReady, setCanvasReady] = useState(false)
  const [loadIssue, setLoadIssue] = useState<WorkspaceIssue | null>(null)
  const [loadAttempt, setLoadAttempt] = useState(0)
  const [sessionExpired, setSessionExpired] = useState(false)
  const presence = useCanvasPresence(projectId,canvasReady && !sessionExpired,workspaceEpoch)
  const draggingPresenceRef = useRef(false)
  const canvasTarget = useMemo<EditTarget>(() => ({ projectId, type: 'canvas', resourceId: 0 }), [projectId])
  // 后台生成只更新任务进度，不占用人工编辑权；成员权限与版本校验保护共享画布。
  const canEdit = canEditStudioCanvas(validProjectId, canvasReady, Boolean(loadIssue), sessionExpired)
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<Data>>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
  const resolveWritingReferences = useMemo(createWritingReferenceResolver,[])
  const [workspacePanel, setWorkspacePanel] = useState<WorkspaceAction | null>(null)
  const [workspaceTheme, setWorkspaceTheme] = useState(() => localStorage.getItem('printfilm.theme') || 'light')
  const [version, setVersion] = useState(1)
  const [viewport, setViewport] = useState<Viewport>({ x: 0, y: 0, zoom: 1 })
  /** 远端文档写入后递增，强制 ReactFlow 用 defaultViewport 重挂载（避免受控 viewport 死循环）。 */
  const [flowKey, setFlowKey] = useState(0)
  const [flow, setFlow] = useState<ReactFlowInstance<Node<Data>, Edge> | null>(null)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [selectedNodeIds, setSelectedNodeIds] = useState<string[]>([])
  const [panelsSuppressed, setPanelsSuppressed] = useState(false)
  const [tidyRun, setTidyRun] = useState<CanvasTidyRun | null>(null)
  const tidyRunningRef = useRef(false)
  const [agentDockWidth, setAgentDockWidth] = useState(0)
  const [inspectorOpen, setInspectorOpen] = useState(false)
  const [inspectorDraft, setInspectorDraft] = useState<InspectorDraft | null>(null)
  const [contextMenu, setContextMenu] = useState<NodeContextMenu | null>(null)
  const [paneAddMenu, setPaneAddMenu] = useState<{ left: number; top: number; position?: { x: number; y: number } } | null>(null)
  const [viewMode, setViewMode] = useState<WorkspaceMode>('canvas')
  const [composerOpen, setComposerOpen] = useState(false)
  const [selectionAction, setSelectionAction] = useState<ComposerAction | null>(null)
  const [outputRatio, setOutputRatio] = useState('2:3')
  const [outputCount, setOutputCount] = useState('1')
  const [outputVideoMode, setOutputVideoMode] = useState<StudioVideoMode | undefined>(undefined)
  const [outputDuration, setOutputDuration] = useState('7')
  const [outputAudio, setOutputAudio] = useState(true)
  const [outputVoice, setOutputVoice] = useState('narrator_calm')
  const [outputResolution, setOutputResolution] = useState('480p')
  const [imageResolution, setImageResolution] = useState('2K')
  const [hiddenRefIds, setHiddenRefIds] = useState<string[]>([])
  const [composerChips, setComposerChips] = useState<{ id: string; label: string; text?: string }[]>([])
  const [estimateText, setEstimateText] = useState('预计消耗 —')
  const [genModel, setGenModel] = useState('')
  const [submissionError, setSubmissionError] = useState<{ nodeId: string; message: string } | null>(null)
  const mediaCatalog = useMediaModelsCatalog()
  const [status, setStatus] = useState(validProjectId ? '加载中' : '缺少项目 ID')
  const [tool, setTool] = useState<'select' | 'hand' | 'nodes'>('select')
  const [spacePan, setSpacePan] = useState(false)
  const pointerRef = useRef<{ x: number; y: number } | null>(null)
  const [showEdges, setShowEdges] = useState(true)
  const [focusStoryEdges, setFocusStoryEdges] = useState(true)
  const [showMap, setShowMap] = useState(false)
  const [snap, setSnap] = useState(false)
  const [assetsOpen, setAssetsOpen] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [historyNodeId, setHistoryNodeId] = useState<string | null>(null)
  const canEditRef = useRef(canEdit)
  canEditRef.current = canEdit
  const [directorNodeId, setDirectorNodeId] = useState<string | null>(null)
  const [mediaEdit, setMediaEdit] = useState<{ id: string; operation: MediaOperation; start?: number } | null>(null)
  const [gridNodeId, setGridNodeId] = useState<string | null>(null)
  const [analysisNodeId, setAnalysisNodeId] = useState<string | null>(null)
  const [videoSetup, setVideoSetup] = useState<{ id: string; mode: 'image_to_video' | 'first_last_frame' } | null>(null)
  const [textGenerationNodeId, setTextGenerationNodeId] = useState<string | null>(null)
  const [imageTool, setImageTool] = useState<{ id: string; mode: ImageToolMode } | null>(null)
  const replaceTargetRef = useRef<string | null>(null)
  const [maskNodeId, setMaskNodeId] = useState<string | null>(null)
  const [imageEditorMode, setImageEditorMode] = useState<'edit' | 'crop'>('edit')
  const [pendingImageGeneration, setPendingImageGeneration] = useState<{ nodeId: string; prompt: string } | null>(null)
  const compositesRef = useRef(new globalThis.Map<string, Promise<ProjectAsset>>())
  const [recipeOpen, setRecipeOpen] = useState(false)
  const [recipeDraft, setRecipeDraft] = useState<CanvasDocument | undefined>()
  const [agentOpen, setAgentOpen] = useState(false)
  const [searchOpen, setSearchOpen] = useState(false)
  const [helpOpen, setHelpOpen] = useState(false)
  const [tourOpen, setTourOpen] = useState(false)
  const tourAgentWasOpen = useRef(false)
  const [referenceTargetId, setReferenceTargetId] = useState<string | null>(null)
  const [bottomOpen, setBottomOpen] = useState(false)
  const [prompt, setPrompt] = useState('')
  const [genPrompt, setGenPrompt] = useState('')
  useEffect(() => { setSubmissionError(null) }, [selectedNodeId, genModel, outputRatio, outputDuration, outputAudio, outputResolution, outputVideoMode, genPrompt])
  const [answer, setAnswer] = useState('')
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [agentEvents, setAgentEvents] = useState<AgentEvent[]>([])
  const [batchNodeIds, setBatchNodeIds] = useState<string[]>([])
  const [proposalBusy, setProposalBusy] = useState(false)
  const proposalBusyRef = useRef(false)
  const [agentRunning, setAgentRunning] = useState(false)
  const [submittingNodeIds, setSubmittingNodeIds] = useState<Set<string>>(new Set())
  const generationRunningRef = useRef(new Set<string>())
  const generationRunning = submittingNodeIds.has(selectedNodeId || 'new')
  const [assets, setAssets] = useState<Asset[]>([])
  const [tasks, setTasks] = useState<TaskRunOut[]>([])
  const [wallet, setWallet] = useState<Wallet | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [previewKind, setPreviewKind] = useState<'image' | 'video' | 'audio' | 'text'>('image')
  const [compareNodeId, setCompareNodeId] = useState<string | null>(null)
  const [compositionNodeId,setCompositionNodeId]=useState<string|null>(null)
  const agentAbort = useRef<AbortController | null>(null)
  const agentAnswerRef = useRef('')
  const agentHandlerRef = useRef<(event: Record<string, unknown>) => void>(() => undefined)
  useEffect(()=>{
    if (!draggingPresenceRef.current) presence.update({node_ids:selectedNodeIds.slice(0,32),positions:[],action:generationRunning || agentRunning ? 'generating' : inspectorOpen || textGenerationNodeId || composerOpen ? 'editing' : 'idle'})
  },[selectedNodeIds,inspectorOpen,textGenerationNodeId,composerOpen,generationRunning,agentRunning,presence.update,canvasReady])
  const dirtyRef = useRef(false)
  const mountedRef = useRef(true)
  const savingRef = useRef(false)
  const saveCompletionRef = useRef<Promise<void> | null>(null)
  const saveBlockedRef = useRef(false)
  const versionRef = useRef(version)
  const nodesRef = useRef(nodes)
  const edgesRef = useRef(edges)
  const pastRef = useRef<GraphSnapshot[]>([])
  const futureRef = useRef<GraphSnapshot[]>([])
  const clipboardRef = useRef<GraphSnapshot | null>(null)
  const dragCopyRef = useRef<StudioDragCopy | null>(null)
  const uploadRef = useRef<HTMLInputElement | null>(null)
  const commandRef = useRef<Record<string, () => void>>({})
  const keyboardBlockedRef = useRef(false)
  keyboardBlockedRef.current = viewMode !== 'canvas' || !!(tidyRun || previewUrl || compareNodeId || compositionNodeId || directorNodeId || mediaEdit || gridNodeId || analysisNodeId || imageTool || maskNodeId || recipeOpen || historyNodeId || inspectorOpen || historyOpen)
  const documentExtrasRef = useRef<Record<string, unknown>>({})
  nodesRef.current = nodes
  edgesRef.current = edges
  const document = useMemo(() => encodeCanvasDocument({ ...documentExtrasRef.current, toonflowCanvas: true, version: 1, nodes: nodes.map((node) => Object.fromEntries(Object.entries(node).filter(([key]) => !['selected', 'measured', 'dragging', 'resizing'].includes(key)))) as never[], edges: edges.map((edge) => Object.fromEntries(Object.entries(edge).filter(([key]) => key !== 'selected'))) as never[], viewport }), [nodes, edges, viewport])
  const documentRef = useRef(document)
  documentRef.current = document
  versionRef.current = version

  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; agentAbort.current?.abort() } }, [])

  useEffect(() => {
    const expire = () => { setSessionExpired(true); agentAbort.current?.abort() }
    window.addEventListener(STUDIO_SESSION_EXPIRED, expire)
    return () => window.removeEventListener(STUDIO_SESSION_EXPIRED, expire)
  }, [])

  useEffect(() => {
    if (!validProjectId) return
    let active = true
    const token = localStorage.getItem('token')
    const controller = new AbortController()
    const isCurrent = () => active && token === localStorage.getItem('token') && workspaceEpoch === workspaceScope.epoch
    setCanvasReady(false); setLoadIssue(null)
    void loadStudioCanvas({
      syncWorkspace: async () => { setWorkspaceTeam(null); await projectSharingApi.info(projectId) },
      loadCanvas: () => printfilmStudioApi.getCanvas(projectId, controller.signal),
      isCurrent,
      onReady: (result) => {
        // Retrying a connection/space lookup must never discard local edits.
        if (dirtyRef.current) { setCanvasReady(true); setStatus('已恢复连接，保留未保存修改'); return }
        const doc = decodeCanvasDocument(result.document)
        documentExtrasRef.current = doc
        setNodes(doc.nodes as Node<Data>[])
        setEdges(doc.edges as Edge[])
        setViewport(doc.viewport)
        setFlowKey((key) => key + 1)
        setVersion(result.version)
        setCanvasReady(true)
        setStatus('已同步')
      },
      onError: (issue) => { setLoadIssue(issue); setStatus(issue.title) },
    })
    return () => { active = false; controller.abort() }
  }, [projectId, validProjectId, workspaceEpoch, loadAttempt, setEdges, setNodes])

  useEffect(() => {
    if (!canvasReady || sessionExpired) return
    let active = true
    void projectSharingApi.info(projectId).then((project) => { if (active) { setProjectTitle(project.title || ''); setProjectOwner(project.is_owner) } }).catch(() => undefined)
    void printfilmStudioApi.listSessions(projectId).then((result) => { if (active && result.sessions.length) setSessionId((current) => current || result.sessions[0].id) }).catch(() => undefined)
    return () => { active = false }
  }, [canvasReady, projectId, sessionExpired])

  useEffect(() => {
    if (!canvasReady || !validProjectId) return
    let active = true, fetching = false, lastStatus = ''
    const refresh = async () => {
      if (fetching || savingRef.current) return
      fetching = true
      try {
        const result = await printfilmStudioApi.workflowStatus(projectId)
        if (!active) return
        const running = result.run?.status === 'running'
        const stateKey = result.run ? `${result.run.id}:${result.run.status}:${result.run.completed}` : ''
        if (result.run && stateKey !== lastStatus) {
          lastStatus = stateKey
          setStatus(running ? `后台运行中 · ${result.run.completed} / ${result.run.count}，可继续编辑` : result.run.error || '节点运行完成')
          if (!running) void api.wallet().then(setWallet).catch(() => undefined)
        }
        if (!dirtyRef.current && result.version > versionRef.current) {
          const doc = decodeCanvasDocument(result.document)
          documentExtrasRef.current = doc; documentRef.current = doc
          nodesRef.current = doc.nodes as Node<Data>[]; edgesRef.current = doc.edges as Edge[]
          setNodes(doc.nodes as Node<Data>[]); setEdges(doc.edges as Edge[])
          versionRef.current = result.version; setVersion(result.version)
          setStatus(running && result.run ? `后台运行中 · ${result.run.completed} / ${result.run.count}，可继续编辑` : result.run?.error || '已同步项目画布')
        }
      } catch (error) {
        if (active && [403, 404].includes(Number((error as { status?: number }).status))) setLoadIssue(workspaceIssue(error))
      }
      finally { fetching = false }
    }
    void refresh(); const timer = window.setInterval(() => { void refresh() }, 2000)
    return () => { active = false; window.clearInterval(timer) }
  }, [canvasReady, validProjectId, projectId, setNodes, setEdges])
  useEffect(() => () => { agentAbort.current?.abort() }, [])
  useEffect(() => {
    if (!sessionId || agentAbort.current) return
    let active = true
    const controller = new AbortController()
    void printfilmStudioApi.getSession(sessionId).then(async (session) => {
      if (!active || agentAbort.current) return
      setAgentEvents(sessionEvents(session))
      agentAnswerRef.current = ''; setAnswer('')
      if (session.run?.status === 'running') {
        agentAbort.current = controller
        setAgentRunning(true); setStatus('正在恢复 Agent 执行…')
        try { await printfilmStudioApi.resume(sessionId, session.run.id, (event) => agentHandlerRef.current(event), controller.signal); if (active && !controller.signal.aborted) { const restored = await printfilmStudioApi.getSession(sessionId); if (active) setAgentEvents(sessionEvents(restored)) } }
        finally { if (agentAbort.current === controller) { agentAbort.current = null; if (active) setAgentRunning(false) } }
      }
    }).catch((error) => { if (active && !controller.signal.aborted) setStatus(error instanceof Error ? error.message : '会话恢复失败') })
    return () => { active = false; controller.abort() }
  }, [sessionId])
  useEffect(() => {
    if ((!assetsOpen && !composerOpen && !agentOpen) || !validProjectId) return
    let active = true
    printfilmStudioApi.getAssets(projectId).then((result) => active && setAssets(result.assets || [])).catch((error) => { if (active) setStatus(error instanceof Error ? error.message : '素材库加载失败') })
    return () => { active = false }
  }, [assetsOpen, composerOpen, agentOpen, projectId, validProjectId])
  const taskListRefreshKey = nodes.filter(node=>node.data.taskId).map(node=>`${node.data.taskId}:${node.data.status || ''}`).sort().join('|')
  useEffect(() => {
    if (!bottomOpen || !validProjectId) return
    let active = true
    void tasksApi.list({ domain:'studio', drama_project_id:projectId, page_size:30 }).then(result=>{if(active)setTasks(result.items || [])}).catch(()=>undefined)
    return ()=>{active=false}
  }, [bottomOpen, projectId, validProjectId, taskListRefreshKey])
  useEffect(() => {
    if (!validProjectId) return
    let active = true
    void api.wallet().then((value) => { if (active) setWallet(value) }).catch(() => undefined)
    return () => { active = false }
  }, [validProjectId])
  useEffect(() => { setHiddenRefIds([]) }, [selectedNodeId])
  useEffect(() => {
    if (!validProjectId) return
    let active = true
    const terminal = new Set(['completed', 'succeeded', 'failed', 'cancelled'])
    /** 按节点上的工具任务号轮询，把状态和成片写回画布。 */
    const refresh = async () => {
      const pending = nodesRef.current.filter((node) => {
        const taskId = String(node.data.taskId || '')
        return taskId.startsWith('task-') && !terminal.has(String(node.data.status || ''))
      })
      if (!pending.length) return
      let queried: Awaited<ReturnType<typeof queryStudioTasks>>
      try {
        queried = await queryStudioTasks(pending.slice(0, 50).map((node) => String(node.data.taskId)), projectId)
      } catch {
        return
      }
      if (!active) return
      const composited = new globalThis.Map<string, ProjectAsset>()
      const compositeErrors = new globalThis.Map<string, string>()
      const invalidCompositeTasks = new Set<string>()
      for (const node of nodesRef.current) {
        const taskId = String(node.data.taskId || '')
        const hit = queried.data.find((item) => item.id === taskId)
        const raw = hit?.result?.urls?.[0]
        if (!node.data.inpaint || !raw || !canEdit) continue
        try {
          let work = compositesRef.current.get(taskId)
          if (!work) {
            const inpaint = node.data.inpaint as InpaintData
            work = withProjectMedia([inpaint.originalUrl, inpaint.maskUrl, resolveToolMediaUrl(raw) || raw], projectId, ([originalUrl, maskUrl, generatedUrl]) => finishInpaint({ ...inpaint, originalUrl, maskUrl }, generatedUrl)).then((blob) => printfilmStudioApi.uploadAsset(projectId, new File([blob], '局部重绘.png', { type: 'image/png' }), editLockRequestHeaders(canvasTarget)))
            compositesRef.current.set(taskId, work)
          }
          composited.set(taskId, await work)
        } catch (e) { compositesRef.current.delete(taskId); compositeErrors.set(taskId, e instanceof Error ? e.message : '蒙版合成失败'); if (e instanceof InpaintAspectMismatchError) invalidCompositeTasks.add(taskId) }
      }
      if (!active) return
      const current = nodesRef.current
      let changed = false
      const next = current.map((node) => {
        const taskId = String(node.data.taskId || '')
        const hit = queried.data.find((item) => item.node_id === node.id || item.id === taskId)
        if (!hit) return node
        const completedMask = composited.get(taskId)
        if (node.data.inpaint && !completedMask && hit.result?.urls?.length) {
          const error = compositeErrors.get(taskId) || '等待可编辑状态完成蒙版合成'
          if (node.data.error === error) return node
          changed = true; return { ...node, data: { ...node.data, status: invalidCompositeTasks.has(taskId) ? 'failed' : 'awaiting_composite', error } }
        }
        const urls = (completedMask?.url ? [completedMask.url] : hit.result?.urls || []).map((item) => resolveToolMediaUrl(item) || item).filter(Boolean)
        const status = hit.status === 'succeeded' ? 'completed' : hit.generation_stage === 'queued' ? 'queued' : hit.status
        const nextData = {
          ...node.data,
          status,
          canCancel: hit.can_cancel === true,
          generationStage: hit.generation_stage,
          ...(hit.error ? { error: hit.error } : { error: undefined }),
          ...(completedMask ? { assetId: completedMask.id, inpaintCompleted: true } : hit.asset_id ? { assetId: hit.asset_id } : {}),
          ...(urls[0] ? { mediaUrl: urls[0] } : {}),
          ...(urls.length ? { mediaUrls: urls, mediaIndex: clampMediaIndex(node.data.mediaIndex, urls.length) } : {}),
        }
        if (JSON.stringify(nextData) === JSON.stringify(node.data)) return node
        changed = true
        return { ...node, data: nextData }
      })
      if (!changed) return
      setNodes(next)
      if (canEdit) { dirtyRef.current = true; setStatus('任务状态已更新') }
    }
    void refresh()
    const timer = window.setInterval(() => { void refresh() }, 4000)
    return () => { active = false; window.clearInterval(timer) }
  }, [canEdit, canvasTarget, projectId, setNodes, validProjectId])
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || window.document.fullscreenElement || keyboardBlockedRef.current || !isCanvasKeyboardTarget(event.target)) return
      const action = canvasShortcut(event)
      if (!action || action === 'copy' && window.getSelection()?.toString()) return
      event.preventDefault()
      if (action === 'pan') { setSpacePan(true); return }
      commandRef.current[action]?.()
    }
    const release = (event: KeyboardEvent) => { if (event.code === 'Space' || event.key === ' ') setSpacePan(false) }
    const reset = () => setSpacePan(false)
    const onVisibility = () => { if (window.document.hidden) reset() }
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('keyup', release, true)
    window.addEventListener('blur', reset)
    window.document.addEventListener('visibilitychange', onVisibility)
    return () => { window.removeEventListener('keydown', onKeyDown); window.removeEventListener('keyup', release, true); window.removeEventListener('blur', reset); window.document.removeEventListener('visibilitychange', onVisibility) }
  }, [])

  useEffect(() => {
    if (!contextMenu && !paneAddMenu) return
    const closeOutside = (event: PointerEvent) => {
      if (event.target instanceof Element && event.target.closest('.pf-context-menu,.pf-pane-add,.pf-toolbar-primary')) return
      setContextMenu(null); setPaneAddMenu(null)
    }
    window.addEventListener('pointerdown', closeOutside)
    return () => window.removeEventListener('pointerdown', closeOutside)
  }, [contextMenu, paneAddMenu])

  const markDirty = () => { if (!canEdit) { setStatus(loadIssue?.message || '当前画布为只读模式'); return }; dirtyRef.current = true; setStatus('有未保存修改') }
  const handleNodesChange = (changes: Parameters<typeof onNodesChange>[0]) => {
    const allowed = canEdit ? changes : changes.filter((change) => change.type === 'select' || change.type === 'dimensions')
    const drag = dragCopyRef.current
    if (drag && canEdit) {
      const positions = allowed.flatMap((change) => change.type === 'position' && drag.copies.has(change.id) ? [{ id: change.id, position: change.position }] : [])
      onNodesChange(allowed.filter((change) => change.type !== 'position' || !drag.copies.has(change.id)))
      if (positions.length) setNodes((current) => moveStudioDragCopy(current, drag, positions) as Node<Data>[])
    } else onNodesChange(allowed)
    if (allowed.some((change) => change.type !== 'select' && (change.type !== 'dimensions' || change.resizing !== undefined))) markDirty()
  }
  /** 选中集合没变时保持原引用，避免 React Flow 每次同步选择都触发重渲染。 */
  const onSelectionChange = useCallback(({ nodes: picked }: { nodes: { id: string }[] }) => {
    const ids = picked.map((node) => node.id)
    setSelectedNodeIds((current) => (current.length === ids.length && current.every((id, index) => id === ids[index]) ? current : ids))
  }, [])
  const handleEdgesChange = (changes: Parameters<typeof onEdgesChange>[0]) => { const allowed = canEdit ? changes : changes.filter((change) => change.type === 'select'); onEdgesChange(allowed); if (allowed.some((change) => change.type !== 'select')) markDirty() }
  const addNode = (type: string, asset?: Asset, extras: Record<string, unknown> = {}, at?: { x: number; y: number }, select = true) => {
    if (!canEdit) { setStatus(loadIssue?.message || '当前画布为只读模式'); return null }
    const created: Node<Data> = { ...newNode(type, nodesRef.current.length, extras), selected: select, data: { ...defaultNodeData(type), label: asset?.name || `新${nodeLabel[type] || '节点'}`, assetId: asset?.id, mediaUrl: asset?.url || asset?.cover || undefined, mediaType: asset ? assetMediaKind(asset) : undefined, status: asset ? 'completed' : undefined, hint: extras.hint, editor: extras.editor, ...extras } }
    const bounds = window.document.querySelector('.pf-flow-area')?.getBoundingClientRect()
    if (bounds) {
      const library = window.document.querySelector('.pf-library')?.getBoundingClientRect()
      const left = library ? Math.max(bounds.left, Math.min(library.right + 16, bounds.right - 240)) : bounds.left
      const occupied = [...window.document.querySelectorAll<HTMLElement>('.react-flow__node:not(.react-flow__node-group)')].map((element) => element.getBoundingClientRect())
      created.position = newNodePosition(bounds, { left, top: bounds.top, width: bounds.right - left, height: bounds.height }, flow?.getViewport() || viewport, { width: mediaNodeWidth(nodeMediaKind(created)), height: 220 }, at, occupied)
    }
    if (!select && selectedNodeId) {
      const host = nodesRef.current.find((node) => node.id === selectedNodeId)
      if (host) created.position = { x: host.position.x - 300, y: host.position.y }
    }
    const next = [...nodesRef.current.map((node) => select && node.selected ? { ...node, selected: false } : node), created]
    const composeEdges=type==='compose'?nodesRef.current.filter(node=>node.selected&&nodeMediaKind(node)==='video').map(node=>({id:`edge-${crypto.randomUUID()}`,source:node.id,target:created.id})):[]
    commitGraph(next, [...edgesRef.current,...composeEdges], `已添加${created.data.label}，正在保存`)
    // The composer opens in this same event; it must be able to read the new node.
    nodesRef.current = next
    if (select) { setSelectedNodeId(created.id); setSelectedNodeIds([created.id]); setPanelsSuppressed(false); setComposerOpen(false) }
    return created
  }
  const openSelectionComposer = (action: ComposerAction, seedPrompt?: string, nodeId = selectedNodeId) => {
    const source = nodeId ? nodesRef.current.find((node) => node.id === nodeId) : undefined
    if (nodeId) setSelectedNodeId(nodeId)
    setNodes((current) => current.map((node) => node.selected === (node.id === nodeId) ? node : { ...node, selected: node.id === nodeId }))
    setSelectionAction(action)
    if (source) {
      setGenModel(String(source.data.modelId || resolveCatalogModelSelection(mediaCatalog, action === 'video' ? 'video' : 'image', '')))
      setOutputVideoMode(VIDEO_MODES.some((mode) => mode.id === source.data.videoMode) ? source.data.videoMode as StudioVideoMode : undefined)
      setOutputVoice(String(source.data.voice || 'narrator_calm'))
      setOutputAudio(source.data.generateAudio !== false)
      setOutputRatio(String(source.data.ratio || (['video','reference','compose'].includes(action)?'16:9':'2:3'))); setOutputCount(String(source.data.count || '1')); setOutputDuration(String(source.data.duration || '7'))
      if (source.data.resolution) { setOutputResolution(String(source.data.resolution)); setImageResolution(String(source.data.resolution)) }
    }
    setComposerOpen(true)
    setBottomOpen(false)
    setPanelsSuppressed(false)
    // Include the real top toolbar and bottom composer when bringing a node into view.
    window.requestAnimationFrame(() => window.requestAnimationFrame(() => {
      if (!mountedRef.current || !flow) return
      const nodeElement = [...window.document.querySelectorAll<HTMLElement>('.react-flow__node')].find((element) => element.dataset.id === nodeId)
      const area = window.document.querySelector('.pf-flow-area')?.getBoundingClientRect()
      if (!nodeElement || !area) return
      const footer = window.document.querySelector('.pf-studio-footer:not([hidden])')?.getBoundingClientRect()
      const availableBottom = Math.min(area.bottom - 80, footer ? footer.top - 20 : area.bottom - 80)
      const rects = [nodeElement, ...nodeElement.querySelectorAll('.pf-skel-slot')].map((element) => element.getBoundingClientRect())
      const left = Math.min(...rects.map((rect) => rect.left)), top = Math.min(...rects.map((rect) => rect.top))
      const right = Math.max(...rects.map((rect) => rect.right)), bottom = Math.max(...rects.map((rect) => rect.bottom))
      if (left >= area.left + 24 && right <= area.right - 24 && top >= area.top + 80 && bottom <= availableBottom) return
      const current = flow.getViewport(), point = flow.screenToFlowPosition({ x: left, y: top })
      void flow.setViewport(getViewportForBounds({ ...point, width: (right - left) / current.zoom, height: (bottom - top) / current.zoom }, area.width, Math.max(200, availableBottom - area.top), 0.15, current.zoom, 0.18), { duration: 300 })
    }))
    if (source?.data.storyKind === 'shot_video') {
      const promptNode = nodesRef.current.find((node) => node.id === source.data.promptNodeId)
      setGenPrompt(String(promptNode?.data.text || ''))
      setOutputVideoMode('omni_reference')
      return
    }
    if (seedPrompt !== undefined) { setGenPrompt(seedPrompt); return }
    if (source?.data.prompt && (source.data.editor === action || action === 'video' && nodeMediaKind(source) === 'video')) { setGenPrompt(String(source.data.prompt)); return }
    if (action === 'video') setGenPrompt('把当前图片生成一段视频，保持角色和场景一致')
    else if (action === 'reference') setGenPrompt('参考当前图片生成视频，保持镜头构图和角色连续性')
    else if (action === 'edit') setGenPrompt(source ? nodeDraft(source) : '')
    else if (action === 'audio') setGenPrompt(String(source?.data.text || source?.data.prompt || '朗读当前节点的文本'))
    else if (action === 'inpaint') setGenPrompt('保留构图，只重绘画面中需要修改的局部区域')
    else if (action === 'outpaint') setGenPrompt('向外扩展画幅，补全边缘并保持风格一致')
    else if (action === 'compose') setGenPrompt('按时间顺序拼接已连接的视频片段，统一节奏与转场')
    else if (action === 'crop') setGenPrompt('')
  }
  const openNodeEditor = (id: string) => {
    const node = nodesRef.current.find(item => item.id === id)
    if (!node) return
    setContextMenu(null); setPaneAddMenu(null); setSelectedNodeId(id); setSelectedNodeIds([id]); setPanelsSuppressed(false)
    setNodes(current => current.map(item => item.selected === (item.id===id) ? item : {...item,selected:item.id===id}))
    if (node.type==='compose') {setComposerOpen(false);setTextGenerationNodeId(null);return}
    if (node.type==='group') {setComposerOpen(false);setTextGenerationNodeId(null);return}
    if (!canEdit || submittingNodeIds.has(id) || ['queued','running','awaiting_composite'].includes(String(node.data.status))) return
    if (nodeMediaKind(node) === 'text') { setComposerOpen(false); setTextGenerationNodeId(id); return }
    if (node.type === 'frameAnalysis') return
    setTextGenerationNodeId(null); setHiddenRefIds([])
    openSelectionComposer(nodeMediaKind(node) === 'video' ? 'video' : nodeMediaKind(node) === 'audio' ? 'audio' : 'edit', nodeDraft(node), id)
  }
  const selectCanvasNode = (event: MouseEvent, node: Node<Data>) => {
    if (tool === 'hand' || spacePan || event.shiftKey || event.ctrlKey || event.metaKey || event.altKey) return
    if ((event.target as HTMLElement)?.closest('button,a,input,textarea,video,audio,[contenteditable],.react-flow__handle')) return
    if (node.id === selectedNodeId && (composerOpen || textGenerationNodeId === node.id)) {setPanelsSuppressed(false);return}
    openNodeEditor(node.id)
  }
  const clickCanvasPane = (event: MouseEvent) => {
    setContextMenu(null); setPaneAddMenu(null); setPanelsSuppressed(false)
    if (event.detail === 2) {openPaneAddMenu(event);return}
    if (tool === 'select' && !spacePan && !event.shiftKey && !event.ctrlKey && !event.metaKey && !event.altKey) {
      // Screen pixels keep the forgiving click area consistent at every zoom.
      let nearest: {id:string;distance:number} | undefined
      for (const element of window.document.querySelectorAll<HTMLElement>('.react-flow__node:not(.react-flow__node-group)')) {
        const rect=element.getBoundingClientRect()
        if (!rect.width || !rect.height) continue
        const dx=Math.max(rect.left-event.clientX,0,event.clientX-rect.right)
        const dy=Math.max(rect.top-event.clientY,0,event.clientY-rect.bottom)
        const distance=Math.hypot(dx,dy)
        if (distance<=18 && element.dataset.id && (!nearest || distance<nearest.distance)) nearest={id:element.dataset.id,distance}
      }
      if(nearest){openNodeEditor(nearest.id);return}
    }
    setSelectedNodeId(null);setComposerOpen(false);setTextGenerationNodeId(null)
  }
  const addFromCatalog = (item: NodeCatalogItem, at?: { x: number; y: number }) => {
    if (item.type === 'group') { createCategoryFrame(at); setTool('select'); setPaneAddMenu(null); return }
    if (item.action === 'upload') { uploadRef.current?.click(); setTool('select'); setPaneAddMenu(null); return }
    if (item.action === 'assets') { setAssetsOpen(true); setTool('select'); setPaneAddMenu(null); return }
    if (item.action === 'history') { setHistoryOpen(true); setTool('select'); setPaneAddMenu(null); return }
    if (!item.type) return
    const created = addNode(item.type, undefined, { hint: item.hint, editor: item.editor }, at)
    setTool('select')
    setPaneAddMenu(null)
    if (!created) return
    if (item.type === 'director3d') setDirectorNodeId(created.id)
    if (item.editor === 'inpaint' || item.editor === 'outpaint' || item.editor === 'compose' || item.editor === 'video' || item.editor === 'edit' || item.editor === 'audio' || item.editor === 'reference') {
      openSelectionComposer(item.editor, item.hint ? `${item.hint}。` : undefined, created.id)
    }
  }
  const pickHistoryRun = (run: ToolRunRecord) => {
    const media = resolveToolMediaUrl(run.urls?.[0] || run.preview_url)
    const kind = String(run.kind || run.tool_id || '').toLowerCase()
    const type = kind.includes('video') || kind.includes('t2v') ? 'video' : kind.includes('audio') ? 'audio' : 'image'
    addNode(type, undefined, { label: (run.prompt || NODE_TYPE_LABEL[type] || '历史媒体').slice(0, 24), mediaUrl: media || undefined, prompt: run.prompt || '', status: 'completed', taskId: run.task_id || undefined })
    setHistoryOpen(false)
    setStatus('已从生成历史放入画布')
  }
  const connect = (connection: Connection) => {
    if (!canEdit) { setStatus(loadIssue?.message || '当前画布为只读模式'); return }
    const invalid = validateStudioConnection(connection, nodesRef.current, edgesRef.current)
    if (invalid) { setStatus(invalid); return }
    commitGraph(nodesRef.current, addEdge({ ...connection, id: `edge-${Date.now()}`, type: 'default', style: { stroke: '#c4c9d2', strokeWidth: 1.5 } }, edgesRef.current), '已连接节点')
  }
  /** 仅在拖移/缩放结束时写回视口；不要用受控 viewport+onViewportChange（会触发 StoreUpdater 死循环）。 */
  const onMoveEnd = useCallback((_: unknown, next: Viewport) => {
    setViewport((prev) => {
      if (prev.x === next.x && prev.y === next.y && prev.zoom === next.zoom) return prev
      // Panning a loading/readonly canvas is navigation, not a local edit.
      if (canEditRef.current) { dirtyRef.current = true; setStatus('有未保存修改') }
      return next
    })
  }, [])
  const save = useCallback(async () => {
    // A click during autosave must wait for that write, not report a fake conflict.
    while (savingRef.current && saveCompletionRef.current) await saveCompletionRef.current
    if (!mountedRef.current || !validProjectId || !canEdit || savingRef.current || saveBlockedRef.current) return false
    savingRef.current = true
    let finishSave!: () => void
    saveCompletionRef.current = new Promise<void>((resolve) => { finishSave = resolve })
    const snapshot = documentRef.current
    const payload = JSON.stringify(snapshot)
    setStatus('保存中…')
    try {
      const result = await printfilmStudioApi.saveCanvas(projectId, snapshot, versionRef.current, editLockRequestHeaders(canvasTarget))
      if (!mountedRef.current) return false
      storeSnapshot(projectId, snapshot, result.version)
      versionRef.current = result.version
      setVersion(result.version)
      dirtyRef.current = JSON.stringify(documentRef.current) !== payload
      setStatus(dirtyRef.current ? '有未保存修改' : '已保存')
      presence.update({action:'saved',positions:[]})
      return !dirtyRef.current
    } catch (error) {
      if (!mountedRef.current) return false
      if ((error as { status?: number }).status === 409) {
        saveBlockedRef.current = true
        setStatus('画布版本冲突，已保留本地修改。请先导出画布，再刷新核对服务端内容')
      } else {
        if ([403, 404].includes(Number((error as { status?: number }).status))) setLoadIssue(workspaceIssue(error))
        setStatus(error instanceof Error ? error.message : '保存失败')
      }
      return false
    } finally { savingRef.current = false; saveCompletionRef.current = null; finishSave() }
  }, [canEdit, canvasTarget, projectId, validProjectId])
  useEffect(() => {
    if (!validProjectId || !dirtyRef.current || saveBlockedRef.current) return
    const timer = window.setTimeout(() => { void save() }, 1200)
    return () => window.clearTimeout(timer)
  }, [nodes, edges, viewport, version, projectId, validProjectId, save])
  agentHandlerRef.current = (event) => {
    if (!mountedRef.current) return
    const type = String(event.type || 'event')
    if (type === 'message_start') { agentAnswerRef.current = ''; setAnswer('') }
    if (type === 'message_delta') { agentAnswerRef.current += String(event.content || ''); setAnswer(agentAnswerRef.current) }
    if (['thinking', 'tool_start', 'tool_result', 'canvas_patch', 'task_created', 'error', 'reconnecting', 'proposal'].includes(type)) setAgentEvents((events) => [...events, eventFromWire(event)])
    if (type === 'canvas_updated' && Number(event.version) > versionRef.current) void printfilmStudioApi.getCanvas(projectId).then((result) => {
      if (!mountedRef.current || result.version <= versionRef.current) return
      if (dirtyRef.current || savingRef.current) { saveBlockedRef.current = true; setStatus('Agent 更新与本地编辑冲突，已保留本地修改，请导出后刷新核对'); return }
      const doc = decodeCanvasDocument(result.document)
      documentExtrasRef.current = doc; setNodes(doc.nodes as Node<Data>[]); setEdges(doc.edges as Edge[]); setViewport(doc.viewport); setFlowKey((key) => key + 1); versionRef.current = result.version; setVersion(result.version)
    }).catch(() => setStatus('画布更新读取失败，请刷新核对'))
    if (type === 'done') {
      const content = agentAnswerRef.current
      if (content) setAgentEvents((events) => [...events, { type: 'assistant', text: content }])
      agentAnswerRef.current = ''; setAnswer('')
      if (!saveBlockedRef.current) setStatus(event.status === 'cancelled' ? 'Agent 已停止' : event.status === 'failed' ? 'Agent 执行失败，已保留完成步骤' : 'Agent 已完成')
    }
  }
  const askAgent = async (options: AgentOptions = {}, model = '', references: AgentReference[] = [], messageOverride?: string) => {
    const message = (messageOverride ?? prompt).trim()
    if (!validProjectId || !message || agentRunning || agentAbort.current || proposalBusyRef.current) return
    if (dirtyRef.current && !(await save())) { setStatus('请先保存当前画布并处理冲突，再发送给 Agent'); return }
    setPrompt(''); setAnswer(''); agentAnswerRef.current = ''
    setAgentEvents((events) => [...events, { type: 'user', text: message, references: structuredClone(references) }])
    setAgentRunning(true); setStatus('Agent 处理中…')
    const controller = new AbortController()
    agentAbort.current = controller
    try {
      const session = sessionId ? { id: sessionId } : await printfilmStudioApi.createSession(projectId)
      if (!mountedRef.current) return
      await printfilmStudioApi.updateSession(session.id, { model_id: model || null })
      setSessionId(session.id)
      await printfilmStudioApi.stream(session.id, message, (event) => agentHandlerRef.current(event), controller.signal, editLockRequestHeaders(canvasTarget), { ...options, review_changes: true })
      if (!controller.signal.aborted && mountedRef.current) { const restored = await printfilmStudioApi.getSession(session.id); if (mountedRef.current && agentAbort.current === controller) setAgentEvents(sessionEvents(restored)) }
    } catch (error) {
      if (!controller.signal.aborted && mountedRef.current) { setAgentEvents((events) => [...events, { type: 'error', text: error instanceof Error ? error.message : 'Agent 执行失败' }]); setStatus('Agent 连接失败，可刷新恢复当前执行') }
    } finally { if (agentAbort.current === controller) { agentAbort.current = null; if (mountedRef.current) setAgentRunning(false) } }
  }
  const repairAgentStory = async (scriptId: string) => {
    if (!canEdit || agentRunning) return
    if (dirtyRef.current && !(await save())) throw new Error('请先保存当前画布并处理冲突')
    const result = await printfilmStudioApi.repairStory(projectId, scriptId, versionRef.current, editLockRequestHeaders(canvasTarget))
    if (!mountedRef.current) return
    if (dirtyRef.current || savingRef.current) { saveBlockedRef.current = true; throw new Error('修复已保存，但与本地编辑冲突，请刷新核对') }
    const doc = decodeCanvasDocument(result.document)
    pastRef.current = [...pastRef.current, { nodes: nodesRef.current, edges: edgesRef.current }].slice(-40)
    futureRef.current = []
    documentExtrasRef.current = doc; nodesRef.current = doc.nodes as Node<Data>[]; edgesRef.current = doc.edges as Edge[]
    setNodes(nodesRef.current); setEdges(edgesRef.current); setViewport(doc.viewport); setFlowKey((key) => key + 1)
    versionRef.current = result.version; setVersion(result.version); setStatus('已补齐场景、分镜提示词和视频节点连线')
  }
  const changeAgentProposal = async (proposal: AgentProposal, action: ProposalAction) => {
    if (!canEditRef.current || agentRunning || proposalBusyRef.current) throw new Error('请等待当前操作完成，并确认画布可编辑')
    proposalBusyRef.current = true; setProposalBusy(true)
    try {
      if (dirtyRef.current && !(await save())) throw new Error('请先保存画布并处理冲突')
      const candidate = applyProposal(documentRef.current, proposal, action)
      const result = await printfilmStudioApi.saveCanvas(projectId, candidate, versionRef.current, editLockRequestHeaders(canvasTarget))
      if (!mountedRef.current) return
      if (dirtyRef.current || savingRef.current) { saveBlockedRef.current = true; throw new Error('改动已保存，但与本地编辑冲突，请刷新核对') }
      const doc = decodeCanvasDocument(result.document)
      pastRef.current = [...pastRef.current, { nodes: nodesRef.current, edges: edgesRef.current }].slice(-40); futureRef.current = []
      documentExtrasRef.current = doc; documentRef.current = doc
      nodesRef.current = doc.nodes as Node<Data>[]; edgesRef.current = doc.edges as Edge[]
      setNodes(nodesRef.current); setEdges(edgesRef.current)
      versionRef.current = result.version; setVersion(result.version)
      const ids = proposal.nodes.filter((change) => !change.before && change.after?.type !== 'group').map((change) => change.id)
      if (action === 'apply' && ids.length) { setSelectedNodeIds(ids); setSelectedNodeId(ids[0]); requestAnimationFrame(() => { void flow?.fitView({ nodes: ids.map((id) => ({ id })), padding: .15, duration: 400 }) }) }
      setStatus(action === 'apply' ? '已应用这批节点与分组' : action === 'undo' ? '已撤销这批改动' : '已忽略这批改动')
    } finally { proposalBusyRef.current = false; if (mountedRef.current) setProposalBusy(false) }
  }
  const stopAgent = async () => {
    if (!sessionId) return
    try { await printfilmStudioApi.stopSession(sessionId); setStatus('已请求停止，正在取消关联任务…') }
    catch (error) { setStatus(error instanceof Error ? error.message : '停止失败') }
  }
  // Edge filtering only depends on node roles, not drag positions or measurements.
  const edgeRoles=JSON.stringify(nodes.map(node=>[node.id,node.data.storyKind]))
  const displayedEdges=useMemo(()=>showEdges ? visibleStoryEdges(nodes,edges,[...selectedNodeIds,...(selectedNodeId?[selectedNodeId]:[])],focusStoryEdges) : [],[edges,edgeRoles,selectedNodeIds,selectedNodeId,showEdges,focusStoryEdges])
  const selectedNode = selectedNodeId ? nodes.find((node) => node.id === selectedNodeId) : undefined
  useEffect(() => {
    setComposerChips([])
  }, [selectedNodeId])

  const linkedRefs = useMemo(()=>linkedNodeReferences(selectedNode,nodes,edges),[selectedNode,nodes,edges])
  const incompatibleRefs = selectedNode ? linkedRefs.filter((node) => validateStudioConnection({ source: node.id, target: selectedNode.id }, nodes, edges.filter((edge) => !(edge.source === node.id && edge.target === selectedNode.id)))) : []
  const mediaOf = (node: Node<Data>) => String(node.data.mediaUrl || node.data.url || node.data.cover || '')
  /** 引用画布节点：从参考图连到当前节点。 */
  const citeNode = (sourceId: string, targetId = selectedNodeId) => {
    if (!canEdit || !targetId || sourceId === targetId) return
    const existing = edgesRef.current.some((edge) => edge.source === sourceId && edge.target === targetId)
    const invalid = existing ? undefined : validateStudioConnection({ source: sourceId, target: targetId }, nodesRef.current, edgesRef.current)
    if (invalid) { setStatus(invalid); return }
    setEdges((current) => current.some((edge) => edge.source === sourceId && edge.target === targetId) ? current : [...current, { id: `edge-cite-${sourceId}-${targetId}`, source: sourceId, target: targetId, type: 'default', style: { stroke: '#8b7cf7', strokeWidth: 1.6 } }])
    setHiddenRefIds((ids) => ids.filter((id) => id !== sourceId))
    dirtyRef.current = true
    setStatus('已引用并连线')
  }
  const pickMention = (item: { id: string; source: 'node' | 'asset'; label?: string; url?: string; mediaKind?: string }) => {
    if (selectedNodeId) {
      const node = nodesRef.current.find((entry) => entry.id === item.id)
      const asset = assets.find((entry) => String(entry.id) === item.id)
      const reference: PromptReference = { ...item, label: item.label || String(node?.data.label || asset?.name || '参考素材'), url: item.url || (node ? mediaOf(node) : asset?.url || undefined) }
      setNodes((current) => current.map((entry) => entry.id === selectedNodeId ? { ...entry, data: { ...entry.data, promptReferences: [...(Array.isArray(entry.data.promptReferences) ? entry.data.promptReferences as PromptReference[] : []).filter((ref) => ref.id !== item.id || ref.source !== item.source), reference] } } : entry))
    }
    if (item.source === 'node') { citeNode(item.id); return }
    const asset = assets.find((entry) => String(entry.id) === item.id)
    if (!asset) return
    const existing = selectedNodeId && referenceAssetNode(nodesRef.current, asset, selectedNodeId, edgesRef.current)
    if (existing) { citeNode(existing.id); return }
    const created = addNode(assetMediaKind(asset), asset, {}, undefined, false)
    if (created) citeNode(created.id)
  }
  const downloadCanvas = () => {
    const blob = new Blob([JSON.stringify(document, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const anchor = window.document.createElement('a')
    anchor.href = url
    anchor.download = `printfilm-studio-project-${projectId}.json`
    anchor.click()
    URL.revokeObjectURL(url)
    setStatus('画布已导出')
  }
  const shareWorkspace = async () => {
    const shareUrl = window.location.href
    try { await navigator.clipboard?.writeText(shareUrl); setStatus('工作区链接已复制') } catch { setStatus('工作区链接：请从地址栏复制') }
  }
  const resetCanvas = async () => {
    if (!validProjectId || !canEdit || !window.confirm('清空当前 Printfilm Studio 画布？已保存的节点和连线会被移除。')) return
    try {
      const result = await printfilmStudioApi.resetCanvas(projectId, editLockRequestHeaders(canvasTarget))
      saveBlockedRef.current = false
      const doc = decodeCanvasDocument(result.document)
      setNodes(doc.nodes as Node<Data>[]); setEdges(doc.edges as Edge[]); setViewport(doc.viewport); setFlowKey((key) => key + 1); setVersion(result.version); setSelectedNodeId(null); dirtyRef.current = false; setStatus('画布已重置')
    } catch (error) { setStatus(error instanceof Error ? error.message : '重置失败') }
  }

  const checkpointGraph = () => {
    if (!canEditRef.current) return
    pastRef.current = [...pastRef.current, { nodes: nodesRef.current, edges: edgesRef.current }].slice(-40)
    futureRef.current = []
  }
  const startNodeDrag = (event: globalThis.MouseEvent | TouchEvent, node: Node<Data>) => {
    draggingPresenceRef.current = true
    presence.update({action:'dragging',node_ids:[node.id],positions:[{id:node.id,...absoluteNodePosition(node,nodesRef.current)}]})
    setPanelsSuppressed(true); setContextMenu(null); setPaneAddMenu(null)
    dragCopyRef.current = null
    if (!canEdit) return
    checkpointGraph()
    if (!('altKey' in event) || !event.altKey || event.shiftKey) return
    const picked = node.selected ? new Set(nodesRef.current.filter((item) => item.selected).map((item) => item.id)) : new Set([node.id])
    const drag = createStudioDragCopy(nodesRef.current, edgesRef.current, picked, event.ctrlKey || event.metaKey)
    if (!drag.copies.size) return
    dragCopyRef.current = drag
    nodesRef.current = drag.nodes as Node<Data>[]; edgesRef.current = drag.edges
    setNodes(nodesRef.current); setEdges(drag.edges)
    setSelectedNodeIds([...drag.copies.values()]); setSelectedNodeId(drag.copies.values().next().value || null)
    setComposerOpen(false); markDirty()
  }
  const stopNodeDrag = (_event: globalThis.MouseEvent | TouchEvent, dragged: Node<Data>) => {
    draggingPresenceRef.current = false
    presence.update({action:'idle',positions:[]})
    const drag = dragCopyRef.current
    dragCopyRef.current = null
    if (drag) {
      setNodes((current) => current.map((node) => ({ ...node, dragging: false })))
      setStatus('已拖动复制节点')
    }
    if (canEdit && !drag && !dragged.parentId && dragged.type !== 'group') {
      const current = nodesRef.current
      const target = current.find((node) => node.type === 'group' && !node.parentId && !node.data.autoLayoutGroup && dragged.position.x >= node.position.x + 12 && dragged.position.y >= node.position.y + 40 && dragged.position.x + (dragged.measured?.width || 320) <= node.position.x + Number(node.style?.width || node.width || 600) - 12 && dragged.position.y + (dragged.measured?.height || 220) <= node.position.y + Number(node.style?.height || node.height || 400) - 12)
      if (target) {
        const next = current.map((node) => node.id === dragged.id ? { ...node, parentId: target.id, extent: 'parent' as const, position: { x: dragged.position.x - target.position.x, y: dragged.position.y - target.position.y } } : node.id === target.id ? { ...node, data: { ...node.data, children: [...new Set([...(Array.isArray(node.data.children) ? node.data.children : []), dragged.id])] } } : node)
        const frame = next.find((node) => node.id === target.id)!
        nodesRef.current = [frame, ...next.filter((node) => node.id !== target.id)]
        setNodes(nodesRef.current); markDirty(); setStatus('节点已归入分类框')
      }
    }
    setPanelsSuppressed(false)
  }
  // 画布写入统一走这里，保证撤销栈和自动保存使用同一份节点数据。
  const commitGraph = (nextNodes: Node<Data>[], nextEdges: Edge[], message: string) => {
    if (!canEdit) { setStatus(loadIssue?.message || '当前画布为只读模式'); return }
    pastRef.current = [...pastRef.current, { nodes: nodesRef.current, edges: edgesRef.current }].slice(-40)
    futureRef.current = []
    setNodes(nextNodes)
    setEdges(nextEdges)
    nodesRef.current = nextNodes; edgesRef.current = nextEdges
    dirtyRef.current = true
    setStatus(message)
  }
  const organizeWorkspace = () => {
    if (!canEditRef.current || tidyRunningRef.current) return
    if (!nodesRef.current.some((node) => node.type !== 'group')) { setStatus('先添加一些节点，再让小手来整理'); return }
    const before = nodesRef.current, plan = organizeCanvas(before, edgesRef.current)
    tidyRunningRef.current = true
    setComposerOpen(false); setBottomOpen(false); setSearchOpen(false); setPaneAddMenu(null); setContextMenu(null); setTool('select'); setViewMode('canvas')
    setSelectedNodeId(null); setSelectedNodeIds([]); setPanelsSuppressed(true)
    commitGraph(plan.nodes as Node<Data>[], edgesRef.current, `正在整理 ${plan.order.length} 个节点`)
    setTidyRun({ ...plan, id: Date.now(), before })
  }
  const chosenIds = () => nodesRef.current.filter((node) => node.selected).map((node) => node.id)
  const undoGraph = () => {
    if (!canEdit) return
    const previous = pastRef.current.pop()
    if (!previous || !canEdit) { setStatus(previous ? loadIssue?.message || '当前画布为只读模式' : '没有可撤销的操作'); return }
    futureRef.current.push({ nodes: nodesRef.current, edges: edgesRef.current })
    nodesRef.current = previous.nodes; edgesRef.current = previous.edges
    setNodes(previous.nodes); setEdges(previous.edges); dirtyRef.current = true; setStatus('已撤销')
    setSelectedNodeId(previous.nodes.find((node) => node.selected)?.id || null); setComposerOpen(false)
  }
  const redoGraph = () => {
    if (!canEdit) return
    const next = futureRef.current.pop()
    if (!next || !canEdit) { setStatus(next ? loadIssue?.message || '当前画布为只读模式' : '没有可重做的操作'); return }
    pastRef.current.push({ nodes: nodesRef.current, edges: edgesRef.current })
    nodesRef.current = next.nodes; edgesRef.current = next.edges
    setNodes(next.nodes); setEdges(next.edges); dirtyRef.current = true; setStatus('已重做')
    setSelectedNodeId(next.nodes.find((node) => node.selected)?.id || null); setComposerOpen(false)
  }
  const duplicateIds = (ids: string[]) => {
    if (!canEdit) return
    const result = duplicateStudioNodes(nodesRef.current, edgesRef.current, new Set(ids))
    if (!result.ids.length) { setStatus('请先选择要复制的节点'); return }
    commitGraph(result.nodes as Node<Data>[], result.edges, `已复制 ${result.ids.length} 个节点`)
    setSelectedNodeIds(result.ids); setSelectedNodeId(result.ids[0] || null)
  }
  const removeIds = (ids: string[]) => {
    if (!canEdit) return
    const selectedEdges = new Set(edgesRef.current.filter((edge) => edge.selected).map((edge) => edge.id))
    if (!ids.length && !selectedEdges.size) return
    const result = removeStudioNodes(nodesRef.current, edgesRef.current, new Set(ids))
    commitGraph(result.nodes as Node<Data>[], result.edges.filter((edge) => !selectedEdges.has(edge.id)), `已删除 ${ids.length} 个节点${selectedEdges.size ? `和 ${selectedEdges.size} 条连线` : ''}`)
    setSelectedNodeId(null); setSelectedNodeIds([]); setContextMenu(null); setInspectorOpen(false)
  }
  const copySelection = () => {
    const clip = captureStudioSelection(nodesRef.current, edgesRef.current, new Set(chosenIds()))
    if (!clip.nodes.length) { setStatus('请先选择要复制的节点'); return }
    clipboardRef.current = clip
    setStatus(`已复制 ${clip.nodes.length} 个节点，可在当前画布粘贴`)
  }
  const pasteSelection = () => {
    if (!canEdit) return
    const clip = clipboardRef.current
    if (!clip?.nodes.length) { setStatus('剪贴板是空的'); return }
    const result = pasteStudioSelection(nodesRef.current, edgesRef.current, clip)
    commitGraph(result.nodes as Node<Data>[], result.edges, `已粘贴 ${result.ids.length} 个节点`)
    setSelectedNodeIds(result.ids); setSelectedNodeId(result.ids[0] || null)
  }
  const openInspector = (id: string) => {
    const node = nodesRef.current.find((item) => item.id === id)
    if (!node) return
    setSelectedNodeId(id)
    setInspectorDraft({ label: String(node.data.label || node.data.name || ''), text: String(node.data.text || ''), prompt: String(node.data.prompt || ''), clipStart: node.data.clipStart === undefined ? '' : String(node.data.clipStart), clipEnd: node.data.clipEnd === undefined ? '' : String(node.data.clipEnd) })
    setInspectorOpen(true); setContextMenu(null)
  }
  const saveInspector = () => {
    if (!inspectorDraft || !selectedNodeId) return
    commitGraph(updateStudioNode(nodesRef.current, selectedNodeId, { label: inspectorDraft.label, text: inspectorDraft.text, prompt: inspectorDraft.prompt, clipStart: inspectorDraft.clipStart === '' ? undefined : Number(inspectorDraft.clipStart), clipEnd: inspectorDraft.clipEnd === '' ? undefined : Number(inspectorDraft.clipEnd) }) as Node<Data>[], edgesRef.current, '节点已更新')
    setInspectorOpen(false)
  }
  const groupSelection = () => {
    if (!canEdit) return
    const group = createStudioGroup(nodesRef.current, new Set(chosenIds()))
    if (!group) { setStatus('至少选择两个节点后再打组'); return }
    commitGraph(groupStudioNodes(nodesRef.current, group) as Node<Data>[], edgesRef.current, '已创建分组')
    setSelectedNodeId(group.id); setSelectedNodeIds([group.id])
  }
  const createCategoryFrame = (at?: { x: number; y: number }) => {
    if (!canEdit) return
    const all = nodesRef.current, positions = nodeWorldPositions(all)
    const picked = new Set(chosenIds())
    const members = all.filter((node) => { if (!picked.has(node.id)) return false; let parent = node.parentId; const seen = new Set<string>(); while (parent && !seen.has(parent)) { if (picked.has(parent)) return false; seen.add(parent); parent = all.find((item) => item.id === parent)?.parentId } return true })
    const point = at ? flow?.screenToFlowPosition(at) : flow?.screenToFlowPosition({ x: window.innerWidth / 2 - 260, y: window.innerHeight / 2 - 160 })
    const left = members.length ? Math.min(...members.map((node) => positions.get(node.id)!.x)) - 28 : point?.x || 0
    const top = members.length ? Math.min(...members.map((node) => positions.get(node.id)!.y)) - 56 : point?.y || 0
    const group: Node<Data> = { id: `group-${crypto.randomUUID()}`, type: 'group', selected: true, position: { x: left, y: top }, style: { width: members.length ? Math.max(...members.map((node) => positions.get(node.id)!.x + (node.measured?.width || Number(node.style?.width) || 320))) - left + 28 : 600, height: members.length ? Math.max(...members.map((node) => positions.get(node.id)!.y + (node.measured?.height || Number(node.style?.height) || 220))) - top + 28 : 400 }, data: { label: '新分类框', children: members.map((node) => node.id) } }
    const memberIds = new Set(members.map((node) => node.id))
    const detached = all.map((node) => memberIds.has(node.id) ? { ...node, parentId: undefined, extent: undefined, position: positions.get(node.id)! } : node.type === 'group' && Array.isArray(node.data.children) ? { ...node, data: { ...node.data, children: node.data.children.filter((id) => !memberIds.has(String(id))) } } : node)
    commitGraph(groupStudioNodes(detached, group) as Node<Data>[], edgesRef.current, '已创建分类框 · 双击标题重命名，可将节点拖入框中')
    setSelectedNodeId(group.id); setSelectedNodeIds([group.id]); setComposerOpen(false)
  }
  const openNodeComposer = (id: string, action: ComposerAction, seed?: string) => {
    const source = nodesRef.current.find((node) => node.id === id)
    if (action === 'compose' && source && mediaOf(source) && nodeMediaKind(source) === 'video') {
      if (canEdit) { setMediaEdit({id,operation:'trim'}); setComposerOpen(false) }
      return
    }
    if (source && mediaOf(source) && nodeMediaKind(source) === 'image' && ['edit', 'crop', 'inpaint'].includes(action)) {
      if (canEdit) { setImageEditorMode(action === 'crop' ? 'crop' : 'edit'); setMaskNodeId(id); setComposerOpen(false) }
      return
    }
    if (!source || !mediaOf(source) || !['video', 'reference', 'edit', 'outpaint', 'audio', 'compose'].includes(action)) { openSelectionComposer(action, seed, id); return }
    if (!canEdit) return
    const kind = action === 'audio' ? 'audio' : ['video', 'reference', 'compose'].includes(action) ? 'video' : 'image'
    const positions = nodeWorldPositions(nodesRef.current), origin = positions.get(id)!
    const position = { x: origin.x + (source.measured?.width || Number(source.style?.width) || 320) + 110, y: origin.y }
    const occupied = nodesRef.current.filter((node) => node.type !== 'group')
    while (occupied.some((node) => { const p = positions.get(node.id)!; return position.x < p.x + (node.measured?.width || 320) + 24 && position.x + 340 > p.x && position.y < p.y + (node.measured?.height || 220) + 24 && position.y + 240 > p.y })) position.y += 280
    const label = action === 'reference' ? '参考生成视频' : action === 'video' ? '图生视频' : action === 'compose' ? '剪辑合成' : kind === 'audio' ? '生成音频' : '参考生成图片'
    const created: Node<Data> = { ...newNode(`${kind}Generation`, nodesRef.current.length), id: `node-${crypto.randomUUID()}`, position, selected: true, data: { label, editor: action, prompt: seed || '', ratio: kind === 'video' ? (nodeMediaKind(source) === 'video' ? source.data.ratio || '16:9' : '16:9') : source.data.ratio || '2:3', ...(kind === 'video' ? { hideTryHints: true, videoMode: action === 'reference' ? 'omni_reference' : 'image_to_video' } : {}) } }
    commitGraph([...nodesRef.current.map((node) => node.selected ? { ...node, selected: false } : node), created], [...edgesRef.current, { id: `edge-${crypto.randomUUID()}`, source: id, target: created.id }], '已新建生成节点并连接参考素材')
    setSelectedNodeIds([created.id]); setHiddenRefIds([])
    openSelectionComposer(action, seed ?? '', created.id)
  }
  const createImageResult = (source: Node<Data>, data: Data) => {
    const positions = nodeWorldPositions(nodesRef.current), origin = positions.get(source.id) || source.position
    const position = { x: origin.x + (source.measured?.width || Number(source.style?.width) || 320) + 90, y: origin.y }
    while (nodesRef.current.some((node) => { if (node.type === 'group') return false; const p = positions.get(node.id)!; return Math.abs(p.x - position.x) < 340 && Math.abs(p.y - position.y) < 260 })) position.y += 280
    const created: Node<Data> = { ...newNode('image', nodesRef.current.length), id: `node-${crypto.randomUUID()}`, position, selected: true, data }
    commitGraph([...nodesRef.current.map((node) => ({ ...node, selected: false })), created], [...edgesRef.current, { id: `edge-${crypto.randomUUID()}`, source: source.id, target: created.id }], '已保存为新图片节点，原图保持不变')
    setSelectedNodeId(created.id); setSelectedNodeIds([created.id])
    return created
  }
  const ungroupSelection = (merge = false) => {
    if (!canEdit) return
    const ids = new Set(chosenIds())
    if (merge) {
      const result = mergeStudioGroups(nodesRef.current, edgesRef.current, ids)
      if (!result) { setStatus('请选择两个顶层节点或分组，其中至少一个是分组'); return }
      commitGraph(result.nodes as Node<Data>[], result.edges, '已合并分组')
      setSelectedNodeId(result.id); setSelectedNodeIds([result.id]); return
    }
    const groups = new Set(nodesRef.current.filter((node) => node.type === 'group' && ids.has(node.id)).map((node) => node.id))
    if (!groups.size) { if (merge) groupSelection(); return }
    nodesRef.current.forEach((node) => { if (node.parentId && groups.has(node.parentId)) ids.add(node.id) })
    let next = ungroupStudioNodes(nodesRef.current, groups) as Node<Data>[]
    const group = merge ? createStudioGroup(next, ids) : undefined
    if (group) next = groupStudioNodes(next, group) as Node<Data>[]
    else next = next.map((node) => ({ ...node, selected: ids.has(node.id) }))
    commitGraph(next, edgesRef.current.filter((edge) => !groups.has(edge.source) && !groups.has(edge.target)), group ? '已合并分组' : '已取消分组，保留所有子节点')
    setSelectedNodeId(group?.id || null); setSelectedNodeIds(group ? [group.id] : next.filter((node) => node.selected).map((node) => node.id))
  }
  const uploadFiles = async (files: FileList | null) => {
    if (!files?.length || !canEdit) return
    const created: Node<Data>[] = []
    for (const file of Array.from(files)) {
      try {
        setStatus(`正在上传 ${file.name}`)
        const asset = await printfilmStudioApi.uploadAsset(projectId, file, editLockRequestHeaders(canvasTarget))
        if (!mountedRef.current) return
        const type = assetMediaKind(asset)
        created.push({ ...newNode(type, nodesRef.current.length + created.length), data: { label: asset.name || file.name, assetId: asset.id, mediaUrl: asset.url || undefined, mediaType: type, status: 'completed' } })
        setAssets((current) => [asset, ...current])
      } catch (error) {
        if (created.length) commitGraph([...nodesRef.current, ...created], edgesRef.current, '部分素材已导入')
        setStatus(error instanceof Error ? error.message : '素材上传失败'); return
      }
    }
    commitGraph([...nodesRef.current, ...created], edgesRef.current, `已上传 ${created.length} 个媒体节点`)
  }
  const applyCrop = async (ratio: number) => {
    const media = String(selectedNode?.data.mediaUrl || selectedNode?.data.url || selectedNode?.data.cover || '')
    if (!selectedNode || !media) { setStatus('当前节点没有可裁剪的图片'); return }
    try {
      const cropped = await withProjectMedia([media], projectId, ([url]) => cropImageToDataUrl(url, ratio))
      const blob = await fetch(cropped).then((response) => response.blob())
      const asset = await printfilmStudioApi.uploadAsset(projectId, new File([blob], '裁剪图片.png', { type: 'image/png' }), editLockRequestHeaders(canvasTarget))
      if (!mountedRef.current) return
      createImageResult(selectedNode, { label: `${selectedNode.data.label || '图片'} 裁剪`, mediaUrl: asset.url || '', assetId: asset.id, mediaType: 'image', status: 'completed' })
      setComposerOpen(false)
    } catch (error) { setStatus(error instanceof Error ? error.message : '裁剪失败') }
  }
  const absoluteMediaUrl = (url: string) => {
    const resolved = resolveToolMediaUrl(url) || url
    if (!resolved) return ''
    if (resolved.startsWith('blob:') || resolved.startsWith('data:') || /^https?:\/\//i.test(resolved)) return resolved
    return new URL(resolved, window.location.origin).toString()
  }
  const pushMediaFile = async (files: File[], url: string, name: string) => {
    const media = absoluteMediaUrl(url)
    if (!media) return
    const blob = await readProjectMedia(media, projectId, assets.find((asset) => asset.url === media)?.id)
    const ext = ({ 'image/png': 'png', 'image/webp': 'webp', 'video/mp4': 'mp4', 'video/webm': 'webm', 'video/quicktime': 'mov', 'audio/mpeg': 'mp3', 'audio/wav': 'wav', 'audio/mp4': 'm4a', 'audio/ogg': 'ogg' } as Record<string, string>)[blob.type.split(';')[0]] || (/\.(mp4|webm|mov|mp3|wav|m4a|ogg)(?:[?#]|$)/i.exec(media)?.[1]) || 'jpg'
    const filename = name.includes('.') ? name : `${name}.${ext}`
    files.push(new File([blob], filename, { type: blob.type || 'image/jpeg' }))
  }
  const runNodeGeneration = async (action: NonNullable<typeof selectionAction>) => {
    if (!canEdit) { setStatus(loadIssue?.message || '当前画布为只读模式'); return }
    if (action === 'crop') return
    const submittingId = selectedNodeId || 'new'
    const reportError = (message: string) => { setStatus(message); setSubmissionError({nodeId:submittingId,message}) }
    if (referenceValidation) {reportError(referenceValidation);return}
    if (generationRunningRef.current.has(submittingId) || (action !== 'compose' && !genPrompt.trim() && !selectedNode?.data.promptNodeId && selectedNode?.data.storyKind !== 'shot_video')) return
    const setGenerationRunning = (value: boolean) => {
      if (value) generationRunningRef.current.add(submittingId)
      else generationRunningRef.current.delete(submittingId)
      if (mountedRef.current) setSubmittingNodeIds((ids) => { const next = new Set(ids); if (value) next.add(submittingId); else next.delete(submittingId); return next })
    }
    setGenerationRunning(true)
    setSubmissionError(null)
    if (dirtyRef.current && !(await save())) { setGenerationRunning(false); reportError('请先完成画布保存并处理冲突，再创建生成任务'); return }
    if (action === 'compose') {
      try {
        const clips = [...linkedRefs, ...(selectedNode && nodeMediaKind(selectedNode) === 'video' ? [selectedNode] : [])].filter((node) => nodeMediaKind(node) === 'video' && mediaOf(node))
        if (clips.length < 2) throw new Error('请连接至少两个已完成的视频片段后再合成')
        setStatus(`正在合成 ${clips.length} 个视频片段…`)
        const asset = (await printfilmStudioApi.composeMedia(projectId, clips.map(mediaOf), editLockRequestHeaders(canvasTarget))).assets[0]
        if (!asset?.url) throw new Error('视频合成未返回素材')
        if (!mountedRef.current) return
        addNode('video', asset, { prompt: genPrompt, sourceNodeIds: clips.map((node) => node.id) })
        setComposerOpen(false); setStatus('视频已合成并保存为项目素材')
      } catch (error) { reportError(error instanceof Error ? error.message : '视频合成失败') }
      finally { setGenerationRunning(false) }
      return
    }
    const source = nodesRef.current.find((node) => node.id === selectedNodeId)
    let storyInputs: ReturnType<typeof storyVideoInputs>
    let assetPrompt: string | undefined
    try { storyInputs = storyVideoInputs(source, nodesRef.current, edgesRef.current); assetPrompt = storyAssetPrompt(source, nodesRef.current, edgesRef.current) }
    catch (error) { setGenerationRunning(false); reportError(error instanceof Error ? error.message : '分镜参考不完整'); return }
    const userPrompt = storyInputs?.prompt || assetPrompt || genPrompt.trim()
    const referenceText = storyInputs || assetPrompt ? '' : linkedRefs.filter((node) => nodeMediaKind(node) === 'text' && !hiddenRefIds.includes(node.id)).map((node) => `${node.data.label || '参考文本'}：${node.data.text || ''}`).join('\n').slice(0, 6000)
    const rawMessage = storyInputs?.providerPrompt || (referenceText ? `${plainPrompt(userPrompt)}\n\n参考脚本：\n${referenceText}` : plainPrompt(userPrompt))
    const message = action === 'video' || action === 'reference' ? videoPromptAudio(rawMessage,genModel) : rawMessage
    if (!userPrompt) { setGenerationRunning(false); return }
    setStatus('正在提交生成任务…')
    try {
      const files: File[] = []
      const kinds: MediaKind[] = []
      const isVideoAction = action === 'video' || action === 'reference'
      const requestRatio = outputRatio === 'auto' ? (isVideoAction ? '16:9' : '2:3') : outputRatio
      if (isVideoAction && source) assertWritingParameters(nodesRef.current.find(node=>node.id===source.data.promptNodeId),{id:source.id,label:String(source.data.label || ''),kind:'video',model:genModel,ratio:requestRatio,duration:outputDuration})
      const inpaint = action === 'inpaint' ? source?.data.inpaint as InpaintData | undefined : undefined
      if (action === 'inpaint' && !inpaint) throw new Error('请先在图片操作条选择局部重绘并涂抹选区')
      if (inpaint) { await pushMediaFile(files, inpaint.originalUrl, 'original.png'); await pushMediaFile(files, inpaint.guideUrl, 'guide.png'); kinds.push('image', 'image') }
      if (storyInputs) for (const reference of storyInputs.references) {
        await pushMediaFile(files, reference.url, `ref-${reference.node.id}`)
        kinds.push('image')
      }
      if (!storyInputs && action !== 'audio') for (const node of [...(source ? [source] : []), ...linkedRefs.filter((node) => !hiddenRefIds.includes(node.id))]) {
        if (inpaint && (node.id === source?.id || mediaOf(node) === inpaint.originalUrl)) continue
        const media = mediaOf(node)
        if (!media) continue
        const kind = nodeMediaKind(node)
        if (kind === 'text') continue
        if (!isVideoAction && kind !== 'image') throw new Error('图片编辑仅支持图片参考，请移除音视频参考')
        await pushMediaFile(files, media, `ref-${node.id}`)
        kinds.push(kind)
      }
      if (isVideoAction) { const mode = storyInputs?.mode || outputVideoMode || (action === 'reference' && kinds.length ? 'omni_reference' : kinds.length === 1 && kinds[0] === 'image' ? 'image_to_video' : videoFileReferences(kinds).mode); const error = videoReferenceError(kinds, mode, catalogVideoModels(mediaCatalog).find((model) => model.id === genModel)?.reference_limits); if (error) throw new Error(error) }
      const videoRefs = videoFileReferences(kinds, action === 'reference', storyInputs?.mode || outputVideoMode)
      const references: ToolReferenceInput[] = videoRefs.references
      const isImageEdit = action === 'edit' || action === 'inpaint' || action === 'outpaint'
      const toolId = action === 'audio' ? 'audio' : isImageEdit ? (files.length || references.length ? 'i2i' : 't2i') : 't2v'
      const videoMode = videoRefs.mode
      let priceVersion: number | undefined
      if (toolId === 't2v') {
        const quote = await estimateStudioTool({ tool_id: 't2v', model_id: genModel, generate_audio: outputAudio, resolution: outputResolution, ratio: requestRatio, duration: outputDuration, video_mode: videoMode, references })
        priceVersion = quote.price_version ?? 0
        setStatus(`预计消耗 ${quote.estimate_yuan} 元，正在创建任务`)
      }
      const outputKind = action === 'audio' ? 'audio' : isVideoAction ? 'video' : 'image'
      const reuseSource = source && nodeMediaKind(source) === outputKind
      if (reuseSource && ['queued', 'running', 'awaiting_composite'].includes(String(source.data.status))) throw new Error('该节点已有任务，请等待完成或创建新节点')
      const targetNodeId = reuseSource ? source.id : `node-${crypto.randomUUID()}`
      const result = await runStudioTool({ projectId, editHeaders: editLockRequestHeaders(canvasTarget), toolId, prompt: inpaint ? `对第一张原图做局部重绘。第二张为选区引导图，红色是修改范围，不要把红色标注画进结果。保留比例和区域外内容，返回完整图片。重绘要求：${message}` : message, modelId: action === 'audio' ? '' : genModel, voice: outputVoice, generateAudio: isVideoAction ? outputAudio : undefined, files, ratio: requestRatio, resolution: isVideoAction ? outputResolution : imageResolution, duration: action === 'audio' ? '' : isVideoAction ? outputDuration : '', pack: isVideoAction || action === 'audio' ? '' : inpaint ? '1' : outputCount, references: isVideoAction ? references : undefined, priceVersion, videoMode: toolId === 't2v' ? videoMode : undefined, nodeId: targetNodeId })
      if (!mountedRef.current) return
      const type = action === 'audio' ? 'audio' : isVideoAction || toolId === 't2v' ? 'video' : source?.type === 'inpaint' || source?.type === 'outpaint' || action === 'inpaint' || action === 'outpaint' ? (source?.type === 'inpaint' || action === 'inpaint' ? 'inpaint' : 'outpaint') : 'image'
      const resultUrls = (result.urls || []).map((item) => resolveToolMediaUrl(item) || item).filter(Boolean)
      const mediaPatch = {
        label: reuseSource ? String(source?.data.label || userPrompt.slice(0, 24)) : userPrompt.slice(0, 24),
        prompt: userPrompt,
        mediaOutputMetadata:{prompt:userPrompt,modelId:genModel,ratio:requestRatio,resolution:isVideoAction?outputResolution:imageResolution,duration:isVideoAction?outputDuration:undefined},
        status: result.status || 'queued',
        error: undefined,
        cancelRequested: false,
        canCancel: result.status === 'queued',
        taskId: result.task_id || undefined,
        mediaUrl: resultUrls[0] || undefined,
        mediaUrls: resultUrls.length ? resultUrls : undefined,
        mediaIndex: 0,
        mediaType: type === 'inpaint' || type === 'outpaint' ? 'image' : type,
        editor: action,
        modelId: action === 'audio' ? '' : genModel,
        ratio: requestRatio,
        duration: outputDuration,
        generateAudio: outputAudio,
        resolution: isVideoAction ? outputResolution : imageResolution,
        count: outputCount,
        voice: outputVoice,
        ...(inpaint ? { inpaint, mediaUrl: undefined, mediaUrls: undefined, status: result.task_id ? 'queued' : 'awaiting_composite' } : {}),
      }
      const nextNodes = [...nodesRef.current]
      if (reuseSource && source) {
        const liveSource=nodesRef.current.find(node=>node.id===source.id)
        if(!liveSource || !canEditRef.current){setStatus('任务已提交，可在生成历史中查看结果');return}
        const replacement = { ...replaceNodeMedia(liveSource.data, { mediaUrl: resultUrls[0] || '', mediaUrls: resultUrls, mediaType: outputKind }), assetId: undefined, cover: undefined }
        const updated = updateStudioNode(nextNodes, source.id, { ...replacement, ...mediaPatch }) as Node<Data>[]
        commitGraph(updated, edgesRef.current, result.task_id ? `任务 ${result.task_id} 已创建` : '生成已提交')
      } else {
        const created = { ...newNode(type, nextNodes.length), id: targetNodeId, data: mediaPatch }
        const nextEdges = source ? [...edgesRef.current, { id: `edge-${Date.now()}`, source: source.id, target: created.id, type: 'smoothstep' }] : edgesRef.current
        commitGraph([...nextNodes, created], nextEdges, result.task_id ? `任务 ${result.task_id} 已创建` : '生成已提交')
      }
      setGenPrompt(''); setComposerOpen(false); setBottomOpen(false)
    } catch (error) { reportError(error instanceof Error ? error.message : '生成任务创建失败') }
    finally { setGenerationRunning(false) }
  }
  const pendingImageRunRef = useRef(runNodeGeneration)
  const quoteTargets = async (ids: string[], settings: BatchSettings) => {
    if (dirtyRef.current && !(await save())) throw new Error('请先保存画布并处理冲突')
    return printfilmStudioApi.quoteWorkflow(projectId, ids, settings, versionRef.current, editLockRequestHeaders(canvasTarget), ids.length > 0 && ids.every(id => nodesRef.current.some(node=>node.id===id && writingNode(node))))
  }
  const runAgentBatch = async (quote: BatchQuote) => {
    if (!canEditRef.current || proposalBusyRef.current || agentRunning || !quote.runId) throw new Error('当前无法运行，请重新报价')
    const result = await printfilmStudioApi.startWorkflow(projectId, quote.runId, editLockRequestHeaders(canvasTarget))
    setStatus(result.status === 'running' ? '已在后台运行，可继续编辑、关闭弹窗或离开页面' : '节点运行完成')
    setComposerOpen(false); setTextGenerationNodeId(null)
  }
  const openDependencyRun = (ids: string[]) => {
    if (ids.length > 1) { setBatchNodeIds(ids); return }
    try {
      const texts = nodesRef.current.filter(node => ids.includes(node.id) && writingNode(node))
      const plan = texts.length === ids.length ? texts : dependencyPlan(ids, nodesRef.current, edgesRef.current)
      if (!plan.length) { setStatus('这些节点已有有效结果，无需重复运行'); return }
      if (ids.length > 1 || plan.length > 1) { setBatchNodeIds(ids); return }
      if (proposalBusyRef.current) return
      proposalBusyRef.current = true
      setStatus('正在提交运行…')
      void batchDefaults(catalogImageModels(mediaCatalog).filter(model => model.available !== false), catalogVideoModels(mediaCatalog).filter(model => model.available !== false))
        .then(settings => quoteTargets(ids, settings)).then(async quote => { proposalBusyRef.current = false; await runAgentBatch(quote) })
        .catch(reason => setStatus(reason instanceof Error ? reason.message : '无法运行节点')).finally(() => { proposalBusyRef.current = false })
    } catch (reason) { setStatus(reason instanceof Error ? reason.message : '无法运行节点') }
  }
  const quoteAgentBatch = (settings: BatchSettings) => quoteTargets(batchNodeIds, settings)
  pendingImageRunRef.current = runNodeGeneration
  useEffect(() => {
    if (!pendingImageGeneration || selectedNodeId !== pendingImageGeneration.nodeId || genPrompt !== pendingImageGeneration.prompt || !catalogImageModels(mediaCatalog).some((model) => model.id === genModel)) return
    setPendingImageGeneration(null)
    void pendingImageRunRef.current('inpaint')
  }, [pendingImageGeneration, selectedNodeId, genPrompt, genModel, mediaCatalog])
  const cutSelection = () => {
    if (!canEdit || !chosenIds().length) return
    copySelection()
    removeIds(chosenIds())
    setStatus('已剪切')
  }
  const runMenuAction = (id: string) => {
    if (id === 'disconnect' && contextMenu?.kind === 'edge') {
      if (canEdit) {const next=disconnectStudioEdge(nodesRef.current,edgesRef.current,contextMenu.id);commitGraph(next.nodes as Node<Data>[],next.edges,'已断开连线')}
      setContextMenu(null); return
    }
    if (!canEdit && !['copy', 'share', 'ask_agent'].includes(id)) return
    const targetId = contextMenu?.id || selectedNodeId
    if (id === 'run_here' && targetId) {
      openDependencyRun([targetId])
    }
    if (id === 'recipe') { try { setRecipeDraft(captureRecipe(documentRef.current, chosenIds())); setRecipeOpen(true) } catch (e) { setStatus(e instanceof Error ? e.message : '无法保存配方') } }
    if (id === 'share') void shareWorkspace()
    if (id === 'rename' && targetId) openInspector(targetId)
    if (id === 'duplicate') duplicateIds(chosenIds())
    if (id === 'copy') copySelection()
    if (id === 'cut') cutSelection()
    if (id === 'group') groupSelection()
    if (id === 'ungroup') ungroupSelection()
    if (id === 'mergeGroup') ungroupSelection(true)
    if (id === 'ask_agent') {
      setAgentOpen(true)
      if (targetId) { setSelectedNodeId(targetId); setSelectedNodeIds([targetId]) }
      setPrompt(targetId ? '请围绕这个参考节点给出下一步创作建议' : '请帮我看看当前画布该怎么继续')
    }
    if (id === 'remove') removeIds(chosenIds())
    if (id === 'horizontal' || id === 'vertical' || id === 'grid') commitGraph(arrangeStudioNodes(nodesRef.current, new Set(chosenIds()), id) as Node<Data>[], edgesRef.current, '已排列所选节点')
    setContextMenu(null)
  }
  const uploadOntoNode = async (id: string, files: FileList | null) => {
    if (!files?.length || !canEdit) return
    const file = files[0]
    if (nodesRef.current.find((node) => node.id === id)?.type === 'frameAnalysis' && !file.type.startsWith('video/')) { setStatus('逐帧拉片只能上传视频'); return }
    try {
      setStatus(`正在上传 ${file.name}`)
      const asset = await printfilmStudioApi.uploadAsset(projectId, file, editLockRequestHeaders(canvasTarget))
      if (!mountedRef.current) return
      const kind = assetMediaKind(asset)
      if (!canEditRef.current) { setStatus('素材已上传，取得编辑权后可从素材库添加'); return }
      commitGraph(updateStudioNode(nodesRef.current, id, replaceNodeMedia(nodesRef.current.find((node) => node.id === id)?.data || {}, { mediaUrl: asset.url || '', assetId: asset.id, mediaType: kind, label: file.name })) as Node<Data>[], edgesRef.current, '已添加媒体到节点')
      setAssets((current) => [asset, ...current])
    } catch (error) { setStatus(error instanceof Error ? error.message : '素材上传失败') }
  }

  const placeAsset = async (sourceId: number, at?: { x: number; y: number }) => {
    if (!canEdit) return
    const asset = await printfilmStudioApi.importAsset(projectId, sourceId, editLockRequestHeaders(canvasTarget))
    if (!mountedRef.current) return
    setAssets((current) => current.some((item) => item.id === asset.id) ? current : [asset, ...current])
    addNode(assetMediaKind(asset), asset, {}, at)
  }
  const placeReferenceAsset = async (sourceAsset: ProjectAsset, targetId: string) => {
    if (!canEdit) return
    const existing = referenceAssetNode(nodesRef.current, sourceAsset, targetId, edgesRef.current)
    if (existing) {
      citeNode(existing.id, targetId)
      setReferenceTargetId(null); setAssetsOpen(false)
      return
    }
    const candidate: Node<Data> = { id: `node-${crypto.randomUUID()}`, type: assetMediaKind(sourceAsset), position: { x: 0, y: 0 }, data: {} }
    const invalid = validateStudioConnection({ source: candidate.id, target: targetId }, [...nodesRef.current, candidate], edgesRef.current)
    if (invalid) throw new Error(invalid)
    const asset = await printfilmStudioApi.importAsset(projectId, sourceAsset.id, editLockRequestHeaders(canvasTarget))
    if (!mountedRef.current || !canEditRef.current) return
    const target = nodesRef.current.find((node) => node.id === targetId)
    if (!target) throw new Error('目标节点已移除，请重新选择')
    const origin = nodeWorldPositions(nodesRef.current).get(targetId)!
    const occupied = nodeWorldPositions(nodesRef.current)
    candidate.position = { x: origin.x - 400, y: origin.y }
    while (nodesRef.current.some((node) => node.type !== 'group' && Math.abs(occupied.get(node.id)!.x - candidate.position.x) < 340 && Math.abs(occupied.get(node.id)!.y - candidate.position.y) < 260)) candidate.position.y += 280
    candidate.data = { label: asset.name || '参考素材', assetId: asset.id, mediaUrl: asset.url || asset.cover || '', mediaType: assetMediaKind(asset), status: 'completed' }
    setAssets((current) => current.some((item) => item.id === asset.id) ? current : [asset, ...current])
    commitGraph([...nodesRef.current.map((node) => ({ ...node, selected: node.id === targetId })), candidate], [...edgesRef.current, { id: `edge-${crypto.randomUUID()}`, source: candidate.id, target: targetId }], '已添加参考素材并连线')
    setSelectedNodeIds([targetId]); setSelectedNodeId(targetId); setReferenceTargetId(null); setAssetsOpen(false)
  }
  const putMediaResults = (sourceId: string, outputs: ProjectAsset[], columns = 4) => {
      if (!mountedRef.current) return
      const source = nodesRef.current.find((node) => node.id === sourceId)
      setAssets((current) => [...outputs, ...current])
      if (!source || !canEditRef.current) { setStatus('处理结果已保存到素材库，请重新取得编辑权后添加到画布'); return }
      const position = flow?.getInternalNode(source.id)?.internals.positionAbsolute || source.position
      const added = outputs.map((asset, index) => ({ ...newNode(assetMediaKind(asset), nodesRef.current.length + index), position: { x: position.x + 380 + (index % columns) * 310, y: position.y + Math.floor(index / columns) * 260 }, data: { label: asset.name || '处理结果', mediaUrl: asset.url || undefined, assetId: asset.id, mediaType: assetMediaKind(asset), status: 'completed' } }))
      commitGraph([...nodesRef.current, ...added], [...edgesRef.current, ...added.map((node) => ({ id: `edge-${crypto.randomUUID()}`, source: source.id, target: node.id }))], `已添加 ${added.length} 个媒体结果`)
  }
  const analysisNode = nodes.find((node) => node.id === analysisNodeId)
  const textGenerationNode = nodes.find((node) => node.id === textGenerationNodeId)
  const textWritingContext = textGenerationNode ? writingContext(textGenerationNode, nodes, edges) : {references:[],outputs:[]}
  const textWritingInputs = textGenerationNode ? writingInputSignature(textGenerationNode.data, textWritingContext.references, textWritingContext.outputs) : ''
  const validateTextWriting = () => {
    const current = nodesRef.current.find(node => node.id === textGenerationNode?.id)
    if (!mountedRef.current || !canEditRef.current || !current) throw new Error('节点已删除或不可编辑，生成结果已保留')
    const context = writingContext(current, nodesRef.current, edgesRef.current)
    if (writingInputSignature(current.data, context.references, context.outputs) !== textWritingInputs) throw new Error('写作要求、参考素材或下游参数已变化，本次结果已保留，请核对后重新生成')
  }
  const imageToolNode = nodes.find((node) => node.id === imageTool?.id)
  const analysisSourceId = edges.find((edge) => edge.target === analysisNodeId)?.source
  const analysisSource = nodes.find((node) => node.id === analysisSourceId)
  const analysisUrl = String(analysisSource?.data.mediaUrl || analysisSource?.data.url || analysisNode?.data.mediaUrl || analysisNode?.data.url || '')
  const createVideoInput = (targetId: string, kind: 'image' | 'text', mode?: StudioVideoMode) => {
    if (!canEdit) return
    const target = nodesRef.current.find((node) => node.id === targetId)
    if (!target) return
    const world = nodeWorldPositions(nodesRef.current), origin = world.get(targetId)!
    let y = origin.y
    while (nodesRef.current.some((node) => node.type !== 'group' && Math.abs(world.get(node.id)!.x - (origin.x - 420)) < 350 && Math.abs(world.get(node.id)!.y - y) < 260)) y += 280
    const created = { ...newNode(kind, nodesRef.current.length), id: `node-${crypto.randomUUID()}`, position: { x: origin.x - 420, y }, data: { label: kind === 'text' ? '故事脚本' : '参考图片', editor: kind === 'text' ? 'text' : 'edit', text: '', prompt: '' }, selected: true }
    const next = updateStudioNode(nodesRef.current, targetId, mode ? { videoMode: mode } : {}) as Node<Data>[]
    const retainedEdges = kind === 'text' ? edgesRef.current : edgesRef.current.filter((edge) => edge.target !== targetId || nodeMediaKind(nodesRef.current.find((node) => node.id === edge.source)) === 'text' || mode === 'first_last_frame' && edge === edgesRef.current.find((item) => item.target === targetId && nodeMediaKind(nodesRef.current.find((node) => node.id === item.source)) === 'image'))
    commitGraph([...next.map((node) => ({ ...node, selected: false })), created], [...retainedEdges, { id: `edge-${crypto.randomUUID()}`, source: created.id, target: targetId }], '已创建输入节点并连接视频')
    setVideoSetup(null); setSelectedNodeId(created.id); setSelectedNodeIds([created.id]); setComposerOpen(false)
    if (kind === 'text') { setTextGenerationNodeId(created.id); window.requestAnimationFrame(() => focusNode(created.id)) }
    else openSelectionComposer('edit', '', created.id)
  }
  const exportComposition = async (id:string) => {
    if(!canEditRef.current || generationRunningRef.current.has(id))return
    const clips=compositionClips(id,nodesRef.current,edgesRef.current),issue=compositionError(clips)
    if(issue)throw new Error(issue)
    const signature=JSON.stringify(clips.map(({id,url})=>({id,url})))
    generationRunningRef.current.add(id);setSubmittingNodeIds(ids=>new Set([...ids,id]))
    try {
      if(dirtyRef.current && !(await save()))throw new Error('请先处理画布保存冲突')
      const asset=(await printfilmStudioApi.composeMedia(projectId,clips.map(clip=>clip.url),editLockRequestHeaders(canvasTarget))).assets[0]
      if(!asset?.url)throw new Error('视频合成未返回文件')
      if(!mountedRef.current)return
      setAssets(current=>[asset,...current])
      const target=nodesRef.current.find(node=>node.id===id)
      if(!target || !canEditRef.current || signature!==JSON.stringify(compositionClips(id,nodesRef.current,edgesRef.current).map(({id,url})=>({id,url}))))throw new Error('片段或顺序已变化，合成视频已保存在项目素材库，请重新编排')
      commitGraph(updateStudioNode(nodesRef.current,id,{...replaceNodeMedia(target.data,{mediaUrl:asset.url,assetId:asset.id,mediaType:'video'}),compositionOrder:clips.map(clip=>clip.id)}) as Node<Data>[],edgesRef.current,'合成视频已保存，可下载导出')
    } finally {generationRunningRef.current.delete(id);if(mountedRef.current)setSubmittingNodeIds(ids=>{const next=new Set(ids);next.delete(id);return next})}
  }
  const nodeActions: StudioNodeActions = {
    writingReferences: (id) => resolveWritingReferences(id,nodesRef.current,edgesRef.current),
    projectId,
    focusNode: id=>focusNode(id),
    composition: id=>setCompositionNodeId(id),
    compositionSummary: id=>{const clips=compositionClips(id,nodesRef.current,edgesRef.current);return {count:clips.length,pending:compositionError(clips)}},
    disconnectEdge: id=>{if(!canEditRef.current)return;const next=disconnectStudioEdge(nodesRef.current,edgesRef.current,id);commitGraph(next.nodes as Node<Data>[],next.edges,'已剪断连线')},
    cancelGeneration: (id) => {
      const node = nodesRef.current.find((item) => item.id === id)
      if (!canEdit || !node?.data.taskId || node.data.cancelRequested) return
      void printfilmStudioApi.cancelGeneration(projectId, String(node.data.taskId), editLockRequestHeaders(canvasTarget)).then(() => {
        if (mountedRef.current && canEditRef.current) commitGraph(updateStudioNode(nodesRef.current, id, { cancelRequested: true }) as Node<Data>[], edgesRef.current, '已请求取消，等待服务确认')
      }).catch((reason) => setStatus(reason instanceof Error ? reason.message : '取消失败'))
    },
    imageTools: (id, mode) => setImageTool({ id, mode }),
    generateText: (id) => { setTextGenerationNodeId(id); setSelectedNodeId(id); setSelectedNodeIds([id]); setPanelsSuppressed(false) },
    closeTextComposer: () => setTextGenerationNodeId(null),
    textComposer: textGenerationNode ? { nodeId: textGenerationNode.id, content: <InlineTextComposer onFocusReference={id=>focusNode(id)} key={textGenerationNode.id} runStore={writingRuns} onValidate={validateTextWriting} projectId={projectId} nodeId={textGenerationNode.id} title={String(textGenerationNode.data.label || '文本')} text={String(textGenerationNode.data.text || '')} settings={textGenerationNode.data} headers={editLockRequestHeaders(canvasTarget)} writable={canEdit} references={textWritingContext.references} outputs={textWritingContext.outputs} candidates={nodes.filter((node) => node.id !== textGenerationNode.id && node.type !== 'group' && ['text','image'].includes(nodeMediaKind(node)) && (!textGenerationNode.data.sourceScriptId || !node.data.sourceScriptId || node.data.sourceScriptId === textGenerationNode.data.sourceScriptId)).map(writingReference)} onSetting={(key, value) => { if (!canEdit) return; setNodes((current) => updateStudioNode(current, textGenerationNode.id, { [key]: value }) as Node<Data>[]); dirtyRef.current = true }} onReference={(id) => { if (!canEdit) return; try { const graph = toggleWritingReference(textGenerationNode, nodesRef.current, edgesRef.current, id); if (!graph.removing) { const error = graph.edges.filter(edge=>!edgesRef.current.some(old=>old.id===edge.id)).map(edge=>validateStudioConnection(edge,graph.nodes,edgesRef.current)).find(Boolean); if (error) throw new Error(error) }; commitGraph(graph.nodes,graph.edges,graph.removing ? '已移除写作与视频参考' : '已关联写作与视频参考') } catch (error) { setStatus(error instanceof Error ? error.message : '参考关联失败') } }} onBusy={(busy) => setSubmittingNodeIds((ids) => { const next = new Set(ids); if (busy) next.add(textGenerationNode.id); else next.delete(textGenerationNode.id); return next })} onApply={(result, expected, outputs) => {
      const current = nodesRef.current.find((node) => node.id === textGenerationNode.id)
      if (!canEditRef.current || !current || String(current.data.text || '') !== expected) throw new Error('节点正文已变化，生成结果已保留，请核对后复制')
      commitGraph(updateStudioNode(nodesRef.current, current.id, { text: result, writingOutputSettings: outputs }) as Node<Data>[], edgesRef.current, 'AI 正文已写入节点')
    }} /> } : undefined,
    videoStart: (id, mode) => { if (!canEdit) return; if (mode === 'script') createVideoInput(id, 'text'); else setVideoSetup({ id, mode }) },
    analyze: (id) => {
      const source = nodesRef.current.find((node) => node.id === id)
      if (!source) return
      if (source.type === 'frameAnalysis') { setAnalysisNodeId(id); return }
      if (!canEdit) return
      const position = flow?.getInternalNode(id)?.internals.positionAbsolute || source.position
      const created = { ...newNode('frameAnalysis', nodesRef.current.length), position: { x: position.x + (source.width || 320) + 80, y: position.y }, data: { label: `${source.data.label || '视频'} · 逐帧拉片`, mediaUrl: source.data.mediaUrl || source.data.url, mediaType: 'video' } }
      commitGraph([...nodesRef.current, created], [...edgesRef.current, { id: `edge-${crypto.randomUUID()}`, source: id, target: created.id }], '已添加逐帧拉片节点，打开后可开始检测')
      setAnalysisNodeId(created.id)
    },
    director: setDirectorNodeId,
    mediaEdit: (id, operation, start) => { if (canEdit) setMediaEdit({ id, operation, start }) },
    gridSplit: (id) => { if (canEdit) setGridNodeId(id) },
    history: (id) => setHistoryNodeId(id),
    ask: (id) => { setSelectedNodeId(id); setSelectedNodeIds([id]); setAgentOpen(true); setPrompt('请以这个参考脚本规划角色与分镜，创建对应文本节点并连接到脚本，先不生成图片或视频。'); },
    writable: canEdit,
    submittingNodeIds,
    selectionCount: selectedNodeIds.length,
    panelsSuppressed,
    checkpoint: checkpointGraph,
    rename: (id, title) => { if (canEdit) commitGraph(updateStudioNode(nodesRef.current, id, { label: title }) as Node<Data>[], edgesRef.current, '节点已重命名') },
    imageLoaded: (id, url, naturalWidth, naturalHeight) => {
      const node = nodesRef.current.find((item) => item.id === id)
      if (!node || node.data.mediaLayoutUrl === url) return
      const size = imageNodeSize(naturalWidth, naturalHeight, node.data.userResized ? Number(node.style?.width) : undefined, mediaCandidates(node.data).length)
      setNodes((current) => current.map((item) => item.id === id ? { ...item, ...size, style: { ...item.style, ...size }, data: { ...item.data, mediaLayoutUrl: url, naturalWidth, naturalHeight } } : item))
      if (canEdit) markDirty()
    },
    resize: (id, width, height) => {
      if (!canEdit) return
      setNodes((current) => current.map((node) => {
        if (node.id !== id) return node
        const size = nodeMediaKind(node) === 'image' && node.data.naturalWidth ? imageNodeSize(Number(node.data.naturalWidth), Number(node.data.naturalHeight), width, mediaCandidates(node.data).length) : { width, height }
        return { ...node, ...size, style: { ...node.style, ...size }, data: { ...node.data, userResized: true } }
      }))
      markDirty()
    },
    inspect: openInspector,
    duplicate: (id) => duplicateIds([id]),
    remove: (id) => removeIds([id]),
    preview: (id) => {
      const node = nodesRef.current.find((item) => item.id === id)
      const urls = collectMediaUrls(node?.data)
      const media = urls[clampMediaIndex(node?.data.mediaIndex, urls.length)] || node?.data.mediaUrl || node?.data.url || node?.data.cover
      if (!media) { setStatus('当前节点没有可预览的媒体'); return }
      setPreviewKind(nodeMediaKind(node))
      setPreviewUrl(String(media))
    },
    upload: (id) => { if (!canEdit) return; replaceTargetRef.current = id; setSelectedNodeId(id); uploadRef.current?.click() },
    download: (id) => {
      const node = nodesRef.current.find((item) => item.id === id)
      const urls = collectMediaUrls(node?.data)
      const media = urls[clampMediaIndex(node?.data.mediaIndex, urls.length)] || node?.data.mediaUrl || node?.data.url || node?.data.cover
      if (!media) {
        const text = String(node?.data.text || node?.data.prompt || '')
        if (!text) { setStatus('当前节点没有可下载的内容'); return }
        const url = URL.createObjectURL(new Blob([text], { type: 'text/markdown;charset=utf-8' })); const link = window.document.createElement('a'); link.href = url; link.download = `${node?.data.label || '文本'}.md`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); return
      }
      const anchor = window.document.createElement('a')
      anchor.href = String(media)
      anchor.target = '_blank'
      anchor.rel = 'noreferrer'
      anchor.download = String(node?.data.label || 'printfilm-studio-media')
      anchor.click()
    },
    openComposer: openNodeComposer,
    editGeneration: openNodeEditor,
    moreMenu: (event,id) => {
      event.preventDefault();event.stopPropagation()
      openNodeEditor(id)
      setContextMenu({left:event.clientX,top:event.clientY,id})
    },
    dropFiles: (id, files) => { setSelectedNodeId(id); void uploadOntoNode(id, files) },
    updateText: (id, next) => {
      if (!canEdit) return
      setNodes((current) => current.map((node) => node.id === id ? { ...node, data: { ...node.data, ...(nodeMediaKind(node) === 'text' ? { text: next } : { prompt: next }) } } : node))
      dirtyRef.current = true
    },
    contextMenu: (event, id) => {
      event.preventDefault()
      const keepSelection = nodesRef.current.some((node) => node.id === id && node.selected)
      const next = nodesRef.current.map((node) => ({ ...node, selected: keepSelection ? !!node.selected : node.id === id }))
      nodesRef.current = next; setNodes(next); setEdges((current) => current.map((edge) => ({ ...edge, selected: false })))
      setSelectedNodeIds(next.filter((node) => node.selected).map((node) => node.id)); setSelectedNodeId(id)
      setComposerOpen(false); setPaneAddMenu(null); setContextMenu({ left: event.clientX, top: event.clientY, id })
    },
    setMediaIndex: (id, index) => {
      const node=nodesRef.current.find(item=>item.id===id)
      if(!canEdit || !node || submittingNodeIds.has(id) || ['queued','running','awaiting_composite'].includes(String(node.data.status)))return
      const item=mediaCandidates(node.data)[index]
      if(!item)return
      commitGraph(updateStudioNode(nodesRef.current,id,adoptMediaCandidate(node.data,item)) as Node<Data>[],edgesRef.current,'已采用候选版本')
    },
    compareVariants: (id) => {
      const node=nodesRef.current.find(item=>item.id===id)
      if(!node || mediaCandidates(node.data).length<2){setStatus('至少两个版本才能对比');return}
      setCompareNodeId(id)
    },
    splitVariants: (id) => {
      if (!canEdit) { setStatus(loadIssue?.message || '当前画布为只读模式'); return }
      const source = nodesRef.current.find((item) => item.id === id)
      const candidates=mediaCandidates(source?.data || {}), urls=candidates.map(item=>item.mediaUrl)
      if (!source || urls.length < 2) { setStatus('至少两张图才能拆开'); return }
      const mediaKind=nodeMediaKind(source)
      const origin=absoluteNodePosition(source,nodesRef.current)
      const baseLabel = String(source.data.label || source.data.name || '媒体').replace(/·\d+$/, '')
      const created = urls.map((url, index) => ({
        ...newNode(mediaKind, nodesRef.current.length + index),
        position: { x: origin.x + 360 + (index % 3) * 340, y: origin.y + Math.floor(index / 3) * 240 },
        data: {
          ...candidates[index],
          label: `${baseLabel}·${index + 1}`,
          prompt: candidates[index].prompt || source.data.prompt,
          text: source.data.text,
          status: 'completed',
          mediaUrl: url,
          mediaUrls: [url],
          mediaIndex: 0,
          mediaType: mediaKind,
        },
      }))
      const nextEdges = [
        ...edgesRef.current,
        ...created.map((node, index) => ({ id: `edge-split-${Date.now()}-${index}`, source: source.id, target: node.id, type: 'smoothstep' as const })),
      ]
      commitGraph([...nodesRef.current, ...created], nextEdges, `已拆开为 ${created.length} 个媒体节点`)
      setSelectedNodeId(created[0]?.id || id)
      setSelectedNodeIds(created.map((node) => node.id))
    },
  }
  const selectAll = () => { const next = nodesRef.current.map((node) => ({ ...node, selected: true })); nodesRef.current = next; setNodes(next); setSelectedNodeIds(next.map((node) => node.id)); setSelectedNodeId(next[0]?.id || null); setComposerOpen(false) }
  const escapeCanvas = () => {
    setContextMenu(null); setPaneAddMenu(null); setSearchOpen(false); setHelpOpen(false); setComposerOpen(false); setSpacePan(false)
    setTool((current) => current === 'nodes' ? 'select' : current)
    const next = nodesRef.current.map((node) => ({ ...node, selected: false }))
    nodesRef.current = next; setNodes(next); setEdges((current) => current.map((edge) => ({ ...edge, selected: false })))
    setSelectedNodeId(null); setSelectedNodeIds([])
  }
  commandRef.current = {
    undo: undoGraph, redo: redoGraph, copy: copySelection, cut: cutSelection, paste: pasteSelection,
    duplicate: () => duplicateIds(chosenIds()), remove: () => removeIds(chosenIds()),
    group: groupSelection, ungroup: () => ungroupSelection(), mergeGroup: () => ungroupSelection(true),
    select: () => setTool('select'), hand: () => setTool('hand'), selectAll, escape: escapeCanvas,
    search: () => setSearchOpen(true), zoomIn: () => { void flow?.zoomIn() }, zoomOut: () => { void flow?.zoomOut() },
    fitView: () => { void flow?.fitView({ padding: .2, duration: 250 }) }, save: () => { void save() },
    arrange: organizeWorkspace,
    add: () => {
      if (!canEdit || viewMode !== 'canvas') return
      const rect = window.document.querySelector('.pf-flow-area')?.getBoundingClientRect()
      if (!rect) return
      const pointer = pointerRef.current
      setContextMenu(null); setPaneAddMenu(pointer ? nodeMenuPosition(pointer, { width: window.innerWidth, height: window.innerHeight }) : { left: Math.max(12, Math.min(rect.left + rect.width / 2 - 150, window.innerWidth - 320)), top: Math.max(12, Math.min(rect.top + rect.height / 2 - 240, window.innerHeight - 510)) })
    },
  }
  const menuActions = contextMenu?.kind === 'edge' ? [{ id: 'disconnect', label: '断开连线', disabled: !canEdit, danger: true }] : [
    { id: 'run_here', label: '运行到这里', disabled: !canEdit },
    { id: 'recipe', label: '保存为配方', disabled: !canEdit },
    { id: 'share', label: '复制工作区链接' },
    { id: 'rename', label: '重命名', disabled: !canEdit },
    { id: 'copy', label: '复制节点', shortcut: 'Ctrl+C' },
    { id: 'cut', label: '剪切节点', shortcut: 'Ctrl+X', disabled: !canEdit },
    { id: 'duplicate', label: '创建副本', shortcut: 'Ctrl+D', disabled: !canEdit },
    { id: 'group', label: '分组所选节点', shortcut: 'Ctrl+G', disabled: !canEdit || chosenIds().length < 2 },
    { id: 'ungroup', label: '取消分组', shortcut: 'Ctrl+Shift+G', disabled: !canEdit || !nodes.some((node) => node.type === 'group' && chosenIds().includes(node.id)) },
    { id: 'mergeGroup', label: '合并分组', shortcut: 'Ctrl+Alt+G', disabled: !canEdit || chosenIds().length < 2 || !nodes.some((node) => node.type === 'group' && node.selected) },
    ...(['horizontal', 'vertical', 'grid'] as const).map((id) => ({ id, label: { horizontal: '水平排列', vertical: '垂直排列', grid: '宫格排列' }[id], disabled: !canEdit || chosenIds().length < 2 })),
    { id: 'ask_agent', label: '询问 Printfilm 拍档' },
    { id: 'remove', label: '删除', danger: true, disabled: !canEdit },
  ]
  const isVideoComposer = selectionAction === 'video' || selectionAction === 'reference' || selectionAction === 'compose'
  const composerModels = useMemo(() => {
    if (selectionAction === 'audio') return []
    const list = isVideoComposer ? catalogVideoModels(mediaCatalog) : catalogImageModels(mediaCatalog)
    return list.filter((item) => item.available !== false).map((item) => ({ id: item.id, label: item.label || item.id }))
  }, [isVideoComposer, mediaCatalog, selectionAction])
  useEffect(() => {
    if (selectionAction === 'audio') return
    const next = resolveCatalogModelSelection(mediaCatalog, isVideoComposer ? 'video' : 'image', genModel)
    if (next !== genModel) setGenModel(next)
  }, [genModel, isVideoComposer, mediaCatalog, selectionAction])
  useEffect(() => {
    if (isVideoComposer || !mediaCatalog || !genModel) return
    const model = catalogImageModels(mediaCatalog).find((item) => item.id === genModel)
    const resolutions = model?.available_resolutions ?? model?.allowed_resolutions ?? []
    if (!resolutions.length) return
    setImageResolution((current) => resolutions.includes(current) ? current : (model?.defaults?.resolution && resolutions.includes(model.defaults.resolution) ? model.defaults.resolution : resolutions[0]))
  }, [genModel, isVideoComposer, mediaCatalog, selectionAction])
  const quoteKinds = JSON.stringify([...(selectedNode && selectedNode.data.storyKind !== 'shot_video' && mediaOf(selectedNode) ? [selectedNode] : []), ...linkedRefs.filter((node) => !hiddenRefIds.includes(node.id))].map(nodeMediaKind).filter((kind) => kind !== 'text'))
  const selectedGenerationModel = (isVideoComposer ? catalogVideoModels(mediaCatalog) : catalogImageModels(mediaCatalog)).find((model) => model.id === genModel)
  const referenceKinds = JSON.parse(quoteKinds) as MediaKind[]
  const effectiveVideoMode: StudioVideoMode = selectedNode?.data.storyKind === 'shot_video' ? 'omni_reference' : outputVideoMode || (selectionAction === 'reference' && referenceKinds.length ? 'omni_reference' : referenceKinds.length === 1 && referenceKinds[0] === 'image' ? 'image_to_video' : videoFileReferences(referenceKinds).mode)
  const storyValidation = (() => { try { storyVideoInputs(selectedNode, nodes, edges); return undefined } catch (error) { return error instanceof Error ? error.message : '分镜参考不完整' } })()
  const pendingReference=linkedRefs.find(node=>!hiddenRefIds.includes(node.id) && referenceState(node))
  const referenceValidation=pendingReference ? `关联节点「${pendingReference.data.label || '参考节点'}」${referenceState(pendingReference)}，完成后再生成` : undefined
  const videoValidation = isVideoComposer && selectionAction !== 'compose' ? storyValidation || videoReferenceError(referenceKinds, effectiveVideoMode, selectedGenerationModel?.reference_limits) : undefined
  useEffect(() => {
    if (!composerOpen || !selectionAction || selectionAction === 'crop') { setEstimateText('预计消耗 —'); return }
    if (selectionAction === 'compose') { setEstimateText('本地合成 · 无模型费用'); return }
    if (selectionAction === 'audio') {
      let active = true
      setEstimateText('正在估算…')
      void printfilmStudioApi.estimateAudio(projectId).then((quote) => { if (active) setEstimateText(`预计消耗 ${quote.estimate_yuan.toFixed(2)} 元`) }).catch(() => { if (active) setEstimateText('费用估算暂不可用') })
      return () => { active = false }
    }
    const video = selectionAction === 'video' || selectionAction === 'reference'
    if (!video) {
      let active = true
      setEstimateText('正在估算…')
      void printfilmStudioApi.estimateImage(projectId, { model_id: genModel, resolution: imageResolution, ratio: outputRatio === 'auto' ? '2:3' : outputRatio, count: Number(outputCount) || 1 }).then((quote) => { if (active) setEstimateText(`预计消耗 ${quote.estimate_yuan.toFixed(2)} 元`) }).catch(() => { if (active) setEstimateText('费用估算暂不可用') })
      return () => { active = false }
    }
    const validation = referenceValidation || videoValidation
    if (validation) { setEstimateText('预计消耗 —'); return }
    let active = true
    const controller = new AbortController()
    setEstimateText('正在估算…')
    const timer = window.setTimeout(() => {
      const quoteRefs = videoFileReferences(JSON.parse(quoteKinds) as MediaKind[], selectionAction === 'reference', effectiveVideoMode)
      void estimateStudioTool({
        tool_id: 't2v',
        model_id: genModel,
        resolution: outputResolution,
        ratio: outputRatio === 'auto' ? '16:9' : outputRatio,
        duration: outputDuration,
        generate_audio: outputAudio,
        video_mode: quoteRefs.mode,
        references: quoteRefs.references,
      }, controller.signal).then((quote) => {
        if (!active) return
        const price = catalogVideoModels(mediaCatalog).find((item) => item.id === genModel)?.prices?.[outputResolution]
        const rate = price ? `${Number(price)} 元` : `约 ${(Number(quote.estimate_yuan) / Number(outputDuration)).toFixed(3)} 元`
        setEstimateText(`${rate} / 秒 · 预计 ${quote.estimate_yuan} 元`)
      }).catch((error) => { if (active) setEstimateText(error instanceof Error ? error.message : '费用估算暂不可用') })
    }, 280)
    return () => { active = false; window.clearTimeout(timer); controller.abort() }
  }, [composerOpen, selectionAction, outputRatio, outputDuration, outputAudio, outputResolution, outputCount, genModel, imageResolution, mediaCatalog, projectId, quoteKinds, effectiveVideoMode, referenceValidation, videoValidation])
  const controls = generationControls(selectedGenerationModel, isVideoComposer)
  useEffect(() => {
    if (!composerOpen || selectionAction === 'audio' || selectionAction === 'crop') return
    const options = generationControls(selectedGenerationModel, isVideoComposer)
    const ratio = options.ratios.includes(outputRatio) ? outputRatio : options.ratios.includes(isVideoComposer ? '16:9' : '2:3') ? (isVideoComposer ? '16:9' : '2:3') : selectedGenerationModel?.defaults?.aspect_ratio && options.ratios.includes(selectedGenerationModel.defaults.aspect_ratio) ? selectedGenerationModel.defaults.aspect_ratio : options.ratios[0]
    const resolution = isVideoComposer ? options.resolutions.includes(outputResolution) ? outputResolution : options.resolutions[0] : options.resolutions.includes(imageResolution) ? imageResolution : options.resolutions[0]
    const duration = options.durations.includes(outputDuration) ? outputDuration : options.durations[0] || '5'
    if (ratio !== outputRatio) setOutputRatio(ratio)
    if (isVideoComposer) { if (resolution !== outputResolution) setOutputResolution(resolution); if (duration !== outputDuration) setOutputDuration(duration) }
    else if (resolution !== imageResolution) setImageResolution(resolution)
    if (canEdit && selectedNodeId && genModel) {
      const patch = {modelId:genModel,ratio,resolution,...(isVideoComposer ? {duration} : {})}
      const node = nodesRef.current.find(item=>item.id===selectedNodeId)
      if (node && Object.entries(patch).some(([key,value])=>node.data[key]!==value)) {
        setNodes(current=>updateStudioNode(current,selectedNodeId,patch) as Node<Data>[]); dirtyRef.current = true
      }
    }
  }, [composerOpen, selectionAction, selectedGenerationModel, isVideoComposer, outputRatio, outputResolution, outputDuration, imageResolution, genModel, canEdit, selectedNodeId])

  const rememberParameter = (key: string, value: string | boolean) => { if (!canEdit || !selectedNodeId) return; setNodes((current) => updateStudioNode(current, selectedNodeId, { [key]: value }) as Node<Data>[]); dirtyRef.current = true }
  const linkedPromptNode = nodes.find((node) => node.id === selectedNode?.data.promptNodeId && ['text', 'script'].includes(node.type || ''))
  const strictStoryPrompt = selectedNode?.data.storyKind === 'shot_video' || ['character','scene'].includes(String(selectedNode?.data.storyKind))
  const rawComposerPrompt = linkedPromptNode && (strictStoryPrompt || String(linkedPromptNode.data.text || '').trim()) ? String(linkedPromptNode.data.text || '') : genPrompt
  const liveComposerPrompt = linkedPromptNode && selectedNode?.data.storyKind === 'shot_video' ? linkedWritingResult(rawComposerPrompt,writingContext(linkedPromptNode,nodes,edges).references) : rawComposerPrompt
  const writeComposerPrompt = (value: string) => {
    setGenPrompt(value)
    if (linkedPromptNode && canEdit) {
      const promptId = linkedPromptNode.id
      setNodes((current) => updateStudioNode(current, promptId, { text: value }) as Node<Data>[])
      dirtyRef.current = true
    } else if (canEdit && selectedNodeId) {
      setNodes((current) => updateStudioNode(current, selectedNodeId, { prompt: value }) as Node<Data>[])
      dirtyRef.current = true
    }
  }
  const composerState: StudioComposerState | null = (composerOpen && selectionAction && selectedNodeId) ? {
    nodeId: selectedNodeId,
    action: selectionAction,
    prompt: liveComposerPrompt,
    onPrompt: writeComposerPrompt,
    chips: composerChips,
    onRemoveChip: (id) => { const text = composerChips.find((item) => item.id === id)?.text; setComposerChips((items) => items.filter((item) => item.id !== id)); if (text) { const next = liveComposerPrompt.replace(text, '').trim(); writeComposerPrompt(next); if (selectedNode?.data.storyKind !== 'shot_video') rememberParameter('prompt', next) } },
    onAddChip: (chip, append) => { setComposerChips((items) => items.some((item) => item.id === chip.id) ? items : [...items, { ...chip, text: append }]); const next = liveComposerPrompt.includes(append) ? liveComposerPrompt : `${liveComposerPrompt}\n${append}`.trim(); writeComposerPrompt(next); if (selectedNode?.data.storyKind !== 'shot_video') rememberParameter('prompt', next) },
    refs: linkedRefs.filter(node=>!hiddenRefIds.includes(node.id)).map(node=>({id:node.id,url:mediaOf(node),mediaKind:nodeMediaKind(node),label:String(node.data.label||node.data.name||'参考节点'),status:referenceState(node)})),
    onFocusRef: id=>focusNode(id),
    onRemoveRef: (id) => {
      if(!canEdit || !selectedNode) return
      const data={...selectedNode.data}
      if(data.promptNodeId===id) delete data.promptNodeId
      if(Array.isArray(data.referenceNodeIds)) data.referenceNodeIds=data.referenceNodeIds.filter(item=>item!==id)
      commitGraph(nodesRef.current.map(node=>node.id===selectedNode.id?{...node,data}:node),edgesRef.current.filter(edge=>!(edge.source===id&&edge.target===selectedNode.id)),'已移除参考关联')
    },
    onAddRef: () => { setReferenceTargetId(selectedNodeId); setAssetsOpen(true) },
    mentions: {
      connected: linkedRefs.filter((node) => !hiddenRefIds.includes(node.id)).map((node, index) => ({ id: node.id, label: String(node.data.label || node.data.name || `图${index + 1}`), url: mediaOf(node), mediaKind: nodeMediaKind(node), hint: referenceState(node) || `图${index + 1}`, source: 'node' as const })),
      canvas: nodes.filter((node) => node.id !== selectedNodeId && mediaOf(node) && !validateStudioConnection({ source: node.id, target: selectedNodeId }, nodes, edges) && !linkedRefs.some((item) => item.id === node.id)).map((node) => ({ id: node.id, label: String(node.data.label || node.data.name || '图片'), url: mediaOf(node), mediaKind: nodeMediaKind(node), hint: '图片', source: 'node' as const })),
      assets: assets.filter((asset) => (asset.url || asset.cover) && (selectionAction === 'compose' ? assetMediaKind(asset) === 'video' : isVideoComposer ? true : selectionAction === 'audio' ? false : assetMediaKind(asset) === 'image')).map((asset) => ({ id: String(asset.id), label: asset.name || `素材 #${asset.id}`, url: String(asset.cover || asset.url || ''), mediaKind: assetMediaKind(asset), hint: '素材', source: 'asset' as const })),
    },
    onMention: pickMention,
    modelId: selectionAction === 'audio' ? '' : genModel,
    controls,
    videoMode: effectiveVideoMode,
    onVideoModeChange: (value) => { setOutputVideoMode(value); rememberParameter('videoMode', value) },
    videoModeOptions: VIDEO_MODES.map((mode) => { const limits = selectedGenerationModel?.reference_limits; const disabled = selectedNode?.data.storyKind === 'shot_video' && mode.id !== 'omni_reference' || !!limits && (mode.id === 'first_last_frame' ? limits.images < 2 : mode.id === 'image_to_video' ? limits.images < 1 : mode.id === 'omni_reference' ? limits.images + limits.videos + limits.audios === 0 : false); return { ...mode, disabled, hint: disabled ? '当前模型不支持' : undefined } }),
    validationMessage: referenceValidation || videoValidation || (incompatibleRefs.length ? '参考类型不兼容，请移除不支持的连线' : undefined) || (submissionError?.nodeId === selectedNodeId ? submissionError.message : undefined),
    voice: outputVoice,
    onVoiceChange: (value) => { setOutputVoice(value); rememberParameter('voice', value) },
    modelOptions: composerModels.length ? composerModels : [{ id: selectionAction === 'audio' ? '' : genModel || '', label: selectionAction === 'audio' ? '默认语音模型' : catalogModelLabel(genModel, composerModels, isVideoComposer ? '默认视频模型' : '默认生图模型') }],
    onModelChange: (value) => { setGenModel(value); rememberParameter('modelId', value) },
    ratio: outputRatio,
    onRatioChange: (value) => { setOutputRatio(value); rememberParameter('ratio', value) },
    count: outputCount,
    onCountChange: (value) => { const count = selectionAction === 'inpaint' ? '1' : value; setOutputCount(count); rememberParameter('count', count) },
    resolution: isVideoComposer ? outputResolution : imageResolution,
    onResolutionChange: (value) => { if (isVideoComposer) setOutputResolution(value); else setImageResolution(value); rememberParameter('resolution', value) },
    duration: outputDuration,
    onDurationChange: (value) => { setOutputDuration(value); rememberParameter('duration', value) },
    estimate: estimateText,
    isVideo: isVideoComposer,
    generateAudio: outputAudio,
    onAudioChange: (value) => { setOutputAudio(value); rememberParameter('generateAudio', value) },
    onClose: () => setComposerOpen(false),
    onSubmit: () => {
      if (selectionAction === 'crop') {
        const ratio = outputRatio === 'auto' ? 2 / 3 : outputRatio === '16:9' ? 16 / 9 : outputRatio === '9:16' ? 9 / 16 : outputRatio === '1:1' ? 1 : outputRatio === '3:2' ? 3 / 2 : 2 / 3
        void applyCrop(ratio)
      } else void runNodeGeneration(selectionAction)
    },
    canSubmit: canEdit && !generationRunning && !referenceValidation && !videoValidation && !incompatibleRefs.length && !['queued', 'running', 'awaiting_composite'].includes(String(selectedNode?.data.status)) && (selectionAction === 'crop' || selectionAction === 'compose' || !!liveComposerPrompt.trim()),
  } : null


  const focusNode = (id: string) => {
    const node = nodesRef.current.find((item) => item.id === id)
    if (!node) return
    if (id !== selectedNodeId) setComposerOpen(false)
    setSelectedNodeId(id); setSelectedNodeIds([id]); setPanelsSuppressed(false)
    setNodes((current) => current.map((item) => ({ ...item, selected: item.id === id })))
    if (viewMode === 'canvas') { void flow?.fitView({ nodes: [{ id }], padding: .5, duration: 300, maxZoom: 1 }); return }
    const position = flow?.getInternalNode(id)?.internals.positionAbsolute || node.position
    const main = window.document.querySelector('.pf-studio-main')?.getBoundingClientRect()
    const width = node.width || node.measured?.width || 320, height = node.height || node.measured?.height || 240
    setViewport({ x: (main?.width || window.innerWidth) / 2 - position.x - width / 2, y: window.innerHeight / 2 - position.y - height / 2, zoom: 1 })
    setFlowKey((value) => value + 1); setViewMode('canvas')
  }

  const openPaneAddMenu = (event: { clientX: number; clientY: number; preventDefault: () => void; target: EventTarget | null }) => {
    if (!canEdit) return
    const target = event.target as HTMLElement | null
    if (target?.closest('.react-flow__node,.react-flow__edge')) { setPaneAddMenu(null); return }
    if (target?.closest('.pf-pane-add') || target?.closest('.pf-workspace-toolbar') || target?.closest('.pf-composer-card') || target?.closest('.pf-context-menu')) return
    event.preventDefault()
    setContextMenu(null)
    setPaneAddMenu(nodeMenuPosition({ x: event.clientX, y: event.clientY }, { width: window.innerWidth, height: window.innerHeight }))
  }
  const accessIssue: WorkspaceIssue | null = sessionExpired ? workspaceIssue({ status: 401 })
    : !validProjectId ? { title: '项目地址无效', message: '请从项目列表打开工作台。', action: 'back' }
    : loadIssue
  const retryAccess = () => {
    setLoadIssue(null)
    setLoadAttempt((value) => value + 1)
  }
  const loginAgain = () => {
    if (dirtyRef.current) downloadCanvas()
    navigate(studioLoginPath(window.location.pathname + window.location.search + window.location.hash))
  }
  const navigateWorkspace = (path: string) => { void (async () => { if (dirtyRef.current && !(await save())) return; navigate(path) })() }
  const selectStoryboardNode = (id: string | null) => {
    setSelectedNodeId(id); setSelectedNodeIds(id ? [id] : []); setPanelsSuppressed(false)
    if (!id) { setComposerOpen(false); setTextGenerationNodeId(null); return }
    const node = nodesRef.current.find(item => item.id === id)
    if (!node) return
    if (nodeMediaKind(node) === 'text') { setComposerOpen(false); return }
    setTextGenerationNodeId(null)
    openSelectionComposer(nodeMediaKind(node) === 'audio' ? 'audio' : nodeMediaKind(node) === 'image' ? 'edit' : node.type === 'compose' ? 'compose' : 'video', node.type === 'compose' ? undefined : nodeDraft(node), id)
  }
  const composeStoryboard = (ids: string[]) => {
    if (!canEdit) return
    const created = addNode('compose', undefined, { label: '分镜合成', editor: 'compose' })
    if (!created) return
    commitGraph(nodesRef.current, [...edgesRef.current, ...ids.map(source => ({ id: `edge-${crypto.randomUUID()}`, source, target: created.id }))], '已按分镜顺序连接合成节点')
    openSelectionComposer('compose', undefined, created.id)
  }
  const workspaceAction = (action: WorkspaceAction) => {
    setWorkspacePanel(null)
    if (action === 'help') {
      tourAgentWasOpen.current = agentOpen
      setViewMode('canvas'); setHelpOpen(false); setAssetsOpen(false); setHistoryOpen(false); setPaneAddMenu(null); setTourOpen(true)
      return
    }
    if (action === 'home') return navigateWorkspace('/canvas')
    if (action === 'episodes') return navigateWorkspace(`/drama/projects/${projectId}/episodes`)
    if (action === 'pricing') return navigateWorkspace('/pricing')
    if (action === 'agent') return setAgentOpen(true)
    if (action === 'assets') return setAssetsOpen(true)
    if (action === 'history' || action === 'records') return setHistoryOpen(true)
    if (action === 'tidy') return organizeWorkspace()
    if (action === 'download') return downloadCanvas()
    if (action === 'save') { void save(); return }
    if (action === 'import') { if (canEdit) importCanvasRef.current?.click(); return }
    if (action === 'search') { setViewMode('canvas');setSearchOpen(true);return }
    if (action === 'recipes') {setRecipeDraft(undefined);setRecipeOpen(true);return}
    if (action === 'video' || action === 'audio') {setViewMode('canvas');const created=addNode(action);if(created)openSelectionComposer(action,undefined,created.id);return}
    if (action === 'theme') {const next=workspaceTheme==='light'?'dark':'light';setWorkspaceTheme(next);localStorage.setItem('printfilm.theme',next);return}
    setWorkspacePanel(action)
  }
  return <StudioNodeActionsContext.Provider value={nodeActions}><StudioComposerContext.Provider value={composerState}><div className={`pf-studio-shell is-immersive is-${workspaceTheme}`} onMouseDown={(event) => { if (event.button === 2) return; const target = event.target as HTMLElement | null; if (target?.closest('.pf-pane-add') || target?.closest('.pf-workspace-toolbar') || target?.closest('.pf-context-menu')) return; setContextMenu(null); setPaneAddMenu(null) }}>
    <input hidden ref={importCanvasRef} type="file" accept=".json,application/json" onChange={async (event) => {
      const file = event.target.files?.[0]; event.target.value = ''; if (!file || !canEdit) return
      try {
        if (file.size > 5 * 1024 * 1024) throw new Error('画布文件不能超过 5MB')
        const doc = decodeCanvasDocument(JSON.parse(await file.text()))
        const available = await printfilmStudioApi.getAssets(projectId)
        if (!mountedRef.current || !canEditRef.current) return
        const ids = new Set(available.assets.map((asset) => asset.id))
        if (doc.nodes.some((node) => node.data.assetId && !ids.has(Number(node.data.assetId)))) throw new Error('画布引用了其他项目的素材，请先将这些素材导入本项目')
        if (!window.confirm('使用导入文件替换当前画布？可以撤销本次替换。')) return
        documentExtrasRef.current = doc
        commitGraph(doc.nodes as Node<Data>[], doc.edges as Edge[], '画布已导入，正在保存')
        setViewport(doc.viewport); setFlowKey((key) => key + 1)
      } catch (error) { setStatus(error instanceof Error ? error.message : '画布导入失败') }
    }} />
    <input ref={uploadRef} className="pf-upload-input" type="file" accept="image/*,video/*,audio/*" multiple onChange={(event) => { const files = event.target.files; const replacement = replaceTargetRef.current; replaceTargetRef.current = null; if (replacement && files?.length) { void uploadOntoNode(replacement, files); event.target.value = ''; return }; const target = selectedNodeId ? nodesRef.current.find((node) => node.id === selectedNodeId) : undefined; const empty = target && !(target.data.mediaUrl || target.data.url || target.data.cover) && (target.type === 'image' || target.type === 'video' || target.type === 'audio' || target.type === 'asset' || target.type === 'inpaint' || target.type === 'outpaint' || target.type === 'upscale'); if (empty && selectedNodeId) void uploadOntoNode(selectedNodeId, files); else void uploadFiles(files); event.target.value = '' }} />
    <WorkspaceChrome dockWidth={agentOpen ? agentDockWidth : 0} title={projectTitle || `项目 #${projectId || '—'}`} status={savingRef.current ? '保存中…' : saveBlockedRef.current ? '保存冲突' : dirtyRef.current ? '待保存' : !canvasReady ? '加载中…' : '已保存'} balance={wallet ? wallet.balance_yuan.toFixed(2) : '—'} mode={viewMode} onMode={setViewMode} onAction={workspaceAction} />
    {tourOpen && <WorkspaceTour onClose={() => { setTourOpen(false); setAgentOpen(tourAgentWasOpen.current) }} onStep={step => {
      setPaneAddMenu(null)
      if (step === 'agent' || step === 'story') setAgentOpen(true)
      else setAgentOpen(false)
    }} />}
    {workspacePanel === 'defaults' && <DefaultModelPanel onClose={() => setWorkspacePanel(null)} />}
    {workspacePanel === 'wallet' && <WalletPanel balance={wallet ? wallet.balance_yuan.toFixed(2) : '—'} onClose={() => setWorkspacePanel(null)} onNavigate={navigateWorkspace} />}
    {workspacePanel === 'share' && <SharePanel projectId={projectId} onClose={() => setWorkspacePanel(null)} />}
    {workspacePanel && !['defaults','wallet','share'].includes(workspacePanel) && <WorkspaceUtilityPanel key={workspacePanel} panel={workspacePanel} projectId={projectId} title={projectTitle} canvasName={String(documentExtrasRef.current.canvasName || '画布 1')} document={document} writable={canEdit && (workspacePanel !== 'project' || projectOwner)} onClose={() => setWorkspacePanel(null)} onAction={workspaceAction} onNavigate={navigateWorkspace} settings={{snap,showEdges,focusStoryEdges,showMap}} onSetting={(key,value) => { if(key==='snap')setSnap(value); if(key==='showEdges')setShowEdges(value); if(key==='focusStoryEdges')setFocusStoryEdges(value); if(key==='showMap')setShowMap(value) }} onRename={async(title,canvasName) => { await dramaApi.updateProject(projectId,{title}); setProjectTitle(title); documentExtrasRef.current={...documentExtrasRef.current,canvasName};setNodes(current=>[...current]);dirtyRef.current=true;setStatus('待保存') }} onRestore={(snapshot) => { const doc=decodeCanvasDocument(snapshot); documentExtrasRef.current=doc;commitGraph(doc.nodes as Node<Data>[],doc.edges as Edge[],'已恢复历史版本，正在保存');setViewport(doc.viewport);setFlowKey(key=>key+1) }} />}
    <output className="pf-workspace-feedback" aria-live="polite">{status}</output>
    <main className="pf-studio-main" style={{ marginRight: agentOpen ? agentDockWidth : 0 }}>
      {!canEdit && <WorkspaceAccessNotice issue={accessIssue} waiting={!canvasReady ? '正在加载画布' : '正在取得编辑权'} centered={!canvasReady && !dirtyRef.current} hasDraft={dirtyRef.current} onLogin={loginAgain} onRetry={retryAccess} onBack={() => { if (dirtyRef.current && !window.confirm('当前有未保存修改，是否离开工作台？')) return; navigate('/canvas') }} />}
      <aside className="pf-left-rail" hidden><button type="button" className={tool === 'select' ? 'is-active' : ''} aria-pressed={tool === 'select'} onClick={() => setTool('select')}><LayoutGrid size={18} /><span>选择</span></button><button type="button" className={tool === 'hand' ? 'is-active' : ''} aria-pressed={tool === 'hand'} onClick={() => setTool('hand')}><Map size={18} /><span>移动</span></button><button type="button" className={tool === 'nodes' ? 'is-active' : ''} onClick={() => setTool('nodes')}><Plus size={18} /><span>节点</span></button><button type="button" onClick={() => setAssetsOpen((value) => !value)} className={assetsOpen ? 'is-active' : ''}><FolderOpen size={18} /><span>资产</span></button><div className="pf-rail-spacer" /><button type="button" onClick={() => setAgentOpen(true)}><Bot size={18} /><span>Agent</span></button></aside>
      {tool === 'nodes' && <AddNodeMenu onAdd={addFromCatalog} onClose={() => setTool('select')} />}
      {historyOpen && <HistoryPicker writable={canEdit} onPick={pickHistoryRun} onClose={() => setHistoryOpen(false)} />}
      {viewMode === 'document' ? <WorkspaceDocument nodes={nodes} writable={canEdit} onText={nodeActions.updateText} onLocate={focusNode} /> : viewMode === 'storyboard' ? <StoryboardWorkspace nodes={nodes} selectedId={selectedNodeId} onSelect={selectStoryboardNode} onAdd={addNode} onLocate={focusNode} onSave={() => void save()} onSequence={ids => { if (canEdit) commitGraph(setStorySequence(nodesRef.current, ids) as Node<Data>[], edgesRef.current, '分镜顺序已更新') }} onDuration={(id, seconds) => { if (canEdit) commitGraph(updateStudioNode(nodesRef.current, id, { storyboardDuration: seconds }) as Node<Data>[], edgesRef.current, '分镜停留时间已更新') }} onCompose={composeStoryboard} onUndo={undoGraph} onRedo={redoGraph} canUndo={pastRef.current.length > 0} canRedo={futureRef.current.length > 0} onAssets={() => setAssetsOpen(true)} onAgent={() => setAgentOpen(true)} /> : <section className="pf-flow-area" onPointerMove={(event) => { pointerRef.current = { x: event.clientX, y: event.clientY }; if (flow) presence.update({cursor:flow.screenToFlowPosition({x:event.clientX,y:event.clientY})}) }} onPointerLeave={() => { pointerRef.current = null; presence.update({cursor:null}) }} data-tool={tool === 'hand' || spacePan ? 'hand' : 'select'} onDragOver={(event) => { if (event.dataTransfer.types.includes(ASSET_DRAG_TYPE)) { event.preventDefault(); event.dataTransfer.dropEffect = 'copy' } }} onDropCapture={(event) => { const value = event.dataTransfer.getData(ASSET_DRAG_TYPE); if (!value) return; event.preventDefault(); event.stopPropagation(); const id = Number(value); if (Number.isSafeInteger(id) && id > 0) void placeAsset(id, { x: event.clientX, y: event.clientY }).catch((error) => setStatus(error instanceof Error ? error.message : '素材添加失败')) }} onContextMenuCapture={(event) => openPaneAddMenu(event)} onDoubleClickCapture={event => { if ((event.target as HTMLElement).classList.contains('react-flow__pane')) { event.preventDefault(); openPaneAddMenu(event) } }}><div className="pf-flow-tip"><Sparkles size={13} /> 无限画布 · 双击或右键添加节点，拖动空白处平移 · Shift 框选{focusStoryEdges && nodes.some((node) => node.data.storyKind === 'shot_video') ? ' · 选中分镜查看关联线' : ''}</div><ReactFlow onlyRenderVisibleElements={nodes.length>80 && !composerOpen && !textGenerationNodeId} minZoom={0.08} key={flowKey} nodes={nodes} edges={displayedEdges} nodeTypes={nodeTypes} edgeTypes={studioEdgeTypes} onInit={setFlow} defaultViewport={viewport} onMoveEnd={onMoveEnd} onNodeDragStart={startNodeDrag} onNodeDrag={(_event,node,dragged)=>presence.update({action:'dragging',node_ids:dragged.map(item=>item.id).slice(0,32),positions:dragged.slice(0,32).map(item=>({id:item.id,...absoluteNodePosition(item,[...nodesRef.current.filter(old=>old.id!==node.id),node])}))})} onNodeDragStop={stopNodeDrag} onSelectionStart={() => {setPanelsSuppressed(true);presence.update({action:'selecting'})}} onSelectionEnd={() => {setPanelsSuppressed(false);presence.update({action:'idle'})}} onNodeContextMenu={(event, node) => nodeActions.contextMenu(event, node.id)} onEdgeContextMenu={(event, edge) => { event.preventDefault(); setPaneAddMenu(null); setContextMenu({ left: event.clientX, top: event.clientY, id: edge.id, kind: 'edge' }) }} onNodeClick={selectCanvasNode} onSelectionChange={onSelectionChange} onPaneClick={clickCanvasPane} deleteKeyCode={null} onNodesChange={handleNodesChange} onEdgesChange={handleEdgesChange} onConnect={connect} onConnectStart={(_event,params)=>presence.update({action:'connecting',node_ids:params.nodeId?[params.nodeId]:[]})} onConnectEnd={()=>presence.update({action:'idle'})} isValidConnection={(connection) => !validateStudioConnection(connection, nodesRef.current, edgesRef.current)} nodesDraggable={canEdit && tool !== 'hand' && !spacePan} nodesConnectable={canEdit} snapToGrid={snap} snapGrid={[16, 16]} panOnDrag={[0, 1]} panActivationKeyCode={null} selectionOnDrag={false} selectionMode={SelectionMode.Partial} selectionKeyCode={tool === 'select' && !spacePan ? 'Shift' : null} multiSelectionKeyCode={['Shift', 'Control', 'Meta']} zoomOnDoubleClick={false} proOptions={{ hideAttribution: true }}><CollaborationOverlay store={presence.store} nodes={nodes} /><Background color="#d1d5db" gap={22} size={1.1} />{showMap && <MiniMap position="bottom-left" nodeColor="#5c83b9" maskColor="rgba(227,235,247,.65)" />}</ReactFlow>
        <div className="pf-canvas-dock">
        <WorkspaceToolbar label="画布操作条">
          <button type="button" className="pf-toolbar-primary" disabled={!canEdit} onClick={(event) => { const rect = event.currentTarget.getBoundingClientRect(); setPaneAddMenu((value) => value ? null : { left: Math.max(12, rect.left - 110), top: Math.max(12, rect.top - 490) }) }} title="添加节点" aria-label="添加节点"><Plus size={20} /></button>
          <button type="button" className={tool === 'select' ? 'is-active' : ''} aria-pressed={tool === 'select'} onClick={() => setTool('select')} title="选择 · 拖空白处框选，空格拖动平移 (V)" aria-label="选择工具"><MousePointer2 size={18} /></button>
          <button type="button" className={tool === 'hand' ? 'is-active' : ''} aria-pressed={tool === 'hand'} onClick={() => setTool('hand')} title="平移 (H)" aria-label="平移工具"><Hand size={18} /></button>
          <button type="button" onClick={() => setSearchOpen(true)} title="搜索画布节点" aria-label="搜索画布节点"><Search size={18} /></button>
          <button type="button" className="pf-tidy-trigger pf-toolbar-label" disabled={!canEdit || !!tidyRun || !nodes.length} onClick={organizeWorkspace} title="整理画布 · Alt + Shift + F" aria-label="整理画布"><Sparkles size={18} /><span>整理</span></button>
          <button type="button" onClick={() => setHelpOpen(!helpOpen)} title="快捷键" aria-label="快捷键帮助"><CircleHelp size={18} /></button>
          <span className="pf-dock-sep" />
          <button type="button" aria-label="撤销" title="撤销" disabled={!canEdit || !pastRef.current.length} onClick={undoGraph}><Undo2 size={19} /></button>
          <button type="button" aria-label="重做" title="重做" disabled={!canEdit || !futureRef.current.length} onClick={redoGraph}><Redo2 size={19} /></button>
        </WorkspaceToolbar>
        <CanvasAgentButton open={agentOpen} running={agentRunning} onClick={() => setAgentOpen(value => !value)} />
        </div>
        <WorkspaceToolbar className="pf-canvas-navigation" label="画布视图操作条">
          <button type="button" aria-label="项目素材" title="项目素材" aria-expanded={assetsOpen} onClick={() => { setReferenceTargetId(null); setAssetsOpen(!assetsOpen) }}><FolderOpen size={18} /></button>
          <button type="button" aria-label="配方库" title="配方库" onClick={() => { setRecipeDraft(undefined); setRecipeOpen(true) }}><LayoutGrid size={17} /></button>
          <button type="button" aria-label="小地图" title="小地图" aria-pressed={showMap} onClick={() => setShowMap(!showMap)}><Map size={17} /></button>
          <button type="button" aria-label={showEdges ? '隐藏引线' : '显示引线'} title={showEdges ? '隐藏引线' : '显示引线'} aria-pressed={showEdges} onClick={() => setShowEdges(!showEdges)}><Link2 size={17} /></button>
          {nodes.some((node) => node.data.storyKind === 'shot_video') && <button type="button" aria-label="聚焦参考连线" title={focusStoryEdges ? '保留写作与输出连线，选中分镜展开参考；点击显示全部' : '当前显示全部连线，点击聚焦选中分镜的参考'} aria-pressed={focusStoryEdges} onClick={() => setFocusStoryEdges(!focusStoryEdges)}><MousePointer2 size={17} /></button>}
          <button type="button" aria-label="适配画布" title="适配画布" onClick={() => void flow?.fitView({ padding: .2, duration: 250 })}><Scan size={17} /></button>
          <button type="button" aria-label="缩小画布" title="缩小画布" onClick={() => void flow?.zoomOut()}><ZoomOut size={15} /></button><span className="pf-toolbar-zoom">{Math.round(viewport.zoom * 100)}%</span><button type="button" aria-label="放大画布" title="放大画布" onClick={() => void flow?.zoomIn()}><ZoomIn size={15} /></button>
        </WorkspaceToolbar>
        {tidyRun && <CanvasTidyMotion run={tidyRun} flow={flow} onComplete={() => { tidyRunningRef.current = false; setTidyRun(null); setPanelsSuppressed(false); setStatus(`已整理 ${tidyRun.order.length} 个节点 · ${tidyRun.sections.length} 个分区，可撤销`) }} />}
        {searchOpen && <CanvasSearch nodes={nodes} onClose={() => setSearchOpen(false)} onSelect={focusNode} />}
        {helpOpen && <section className="pf-canvas-help"><header><b>画布操作</b><button aria-label="关闭快捷键" onClick={() => setHelpOpen(false)}><X size={14} /></button></header><p>单击选择、拖动节点；左键拖空白处（含分组留白）平移，Shift + 左键拖动框选；拖分组标题移动整个分组。</p><p>双击节点名称改名；右下角拖动调整尺寸。</p><dl><dt>V / H</dt><dd>选择 / 平移</dd><dt>Ctrl + C / V / D</dt><dd>复制 / 粘贴 / 创建副本</dd><dt>Ctrl + Z / Ctrl + Shift + Z</dt><dd>撤销 / 重做</dd><dt>Tab / Esc</dt><dd>添加节点 / 关闭并取消选择</dd><dt>Space / 鼠标中键</dt><dd>临时平移</dd><dt>Alt + 拖动</dt><dd>复制节点内容</dd><dt>Ctrl + Alt + 拖动</dt><dd>复制节点及输入连线</dd><dt>Ctrl + A / X</dt><dd>全选 / 剪切</dd><dt>Ctrl + G / Ctrl + Shift + G</dt><dd>分组 / 取消分组</dd><dt>Ctrl + Alt + G</dt><dd>合并分组</dd><dt>Alt + Shift + F</dt><dd>整理画布</dd><dt>Ctrl + F / 0 / + / −</dt><dd>搜索 / 适应 / 放大 / 缩小</dd><dt>Delete / Backspace</dt><dd>删除所选节点或连线</dd></dl></section>}


      </section>}
      {assetsOpen && <AssetLibraryPanel projectId={projectId} assets={assets} writable={canEdit} acceptKinds={referenceTargetId ? nodeMediaKind(nodes.find((node) => node.id === referenceTargetId)) === 'image' ? ['image'] : nodeMediaKind(nodes.find((node) => node.id === referenceTargetId)) === 'audio' ? [] : ['image_to_video', 'first_last_frame'].includes(String(nodes.find((node) => node.id === referenceTargetId)?.data.videoMode)) ? ['image'] : nodes.find((node) => node.id === referenceTargetId)?.data.videoMode === 'text_to_video' ? [] : ['image', 'video', 'audio'] : undefined} onClose={() => { setAssetsOpen(false); setReferenceTargetId(null) }} onUpload={() => { setSelectedNodeId(null); uploadRef.current?.click() }} onGenerate={() => addFromCatalog({ id: 'image', label: '图片', type: 'image', editor: 'edit' })} onPick={(asset) => referenceTargetId ? placeReferenceAsset(asset, referenceTargetId) : placeAsset(asset.id)} />}
      {agentOpen && <AgentPanel proposals={{ nodes, states: (document.agentProposalStates || {}) as ProposalStates, writable: canEdit, busy: agentRunning || proposalBusy, onAction: changeAgentProposal, onRun: openDependencyRun }} selectedNodeIds={selectedNodeIds} onHistoryChange={(session) => { setSessionId(session.id); setAgentEvents(sessionEvents(session)); setAnswer('') }} onDockWidth={setAgentDockWidth} projectId={projectId} sessionId={sessionId} events={agentEvents} answer={answer} running={agentRunning} prompt={prompt} nodes={nodes} edges={edges} assets={assets} headers={editLockRequestHeaders(canvasTarget)} writable={canEdit} onPrompt={setPrompt} onSend={askAgent} onRepairStory={repairAgentStory} onGenerateMedia={(id, kind) => { const node = nodesRef.current.find(item => item.id === id); if (node && !nodeResultReady(node)) { openDependencyRun([id]); return }; setSelectedNodeIds([id]); openSelectionComposer(kind === 'video' ? 'video' : 'edit', undefined, id) }} onStop={() => void stopAgent()} onClose={() => setAgentOpen(false)} onSelectSession={(id) => { if (agentRunning) return; agentAbort.current?.abort(); agentAbort.current = null; setSessionId(id); setAnswer(''); setAgentEvents([]) }} />}
    </main>
    <footer className={`pf-studio-footer${bottomOpen ? ' is-open' : ''}`} hidden={!bottomOpen}><button type="button" className="pf-footer-toggle" onClick={() => setBottomOpen((value) => !value)}><Box size={14} /> 资产与任务 <ChevronDown size={14} /></button>{bottomOpen && <div className="pf-footer-drawer"><div className="pf-drawer-tab is-active"><Box size={14} /> 资产 <span>{nodes.length}</span></div><div className="pf-drawer-tab"><Sparkles size={14} /> 任务 <span>{tasks.length}</span></div><button type="button" onClick={() => setAssetsOpen(true)}>打开素材库</button><div className="pf-task-list">{tasks.slice(0, 4).map((task) => <div className="pf-task-row" key={task.id}><span>{task.task_type}</span><b className={`is-${task.status}`}>{task.status}</b></div>)}</div><button type="button" disabled={!canEdit} onClick={() => importCanvasRef.current?.click()}>导入画布 JSON</button><button type="button" disabled={!canEdit} onClick={() => void save()}>立即保存</button><button type="button" className="pf-reset-button" onClick={() => void resetCanvas()}>清空当前画布</button></div>}<span className="pf-footer-note">{agentOpen ? 'Agent 已连接当前画布' : 'Agent 已收起'}</span>{!agentOpen && <button type="button" className="pf-open-agent" onClick={() => setAgentOpen(true)}><Bot size={14} /> 打开 Agent</button>}</footer>
    {paneAddMenu && createPortal(
      <div className="pf-pane-add" style={{ left: paneAddMenu.left, top: paneAddMenu.top }} onMouseDown={(event) => event.stopPropagation()} onContextMenu={(event) => event.preventDefault()}>
        <AddNodeMenu floating onAdd={(item) => addFromCatalog(item, paneAddMenu.position)} onClose={() => setPaneAddMenu(null)} />
      </div>,
      window.document.body,
    )}
        {previewUrl && <div className="pf-media-preview" role="dialog" aria-modal="true" onClick={() => setPreviewUrl(null)}><div className="pf-media-preview-card" onClick={(event) => event.stopPropagation()}><button type="button" aria-label="关闭预览" onClick={() => setPreviewUrl(null)}><X size={17} /></button>{previewKind === 'video' ? <video src={previewUrl} controls autoPlay onLoadedMetadata={(event) => { const start = Number(selectedNode?.data.clipStart || 0); if (start) event.currentTarget.currentTime = start }} /> : previewKind === 'audio' ? <audio src={previewUrl} controls autoPlay onLoadedMetadata={(event) => { const start = Number(selectedNode?.data.clipStart || 0); if (start) event.currentTarget.currentTime = start }} /> : <img src={previewUrl} alt="节点预览" />}</div></div>}
    {compareNodeId && nodes.some(node=>node.id===compareNodeId) && <MediaComparison key={compareNodeId} data={nodes.find(node=>node.id===compareNodeId)!.data} video={nodeMediaKind(nodes.find(node=>node.id===compareNodeId))==='video'} writable={canEdit && !submittingNodeIds.has(compareNodeId) && !['queued','running','awaiting_composite'].includes(String(nodes.find(node=>node.id===compareNodeId)?.data.status))} onClose={()=>setCompareNodeId(null)} onAdopt={item=>{const node=nodesRef.current.find(node=>node.id===compareNodeId);if(!node||!canEditRef.current)return;commitGraph(updateStudioNode(nodesRef.current,node.id,adoptMediaCandidate(node.data,item)) as Node<Data>[],edgesRef.current,'已采用候选版本');setCompareNodeId(null)}}/>}
    {compositionNodeId && nodes.some(node=>node.id===compositionNodeId) && <CompositionEditor key={compositionNodeId} clips={compositionClips(compositionNodeId,nodes,edges)} writable={canEdit} busy={submittingNodeIds.has(compositionNodeId)} onClose={()=>setCompositionNodeId(null)} onFocus={focusNode} onOrder={ids=>{if(canEditRef.current)commitGraph(updateStudioNode(nodesRef.current,compositionNodeId,{compositionOrder:ids}) as Node<Data>[],edgesRef.current,'片段顺序已保存')}} onExport={()=>exportComposition(compositionNodeId)} result={mediaOf(nodes.find(node=>node.id===compositionNodeId)!)} onDownload={()=>nodeActions.download(compositionNodeId)}/>}

    {historyNodeId && <NodeMediaHistory data={nodes.find((node) => node.id === historyNodeId)?.data || {}} writable={canEdit} onClose={() => setHistoryNodeId(null)} onRestore={(item) => { const current = nodesRef.current.find((node) => node.id === historyNodeId); if (!current || !canEditRef.current) return; commitGraph(updateStudioNode(nodesRef.current, current.id, adoptMediaCandidate(current.data, item)) as Node<Data>[], edgesRef.current, '已恢复节点媒体'); setHistoryNodeId(null) }} />}
    {gridNodeId && canEdit && nodes.some((node) => node.id === gridNodeId) && <GridSplitEditor assetId={Number(nodes.find((node) => node.id === gridNodeId)?.data.assetId) || undefined} key={`${gridNodeId}:${nodes.find((node) => node.id === gridNodeId)?.data.mediaUrl || ''}`} projectId={projectId} url={String(nodes.find((node) => node.id === gridNodeId)?.data.mediaUrl || '')} title={String(nodes.find((node) => node.id === gridNodeId)?.data.label || '图片')} headers={editLockRequestHeaders(canvasTarget)} onClose={() => setGridNodeId(null)} onComplete={(outputs, columns) => putMediaResults(gridNodeId, outputs, columns)} />}
    {mediaEdit && nodes.some((node) => node.id === mediaEdit.id) && <MediaEditor assetId={Number(nodes.find((node) => node.id === mediaEdit.id)?.data.assetId) || undefined} projectId={projectId} url={String(nodes.find((node) => node.id === mediaEdit.id)?.data.mediaUrl || nodes.find((node) => node.id === mediaEdit.id)?.data.url || '')} kind={nodeMediaKind(nodes.find((node) => node.id === mediaEdit.id)) === 'audio' ? 'audio' : 'video'} initial={mediaEdit.operation} initialStart={mediaEdit.start} headers={editLockRequestHeaders(canvasTarget)} onClose={() => setMediaEdit(null)} onComplete={(outputs) => {
      putMediaResults(mediaEdit.id, outputs)
    }} />}
    {imageTool && imageToolNode && <ImageToolsEditor projectId={projectId} assetId={Number(imageToolNode.data.assetId) || undefined} key={`${imageTool.id}:${imageTool.mode}:${mediaOf(imageToolNode)}`} url={mediaOf(imageToolNode)} mode={imageTool.mode} writable={canEdit} onClose={() => setImageTool(null)} onPrompt={(prompt) => { const id = imageTool.id; setImageTool(null); openNodeComposer(id, 'edit', prompt) }} onExport={async (blob, label) => {
      if (!canEditRef.current) throw new Error('当前画布不可编辑')
      const asset = await printfilmStudioApi.uploadAsset(projectId, new File([blob], `${label}.png`, { type: 'image/png' }), editLockRequestHeaders(canvasTarget))
      putMediaResults(imageTool.id, [asset])
    }} />}
    {videoSetup && <VideoNodeSetup key={`${videoSetup.id}:${videoSetup.mode}`} mode={videoSetup.mode} items={nodes.filter((node) => node.id !== videoSetup.id && nodeMediaKind(node) === 'image' && mediaOf(node)).map((node) => ({ id: node.id, label: String(node.data.label || '图片'), url: mediaOf(node) }))} initialIds={edges.filter((edge) => edge.target === videoSetup.id).map((edge) => edge.source)} onClose={() => setVideoSetup(null)} onCreate={() => createVideoInput(videoSetup.id, 'image', videoSetup.mode)} onLibrary={() => {
      commitGraph(updateStudioNode(nodesRef.current, videoSetup.id, { videoMode: videoSetup.mode }) as Node<Data>[], edgesRef.current, '已选择视频生成方式')
      openSelectionComposer('video', undefined, videoSetup.id); setReferenceTargetId(videoSetup.id); setAssetsOpen(true); setVideoSetup(null)
    }} onApply={(ids) => {
      const targetId = videoSetup.id
      const retained = edgesRef.current.filter((edge) => edge.target !== targetId || nodeMediaKind(nodesRef.current.find((node) => node.id === edge.source)) === 'text')
      commitGraph(updateStudioNode(nodesRef.current, targetId, { videoMode: videoSetup.mode }) as Node<Data>[], [...retained, ...ids.map((source) => ({ id: `edge-${crypto.randomUUID()}`, source, target: targetId }))], '已连接视频参考图片')
      setVideoSetup(null); openSelectionComposer('video', undefined, targetId)
    }} />}
    {analysisNode && <FrameAnalysisEditor assetId={Number(analysisSource?.data.assetId || analysisNode.data.assetId) || undefined} key={`${analysisNode.id}:${analysisUrl}`} projectId={projectId} url={analysisUrl} report={analysisNode.data.analysisReport as FrameAnalysisReport | undefined} headers={editLockRequestHeaders(canvasTarget)} writable={canEdit} onClose={() => setAnalysisNodeId(null)} onComplete={(report, outputs) => {
      if (!mountedRef.current) return
      setAssets((current) => [...outputs, ...current])
      const current = nodesRef.current.find((node) => node.id === analysisNode.id)
      if (!current || !canEditRef.current) { setStatus('分析结果已保存到素材库'); return }
      const position = flow?.getInternalNode(current.id)?.internals.positionAbsolute || current.position
      const added = outputs.map((asset, index) => ({ ...newNode(assetMediaKind(asset), nodesRef.current.length + index), id: `node-${crypto.randomUUID()}`, position: { x: position.x + 380 + (index % 4) * 340, y: position.y + Math.floor(index / 4) * 300 }, data: { label: asset.name || '拉片结果', mediaUrl: asset.url || undefined, assetId: asset.id, mediaType: assetMediaKind(asset), status: 'completed' } }))
      let next = [...updateStudioNode(nodesRef.current, current.id, { analysisReport: report, mediaUrl: analysisUrl }) as Node<Data>[], ...added]
      const group = createStudioGroup(next, new Set(added.map((node) => node.id)), `${current.data.label || '逐帧拉片'} · ${report.shots.length} 个镜头`)
      if (group) next = groupStudioNodes(next, group) as Node<Data>[]
      commitGraph(next, edgesRef.current, `已检测 ${report.shots.length} 个镜头并保存结果`)
    }} />}
    {directorNodeId && <DirectorEditor initial={nodes.find((node) => node.id === directorNodeId)?.data.scene} writable={canEdit} onClose={() => setDirectorNodeId(null)} onSave={(scene) => commitGraph(updateStudioNode(nodesRef.current, directorNodeId, { scene }) as Node<Data>[], edgesRef.current, '三维场景已保存')} onExport={async (scene, blob, kind) => {
      const source = nodesRef.current.find((node) => node.id === directorNodeId)
      if (!source || !canEdit) throw new Error('当前场景不可编辑')
      const asset = kind === 'image'
        ? await printfilmStudioApi.uploadAsset(projectId, new File([blob], '导演台取景.png', { type: 'image/png' }), editLockRequestHeaders(canvasTarget))
        : (await printfilmStudioApi.editMedia(projectId, new File([blob], '导演台运镜.webm', { type: 'video/webm' }), { operation: 'speed', speed: 1 }, editLockRequestHeaders(canvasTarget))).assets[0]
      if (!asset?.url) throw new Error('导演台导出未返回媒体')
      if (!mountedRef.current) return
      const created = { ...newNode(kind, nodesRef.current.length), position: { x: source.position.x + 360, y: source.position.y }, data: { label: kind === 'video' ? '导演台运镜.mp4' : asset.name || '导演台导出', assetId: asset.id, mediaUrl: asset.url || undefined, mediaType: kind, status: 'completed' } }
      commitGraph([...updateStudioNode(nodesRef.current, source.id, { scene }) as Node<Data>[], created], [...edgesRef.current, { id: `edge-${crypto.randomUUID()}`, source: source.id, target: created.id }], '导演台媒体已保存到项目并连线')
    }} />}
    {maskNodeId && <MaskEditor initialMode={imageEditorMode} projectId={projectId} assetId={Number(nodes.find((node) => node.id === maskNodeId)?.data.assetId) || undefined} url={String((nodes.find((node) => node.id === maskNodeId)?.data.inpaint as InpaintData | undefined)?.originalUrl || nodes.find((node) => node.id === maskNodeId)?.data.mediaUrl || '')} onClose={() => setMaskNodeId(null)} onSave={async (mask, guide, editPrompt) => {
      const source = nodesRef.current.find((node) => node.id === maskNodeId)
      if (!source || !canEdit) throw new Error('当前节点不可编辑')
      const originalUrl = (source.data.inpaint as InpaintData | undefined)?.originalUrl || String(source.data.mediaUrl || source.data.url || '')
      const maskAsset = await printfilmStudioApi.uploadAsset(projectId, new File([mask], '重绘选区.png', { type: 'image/png' }), editLockRequestHeaders(canvasTarget))
      const guideAsset = await printfilmStudioApi.uploadAsset(projectId, new File([guide], '重绘引导.png', { type: 'image/png' }), editLockRequestHeaders(canvasTarget))
      if (!mountedRef.current) return
      const created = createImageResult(source, { label: `${source.data.label || '图片'} 编辑`, editor: 'inpaint', prompt: editPrompt, count: '1', ratio: source.data.ratio || 'auto', inpaint: { originalUrl, maskUrl: maskAsset.url, guideUrl: guideAsset.url } })
      setMaskNodeId(null); setOutputCount('1'); setHiddenRefIds([]); openSelectionComposer('inpaint', editPrompt, created.id)
      setPendingImageGeneration({ nodeId: created.id, prompt: editPrompt })
    }} onCrop={async (blob) => {
      const source = nodesRef.current.find((node) => node.id === maskNodeId)
      if (!source || !canEdit) throw new Error('当前节点不可编辑')
      const asset = await printfilmStudioApi.uploadAsset(projectId, new File([blob], '裁剪图片.png', { type: 'image/png' }), editLockRequestHeaders(canvasTarget))
      if (!mountedRef.current) return
      const current = nodesRef.current.find((node) => node.id === source.id)
      if (!current) return
      createImageResult(current, { label: `${current.data.label || '图片'} 裁剪`, mediaUrl: asset.url || '', assetId: asset.id, mediaType: 'image', status: 'completed' })
      setAssets((items) => [asset, ...items])
      setMaskNodeId(null)
    }} />}
    {recipeOpen && <RecipeLibrary projectId={projectId} draft={recipeDraft} writable={canEdit} onClose={() => setRecipeOpen(false)} onApply={(recipe) => {
      try { const bounds = window.document.querySelector('.pf-flow-area')?.getBoundingClientRect(); const at = flow && bounds ? flow.screenToFlowPosition({ x: bounds.left + bounds.width / 2, y: bounds.top + bounds.height / 2 }) : { x: 0, y: 0 }; const graph = instantiateRecipe(recipe.document, at); commitGraph([...nodesRef.current.map((node) => ({ ...node, selected: false })), ...graph.nodes as Node<Data>[]], [...edgesRef.current, ...graph.edges], `已应用配方：${recipe.name}`); setRecipeOpen(false) } catch (e) { setStatus(e instanceof Error ? e.message : '配方应用失败') }
    }} />}
    {contextMenu && <StudioContextMenu menu={contextMenu} actions={menuActions} onSelect={runMenuAction} onClose={() => setContextMenu(null)} />}
    {!!batchNodeIds.length && <BatchRunDialog nodes={nodes.filter(node => batchNodeIds.includes(node.id))} imageModels={catalogImageModels(mediaCatalog).filter((model) => model.available !== false)} videoModels={catalogVideoModels(mediaCatalog).filter((model) => model.available !== false)} balance={wallet?.balance_yuan} onQuote={quoteAgentBatch} onRun={runAgentBatch} onClose={() => setBatchNodeIds([])} />}
    {inspectorOpen && inspectorDraft && <StudioInspector references={selectedNode ? writingContext(selectedNode,nodes,edges).references : []} draft={inspectorDraft} kind={selectedNode?.type === 'group' ? 'group' : nodeMediaKind(selectedNode)} writable={canEdit} onChange={setInspectorDraft} onSave={saveInspector} onClose={() => setInspectorOpen(false)} />}
  </div></StudioComposerContext.Provider></StudioNodeActionsContext.Provider>
}



