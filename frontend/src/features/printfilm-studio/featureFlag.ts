import { createJsonRequester } from '../../api/client'

type Capabilities = { printfilm_studio_enabled?: boolean }
const request = createJsonRequester()

/** Public capability check used by navigation and deep-link guards. */
export async function isPrintfilmStudioEnabled(): Promise<boolean> {
  const capabilities = await request<Capabilities>('/api/capabilities')
  return capabilities.printfilm_studio_enabled === true
}
