import type { CanvasDocument } from './canvas/canvasCodec'
import type { AgentReference } from './agent/references'

export type CanvasResponse = { document: CanvasDocument; version: number; updated_at: string | null }
export type AgentMessage = { id: string; role: string; content: unknown; sequence: number; metadata?: { events?: Record<string, unknown>[]; references?: AgentReference[] } }
export type AgentSession = { id: string; project_id: number; title: string; model_id?: string | null; status: string; messages?: AgentMessage[]; run?: { id: string; status: string; last_sequence: number } | null }
export type AgentOptions = { enabled_tools?: string[]; node_ids?: string[]; asset_ids?: number[]; story_step?: 'assets' | 'shots'; review_changes?: boolean; agent_mode?: 'director' | 'assistant'; skill_task?: 'script_write' | 'asset_plan' | 'shot_plan' | 'video_prompt' | 'edit_plan'; skill_ids?: number[]; director_skill_selection?: Partial<Record<'script_write' | 'asset_plan' | 'shot_plan' | 'video_prompt' | 'edit_plan', number | null>> }
export type MediaOperation = 'trim' | 'extract_audio' | 'separate' | 'mute' | 'speed' | 'frame' | 'frames'
export type FrameAnalysisReport = {
  version: number; duration: number; detector: 'adaptive' | 'content'; threshold: number; minimum: number; has_audio: boolean
  audio?: ProjectAsset | null
  shots: { index: number; start: number; end: number; duration: number; frame?: ProjectAsset; clip?: ProjectAsset }[]
}
export type ProjectAsset = { id: number; name?: string | null; type?: string | null; asset_type?: string | null; url?: string | null; cover?: string | null; params?: Record<string, unknown> | null }
