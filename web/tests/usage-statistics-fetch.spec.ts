import { afterEach, expect, it, vi } from 'vitest'
import { fetchUsageStatistics } from '@/lib/usage-statistics'

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })

afterEach(() => vi.unstubAllGlobals())

it('returns the parsed statistics payload on success', async () => {
  const fetchMock = vi.fn(async () => jsonResponse({ year: 2026, totals: { total_tokens: 1 } }))
  vi.stubGlobal('fetch', fetchMock)
  await expect(fetchUsageStatistics(2026)).resolves.toEqual({
    year: 2026,
    totals: { total_tokens: 1 },
  })
})

it('throws the backend detail so a failed load is diagnosable', async () => {
  const fetchMock = vi.fn(async () =>
    jsonResponse(
      { detail: 'A data migration needs recovery. Open Settings → Data migration.' },
      503
    )
  )
  vi.stubGlobal('fetch', fetchMock)
  await expect(fetchUsageStatistics(2026)).rejects.toThrow(
    'A data migration needs recovery. Open Settings → Data migration.'
  )
})

it('rejects malformed success bodies instead of presenting garbage', async () => {
  const fetchMock = vi.fn(async () => new Response('not json', { status: 200 }))
  vi.stubGlobal('fetch', fetchMock)
  await expect(fetchUsageStatistics(2026)).rejects.toThrow()
})
