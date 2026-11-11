import { createContext, type ReactNode, type MouseEvent as ReactMouseEvent } from 'react'
import type { StudioVideoMode } from './generationReferences'
import type { ComposerAction } from './PromptComposer'
import type { MediaOperation } from '../types'
import type { GenerationControls } from './generationControls'
import type { ImageToolMode } from './imageToolParameters'
import type { WritingReference } from './writingContext'

export type ComposerMention = {
  id: string
  label: string
  url?: string
  hint?: string
  mediaKind?: string
  source: 'node' | 'asset'
}

export type StudioComposerState = {
  nodeId: string
  action: ComposerAction
  prompt: string
  onPrompt: (value: string) => void
  chips: { id: string; label: string }[]
  onRemoveChip: (id: string) => void
  onAddChip: (chip: { id: string; label: string }, append: string) => void
  refs: { id: string; url: string; label: string; mediaKind?: string; status?: string }[]
  onRemoveRef: (id: string) => void
  onFocusRef?: (id: string) => void
  onAddRef: () => void
  /** 已接入、画布上、素材库，供 @ 引用。 */
  mentions: { connected: ComposerMention[]; canvas: ComposerMention[]; assets: ComposerMention[] }
  /** 选中引用后接线，素材则先放入画布再接线。 */
  onMention: (item: ComposerMention) => void
  modelId: string
  modelOptions: { id: string; label: string }[]
  onModelChange: (id: string) => void
  ratio: string
  onRatioChange: (value: string) => void
  count: string
  onCountChange: (value: string) => void
  resolution: string
  onResolutionChange: (value: string) => void
  duration: string
  onDurationChange: (value: string) => void
  estimate: string
  videoMode?: StudioVideoMode
  onVideoModeChange?: (value: StudioVideoMode) => void
  videoModeOptions?: { id: string; label: string; disabled?: boolean; hint?: string }[]
  validationMessage?: string
  generateAudio?: boolean
  onAudioChange?: (value: boolean) => void
  isVideo: boolean
  controls?: GenerationControls
  voice?: string
  onVoiceChange?: (value: string) => void
  onClose: () => void
  onSubmit: () => void
  canSubmit: boolean
}

export type StudioNodeActions = {
  focusNode?: (id:string)=>void
  disconnectEdge?: (id:string)=>void
  composition?: (id:string)=>void
  compositionSummary?: (id:string)=>{count:number;pending:string}
  writingReferences?: (id: string) => WritingReference[]
  projectId?: number
  textComposer?: { nodeId: string; content: ReactNode }
  closeTextComposer?: () => void
  analyze: (id: string) => void
  generateText: (id: string) => void
  editGeneration?: (id: string) => void
  moreMenu?: (event: ReactMouseEvent, id: string) => void
  videoStart?: (id: string, mode: 'image_to_video' | 'first_last_frame' | 'script') => void
  imageTools: (id: string, mode: ImageToolMode) => void
  cancelGeneration: (id: string) => void
  mediaEdit: (id: string, operation: MediaOperation, start?: number) => void
  gridSplit: (id: string) => void
  history: (id: string) => void
  ask: (id: string) => void
  director: (id: string) => void
  submittingNodeIds?: ReadonlySet<string>
  writable?: boolean
  selectionCount?: number
  panelsSuppressed?: boolean
  checkpoint: () => void
  rename: (id: string, title: string) => void
  resize: (id: string, width: number, height: number) => void
  imageLoaded?: (id: string, url: string, width: number, height: number) => void
  inspect: (id: string) => void
  duplicate: (id: string) => void
  remove: (id: string) => void
  preview: (id: string) => void
  download: (id: string) => void
  upload: (id: string) => void
  dropFiles: (id: string, files: FileList | null) => void
  updateText: (id: string, text: string) => void
  openComposer: (id: string, action: ComposerAction, seed?: string) => void
  contextMenu: (event: ReactMouseEvent, id: string) => void
  /** 多图切换当前预览。 */
  setMediaIndex: (id: string, index: number) => void
  /** 打开多图对比。 */
  compareVariants: (id: string) => void
  /** 把多图拆成独立图片节点。 */
  splitVariants: (id: string) => void
}

export const StudioNodeActionsContext = createContext<StudioNodeActions | null>(null)
export const StudioComposerContext = createContext<StudioComposerState | null>(null)
