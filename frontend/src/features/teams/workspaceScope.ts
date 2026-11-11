/** 保留登录身份切换时的请求取消机制；团队权限仅由项目成员关系决定。 */
let controller = new AbortController()
export const workspaceScope = { teamId: null as number | null, signal: controller.signal, epoch: 0 }
const listeners = new Set<() => void>()
/** 旧导航适配入口，团队参数不再切换全局空间；reset 用于登录身份切换。 */
export function setWorkspaceTeam(teamId: number | null, reset = false): void {
  teamId = null // Collaboration is scoped by project membership, never a global team.
  if (workspaceScope.teamId === teamId && !reset) return
  controller.abort(new DOMException('创作空间或登录身份已切换', 'AbortError')); controller = new AbortController()
  workspaceScope.teamId = teamId; workspaceScope.signal = controller.signal
  workspaceScope.epoch += 1
  listeners.forEach((listener) => listener())
}
/** 订阅真实资源归属带来的空间变化。 */
export function subscribeWorkspace(listener: () => void): () => void { listeners.add(listener); return () => { listeners.delete(listener) } }
/** 移除旧团队空间请求头，保留调用方取消信号与登录身份隔离。 */
export function scopedRequestInit(_path: string, init: RequestInit = {}): RequestInit {
  const headers = new Headers(init.headers)
  headers.delete('X-Workspace-Personal')
  headers.delete('X-Team-Id')
  const signal = init.signal && typeof AbortSignal.any === 'function' ? AbortSignal.any([init.signal, workspaceScope.signal]) : init.signal || workspaceScope.signal
  return { ...init, headers, signal }
}
