/** HTTP 基础能力：地址、登录态和响应解析；不依赖浏览器全局配置或业务模块。 */
import { getMediaPriceVersion, setMediaPriceVersion } from '../lib/mediaPriceVersion.ts'

/** 空间/路由切换的主动取消不属于业务失败，不能显示为红色报错。 */
export function isRequestAborted(cause: unknown): boolean {
  return cause !== null && typeof cause === 'object' && 'name' in cause && cause.name === 'AbortError'
}

/** 将 FastAPI 的字符串或校验错误数组转换为可展示文案。 */
export function apiErrorMessage(detail: unknown, fallback: string): string {
  if (typeof detail === 'string') return detail || fallback
  if (detail && typeof detail === 'object' && 'message' in detail) return String(detail.message || fallback)
  if (Array.isArray(detail)) {
    const message = detail.map((item) => {
      if (item && typeof item === 'object' && 'msg' in item) {
        return String(item.msg || JSON.stringify(item))
      }
      return JSON.stringify(item)
    }).join('; ')
    return message || fallback
  }
  return fallback
}

/** 未配置时使用当前主机的开发 API；显式空字符串保留同源代理语义。 */
export function resolveApiBase(
  configuredBase: unknown,
  location?: { protocol: string; hostname: string },
): string {
  if (configuredBase !== undefined && configuredBase !== null) return String(configuredBase)
  return location?.hostname
    ? `${location.protocol}//${location.hostname}:8000`
    : 'http://127.0.0.1:8000'
}

/** 不同业务沿用原有错误文案和计费提示，由调用方决定错误展示策略。 */
export type ApiErrorHandler = (response: Response, detail: unknown) => never

/** 创建可注入登录态的 HTTP 客户端，JSON 与文件上传共用同一请求路径。 */
export function createHttpTransport(options: {
  baseUrl: string
  getToken: () => string | null
  onError: ApiErrorHandler
}) {
  /** 保留 Headers 的全部合法输入形式，FormData 的 boundary 交给浏览器生成。 */
  async function response(
    path: string,
    init?: RequestInit,
    onError: ApiErrorHandler = options.onError,
  ): Promise<Response> {
    /* 每次请求重新读取 token，登录、登出后无需重建客户端。 */
    const headers = new Headers()
    const priceVersion = getMediaPriceVersion()
    if (priceVersion !== null && init?.method && init.method.toUpperCase() !== 'GET') {
      headers.set('X-Media-Price-Version', String(priceVersion))
    }
    const token = options.getToken()
    if (token) headers.set('Authorization', `Bearer ${token}`)
    if (!(init?.body instanceof FormData)) headers.set('Content-Type', 'application/json')
    new Headers(init?.headers).forEach((value, key) => headers.set(key, value))
    let result: Response
    try {
      result = await fetch(`${options.baseUrl}${path}`, { ...init, headers })
    } catch (cause) {
      // 浏览器有时把中断显示为 TypeError/Failed to fetch；仍按原始取消原因处理。
      if (init?.signal?.aborted) throw init.signal.reason || new DOMException('请求已取消', 'AbortError')
      throw cause
    }
    if (!result.ok) {
      const error = await result.json().catch(() => ({ detail: result.statusText }))
      // 画布版本、编辑占用等冲突不应触发价格目录刷新和重新报价。
      if (result.status === 409 && /^价格(?:已更新|版本已变化)/.test(apiErrorMessage(error?.detail, '')) && typeof window !== 'undefined') {
        window.dispatchEvent(new Event('media-prices-changed'))
      }
      onError(result, error?.detail)
    }
    return result
  }

  /** 解析成功的 JSON 响应；下载等非 JSON 请求直接使用 response。 */
  async function json<T>(
    path: string,
    init?: RequestInit,
    onError?: ApiErrorHandler,
  ): Promise<T> {
    const data = await (await response(path, init, onError)).json()
    if (path === '/api/media-models') setMediaPriceVersion(data.price_version ?? 0)
    return data as T
  }

  return { response, json }
}
