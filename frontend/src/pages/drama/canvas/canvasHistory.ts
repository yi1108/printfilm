/** 画布撤销/重做历史栈纯函数 */
import type { Edge, Node } from '@xyflow/react'
import { MAX_CANVAS_HISTORY, type CanvasAssetNodeData } from './canvasTypes'

export type CanvasSnapshot = {
  nodes: Node<CanvasAssetNodeData>[]
  edges: Edge[]
}

export type CanvasHistoryState = {
  past: CanvasSnapshot[]
  future: CanvasSnapshot[]
}

/** 创建空历史栈 */
export function createEmptyCanvasHistory(): CanvasHistoryState {
  return { past: [], future: [] }
}

/** 深拷贝画布快照 */
export function cloneCanvasSnapshot(snapshot: CanvasSnapshot): CanvasSnapshot {
  return JSON.parse(JSON.stringify(snapshot)) as CanvasSnapshot
}

/** 将快照压入 past 并清空 future */
export function pushHistory(
  history: CanvasHistoryState,
  snapshot: CanvasSnapshot,
): CanvasHistoryState {
  const nextPast = [...history.past, cloneCanvasSnapshot(snapshot)]
  const trimmedPast =
    nextPast.length > MAX_CANVAS_HISTORY
      ? nextPast.slice(nextPast.length - MAX_CANVAS_HISTORY)
      : nextPast

  return {
    past: trimmedPast,
    future: [],
  }
}

/** 从 past 弹出上一快照并恢复 */
export function undoHistory(
  current: CanvasSnapshot,
  history: CanvasHistoryState,
): { snapshot: CanvasSnapshot; history: CanvasHistoryState } | null {
  if (history.past.length === 0) return null

  const previous = history.past[history.past.length - 1]
  return {
    snapshot: previous,
    history: {
      past: history.past.slice(0, -1),
      future: [cloneCanvasSnapshot(current), ...history.future],
    },
  }
}

/** 从 future 弹出下一快照并恢复 */
export function redoHistory(
  current: CanvasSnapshot,
  history: CanvasHistoryState,
): { snapshot: CanvasSnapshot; history: CanvasHistoryState } | null {
  if (history.future.length === 0) return null

  const next = history.future[0]
  return {
    snapshot: next,
    history: {
      past: [...history.past, cloneCanvasSnapshot(current)],
      future: history.future.slice(1),
    },
  }
}
