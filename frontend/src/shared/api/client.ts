import createClient from 'openapi-fetch'
import type { paths } from '../../generated/api'

export function createApiClient(baseUrl = '', fetcher: typeof fetch = globalThis.fetch) {
  return createClient<paths>({ baseUrl, fetch: fetcher, credentials: 'same-origin' })
}

export const api = createApiClient()

export async function getLiveness(signal?: AbortSignal, client = api) {
  // Keep TanStack Query cancellation as well as a bounded network timeout.
  const timeout = AbortSignal.timeout(8_000)
  const { data, error, response } = await client.GET('/api/v1/health/live', {
    signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
  })
  if (!response.ok || error || !data) {
    throw new Error('暂时无法连接服务，请稍后重试。')
  }
  if (data.status !== 'ok' || data.service !== 'fuma-api') {
    throw new Error('服务返回了无法识别的状态。')
  }
  return data
}
