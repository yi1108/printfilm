export type CloseAccountPayload = {
  password: string
  confirmation: string
}

type AccountRequester = <T>(path: string, init?: RequestInit) => Promise<T>

/** 创建账号安全请求，集中维护注销接口的载荷契约。 */
export function createAccountRequests(request: AccountRequester) {
  return {
    /** 校验密码及确认词后永久注销当前账号。 */
    closeAccount(body: CloseAccountPayload): Promise<{ ok: boolean }> {
      return request<{ ok: boolean }>('/api/auth/close-account', {
        method: 'POST',
        body: JSON.stringify(body),
      })
    },
  }
}
