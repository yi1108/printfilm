/** 画布 store Context：独立文件，避免 CanvasStore 热更新后 Provider / hook 各持一份 Context */
import { createContext, useContext } from 'react'

export const CanvasStoreContext = createContext<unknown>(null)

/** 读取画布状态；必须包在 CanvasStoreProvider 内 */
export function useCanvasStore<T>(): T {
  const ctx = useContext(CanvasStoreContext)
  if (!ctx) {
    throw new Error('useCanvasStore must be used within CanvasStoreProvider')
  }
  return ctx as T
}
