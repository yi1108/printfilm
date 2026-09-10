import type { User } from '../api'

export const USER_UPDATED_EVENT = 'pf-user-updated'

/** 广播用户资料变更，供顶栏等组件同步头像 */
export function dispatchUserUpdated(user: User) {
  window.dispatchEvent(new CustomEvent(USER_UPDATED_EVENT, { detail: user }))
}
