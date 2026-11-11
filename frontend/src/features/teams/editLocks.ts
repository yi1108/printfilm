/** Legacy editor adapter. Project authorization is enforced by the server; canvas uses versioned saves. */
export type EditResource = 'structure' | 'script' | 'episode' | 'asset' | 'canvas'
export type EditTarget = { projectId: number; type: EditResource; resourceId: number }
export function recordDramaResponse(_path: string, _data: unknown, _epoch?: number): void {}
export async function projectTeam(_projectId: number): Promise<null> { return null }
export async function syncProjectWorkspace(_projectId: number): Promise<void> {}
export function editLockRequestHeaders(_target: EditTarget): Record<string, string> { return {} }
export function editLockError(_target: EditTarget): string { return '' }
export function subscribeEditLocks(_listener: () => void): () => void { return () => {} }
export async function holdEditLock(_target: EditTarget, _force = false): Promise<null> { return null }
export async function releaseEditLock(_target: EditTarget, _all = false, _token?: string): Promise<void> {}
export async function releaseLostEditLock(_target: EditTarget): Promise<void> {}
export async function withDramaEditLock<T>(_path: string, init: RequestInit | undefined, action: (init?: RequestInit) => Promise<T>): Promise<T> { return action(init) }
