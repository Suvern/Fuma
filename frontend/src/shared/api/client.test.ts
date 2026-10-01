import { describe, expect, it, vi } from 'vitest'
import { createApiClient, getLiveness } from './client'

describe('generated API client', () => {
  it('uses the IDL path and same-origin credentials', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ status: 'ok', service: 'fuma-api' }))
    const client = createApiClient('http://localhost:8000', fetcher)
    await expect(getLiveness(undefined, client)).resolves.toEqual({ status: 'ok', service: 'fuma-api' })
    const request = fetcher.mock.calls[0]?.[0] as Request
    expect(request.url).toBe('http://localhost:8000/api/v1/health/live')
    expect(request.credentials).toBe('same-origin')
  })

  it('does not treat HTTP failure as a healthy service', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ error: { code: 'INTERNAL_ERROR' } }, { status: 500 }))
    await expect(getLiveness(undefined, createApiClient('http://localhost', fetcher))).rejects.toThrow('暂时无法连接服务')
  })

  it('rejects a successful response with the wrong shape', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(Response.json({ status: 'starting' }))
    await expect(getLiveness(undefined, createApiClient('http://localhost', fetcher))).rejects.toThrow('无法识别')
  })
})
