import { isRequestAborted } from '../../api/http.ts'

export const STUDIO_SESSION_EXPIRED = 'pf-studio-session-expired'
export type WorkspaceIssue = { title: string; message: string; action: 'login' | 'retry' | 'back' }

export function workspaceIssue(cause: unknown): WorkspaceIssue {
  const status = cause && typeof cause === 'object' && 'status' in cause ? cause.status : undefined
  if (status === 401) return { title: '登录已失效', message: '重新登录后即可继续打开当前项目和添加节点。', action: 'login' }
  if (status === 403 || status === 404) return { title: '无法访问此项目', message: '请确认当前账号具有项目访问权限，或返回项目列表选择其他项目。', action: 'back' }
  return { title: '画布加载失败', message: cause instanceof Error ? cause.message : '暂时无法读取画布，请重试。', action: 'retry' }
}

export function canEditStudioCanvas(validProjectId: boolean, canvasReady: boolean, lockReadOnly: boolean, sessionExpired: boolean): boolean {
  return validProjectId && canvasReady && !lockReadOnly && !sessionExpired
}

export function studioLoginPath(path: string): string {
  return `/auth?next=${encodeURIComponent(path)}`
}

/** An old request must not expire a newer login, including across tabs. */
export function reportStudioUnauthorized(cause: unknown, token: string | null, getToken: () => string | null, notify: () => void): void {
  if (token && token === getToken() && cause && typeof cause === 'object' && 'status' in cause && cause.status === 401) notify()
}

/** Resolve the project's real workspace before reading its canvas. Never apply a late response. */
export async function loadStudioCanvas<T>(options: {
  syncWorkspace: () => Promise<unknown>
  loadCanvas: () => Promise<T>
  isCurrent: () => boolean
  onReady: (result: T) => void
  onError: (issue: WorkspaceIssue) => void
}): Promise<void> {
  try {
    await options.syncWorkspace()
    if (!options.isCurrent()) return
    const result = await options.loadCanvas()
    if (options.isCurrent()) options.onReady(result)
  } catch (cause) {
    if (options.isCurrent() && !isRequestAborted(cause)) options.onError(workspaceIssue(cause))
  }
}
