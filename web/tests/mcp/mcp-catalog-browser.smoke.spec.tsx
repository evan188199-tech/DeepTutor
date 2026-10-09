import React from 'react'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import McpCatalogBrowser from '@/components/mcp/McpCatalogBrowser'
import { SPACE_MCP_SURFACE } from '@/components/mcp/surface'
import {
  getMcpCatalog,
  installMcpCatalogEntry,
  testSpaceMcpServer,
  type McpCatalogEntry,
  type McpCatalogPage,
  type McpServerConfig,
  type McpStoreState,
  type McpTestResult,
} from '@/lib/mcp-api'

vi.mock('@/lib/mcp-api', async importOriginal => {
  const actual = await importOriginal<typeof import('@/lib/mcp-api')>()
  return {
    ...actual,
    getMcpCatalog: vi.fn(),
    installMcpCatalogEntry: vi.fn(),
    testSpaceMcpServer: vi.fn(),
  }
})

// `t` must be reference-stable across renders: the fetch effect lists it as a
// dependency, and a fresh function per render would refetch in a loop.
const interpolate = (key: string, opts?: Record<string, unknown>): string =>
  opts
    ? key.replace(/\{\{(\w+)\}\}/g, (_match, name: string) =>
        Object.prototype.hasOwnProperty.call(opts, name) ? String(opts[name]) : `{{${name}}}`
      )
    : key
const translate = vi.fn(interpolate)

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: translate, i18n: { language: 'en' } }),
}))

// restoreMocks wipes implementations after each test; re-prime the translator.
beforeEach(() => {
  translate.mockImplementation(interpolate)
})

function entryFixture(overrides: Partial<McpCatalogEntry> = {}): McpCatalogEntry {
  return {
    id: 'exa',
    display_name: 'Exa',
    description_i18n: { en: 'Neural web search' },
    category: 'search',
    tier: 'curated',
    transport: 'streamableHttp',
    homepage: 'https://example.com/exa',
    docs_url: '',
    requires_i18n: {},
    logo_url: '',
    trust: 'verified',
    self_service: true,
    installed: false,
    installed_as: [],
    fields: [],
    ...overrides,
  }
}

function pageFixture(
  entries: McpCatalogEntry[],
  overrides: Partial<McpCatalogPage> = {}
): McpCatalogPage {
  return {
    entries,
    next_cursor: '',
    total: entries.length,
    categories: {},
    ...overrides,
  }
}

function serverCfg(catalogEntry: string): McpServerConfig {
  return {
    type: 'streamableHttp',
    command: '',
    args: [],
    env: {},
    cwd: '',
    url: `https://mcp.example.com/${catalogEntry}`,
    headers: {},
    tool_timeout: 30,
    enabled_tools: [],
    disabled_tools: [],
    enabled: true,
    auth: '',
    catalog_entry: catalogEntry,
  }
}

function renderBrowser(props: Partial<Parameters<typeof McpCatalogBrowser>[0]> = {}) {
  const onInstalled = vi.fn()
  render(
    <McpCatalogBrowser
      surface={SPACE_MCP_SURFACE}
      installedServers={{}}
      atCapacity={false}
      onInstalled={onInstalled}
      {...props}
    />
  )
  return { onInstalled }
}

const SECRET_FIELD = {
  key: 'api_key',
  label_i18n: { en: 'API key' },
  secret: true,
  required: true,
  placeholder: 'sk-...',
}

// ── catalog loading ──────────────────────────────────────────────────────

it('fetches the first page for the space surface and renders its entries', async () => {
  vi.mocked(getMcpCatalog).mockResolvedValue(
    pageFixture([entryFixture(), entryFixture({ id: 'brave', display_name: 'Brave Search' })], {
      total: 2,
      categories: { search: 2 },
    })
  )
  renderBrowser()

  expect(getMcpCatalog).toHaveBeenCalledWith('/api/space/mcp', {
    q: '',
    category: '',
    tier: '',
    limit: 12,
  })
  expect(await screen.findByRole('button', { name: 'View details: Exa' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'View details: Brave Search' })).toBeInTheDocument()
  expect(screen.getByText('2 of 2 services')).toBeInTheDocument()
  // The category chip carries the match count; card rows repeat the category
  // as a plain chip, so scope the assertion to the filter button.
  expect(screen.getByRole('button', { name: /mcp\.category\.search\s*2/ })).toBeInTheDocument()
  // No cursor: the store shows everything, so "Load more" must not exist.
  expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()
})

it('shows a loading indicator while the first page is in flight', async () => {
  let resolvePage!: (page: McpCatalogPage) => void
  vi.mocked(getMcpCatalog).mockReturnValue(
    new Promise<McpCatalogPage>(resolve => {
      resolvePage = resolve
    })
  )
  renderBrowser()

  expect(document.querySelector('.animate-spin')).not.toBeNull()
  expect(screen.queryByRole('button', { name: 'View details: Exa' })).not.toBeInTheDocument()

  resolvePage(pageFixture([entryFixture()]))
  expect(await screen.findByRole('button', { name: 'View details: Exa' })).toBeInTheDocument()
})

it('renders the failure banner when the catalog request fails', async () => {
  vi.mocked(getMcpCatalog).mockRejectedValue(new Error('catalog request failed'))
  renderBrowser()

  expect(await screen.findByText('catalog request failed')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'View details: Exa' })).not.toBeInTheDocument()
})

it('renders the empty-store copy when the deployment has no services', async () => {
  vi.mocked(getMcpCatalog).mockResolvedValue(pageFixture([]))
  renderBrowser()

  expect(await screen.findByText('The store is empty')).toBeInTheDocument()
})

it('renders the no-match copy when a search matches nothing', async () => {
  vi.mocked(getMcpCatalog).mockResolvedValue(pageFixture([]))
  renderBrowser()
  await screen.findByText('The store is empty')

  fireEvent.change(screen.getByPlaceholderText('Search MCP services…'), {
    target: { value: 'zzz' },
  })

  await waitFor(() =>
    expect(getMcpCatalog).toHaveBeenLastCalledWith(
      '/api/space/mcp',
      expect.objectContaining({ q: 'zzz' })
    )
  )
  expect(await screen.findByText('No services match this filter.')).toBeInTheDocument()
  expect(screen.queryByText('The store is empty')).not.toBeInTheDocument()
})

// ── search and filter inputs ─────────────────────────────────────────────

it('debounces the search box and refetches with the trimmed query', async () => {
  vi.mocked(getMcpCatalog).mockResolvedValue(pageFixture([entryFixture()]))
  renderBrowser()
  await screen.findByRole('button', { name: 'View details: Exa' })

  fireEvent.change(screen.getByPlaceholderText('Search MCP services…'), {
    target: { value: '  exa ' },
  })
  // Not yet: the query is debounced, not fired per keystroke.
  expect(getMcpCatalog).toHaveBeenCalledTimes(1)

  await waitFor(() =>
    expect(getMcpCatalog).toHaveBeenLastCalledWith('/api/space/mcp', {
      q: 'exa',
      category: '',
      tier: '',
      limit: 12,
    })
  )
})

it('refetches when a category chip or tier chip is picked and toggles the tier off', async () => {
  vi.mocked(getMcpCatalog).mockResolvedValue(
    pageFixture([entryFixture()], { categories: { search: 1 } })
  )
  renderBrowser()
  await screen.findByRole('button', { name: 'View details: Exa' })

  fireEvent.click(screen.getByRole('button', { name: /mcp\.category\.search/ }))
  await waitFor(() =>
    expect(getMcpCatalog).toHaveBeenLastCalledWith(
      '/api/space/mcp',
      expect.objectContaining({ category: 'search' })
    )
  )

  fireEvent.click(screen.getByRole('button', { name: 'mcp.tier.curated' }))
  await waitFor(() =>
    expect(getMcpCatalog).toHaveBeenLastCalledWith(
      '/api/space/mcp',
      expect.objectContaining({ tier: 'curated' })
    )
  )

  fireEvent.click(screen.getByRole('button', { name: 'mcp.tier.curated' }))
  await waitFor(() =>
    expect(getMcpCatalog).toHaveBeenLastCalledWith(
      '/api/space/mcp',
      expect.objectContaining({ tier: '' })
    )
  )
})

// ── pagination ───────────────────────────────────────────────────────────

it('appends the next page via Load more, dedupes rows and drops the button when exhausted', async () => {
  const firstPage = pageFixture(
    [entryFixture(), entryFixture({ id: 'brave', display_name: 'Brave Search' })],
    { next_cursor: 'cursor-1', total: 3, categories: { search: 3 } }
  )
  // Second page re-serves `exa` (a re-fetched cursor) plus one new row.
  const secondPage = pageFixture(
    [entryFixture({ id: 'exa' }), entryFixture({ id: 'context7', display_name: 'Context7' })],
    { total: 3 }
  )
  vi.mocked(getMcpCatalog).mockResolvedValueOnce(firstPage).mockResolvedValue(secondPage)
  renderBrowser()
  expect(await screen.findByRole('button', { name: 'Load more' })).toBeInTheDocument()
  expect(screen.getByText('2 of 3 services')).toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: 'Load more' }))

  await waitFor(() =>
    expect(getMcpCatalog).toHaveBeenLastCalledWith('/api/space/mcp', {
      q: '',
      category: '',
      tier: '',
      cursor: 'cursor-1',
      limit: 12,
    })
  )
  expect(await screen.findByText('3 of 3 services')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'View details: Context7' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()
})

// ── installed badges ─────────────────────────────────────────────────────

it('marks entries installed by provenance and by a pre-provenance entry-id name', async () => {
  vi.mocked(getMcpCatalog).mockResolvedValue(
    pageFixture([
      entryFixture({ id: 'exa' }),
      entryFixture({ id: 'legacy', display_name: 'Legacy' }),
      entryFixture({ id: 'other', display_name: 'Other' }),
    ])
  )
  renderBrowser({
    installedServers: {
      exa: serverCfg('exa'),
      // Installed before provenance was recorded: keyed on the entry id.
      legacy: { ...serverCfg('legacy'), catalog_entry: '' },
    },
  })

  const exaCard = await screen.findByRole('button', {
    name: 'View details: Exa',
  })
  expect(within(exaCard).getByText('Installed')).toBeInTheDocument()
  const legacyCard = screen.getByRole('button', {
    name: 'View details: Legacy',
  })
  expect(within(legacyCard).getByText('Installed')).toBeInTheDocument()
  const otherCard = screen.getByRole('button', {
    name: 'View details: Other',
  })
  expect(within(otherCard).queryByText('Installed')).not.toBeInTheDocument()
})

it("falls back to the page's own installed_as while the server list is still loading", async () => {
  vi.mocked(getMcpCatalog).mockResolvedValue(
    pageFixture([entryFixture({ installed_as: ['my-exa'] })])
  )
  renderBrowser({ installedServers: null })

  const card = await screen.findByRole('button', {
    name: 'View details: Exa',
  })
  expect(within(card).getByText('Installed')).toBeInTheDocument()
})

// ── detail pane ──────────────────────────────────────────────────────────

it("opens an entry's detail pane and returns to the grid", async () => {
  vi.mocked(getMcpCatalog).mockResolvedValue(
    pageFixture([entryFixture({ docs_url: 'https://docs.example.com/exa' })])
  )
  renderBrowser()

  fireEvent.click(await screen.findByRole('button', { name: 'View details: Exa' }))
  expect(screen.getByRole('heading', { name: 'Exa' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Documentation' })).toHaveAttribute(
    'href',
    'https://docs.example.com/exa'
  )
  expect(screen.getByRole('button', { name: 'Install' })).toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: 'Back to the store' }))
  expect(await screen.findByRole('button', { name: 'View details: Exa' })).toBeInTheDocument()
})

it('keeps Install disabled until the required credential is filled', async () => {
  vi.mocked(getMcpCatalog).mockResolvedValue(
    pageFixture([entryFixture({ fields: [SECRET_FIELD] })])
  )
  renderBrowser()

  fireEvent.click(await screen.findByRole('button', { name: 'View details: Exa' }))
  const install = screen.getByRole('button', { name: 'Install' })
  expect(install).toBeDisabled()
  expect(screen.getByText('Fill in api_key to continue')).toBeInTheDocument()
  // Secret fields render as password inputs so the browser never autofills
  // them; the visible label is not associated with the input.
  expect(screen.getByPlaceholderText('sk-...')).toHaveAttribute('type', 'password')

  fireEvent.change(screen.getByPlaceholderText('sk-...'), {
    target: { value: 'sk-test' },
  })
  expect(install).toBeEnabled()
})

// ── install branches ─────────────────────────────────────────────────────

it('installs with the chosen name, drops blank optional secrets and probes the new server', async () => {
  const state: McpStoreState = {
    servers: { exa: serverCfg('exa') },
    status: [],
    user: null,
  }
  vi.mocked(getMcpCatalog).mockResolvedValue(
    pageFixture([
      entryFixture({
        fields: [
          SECRET_FIELD,
          {
            key: 'note',
            label_i18n: { en: 'Note' },
            secret: false,
            required: false,
            placeholder: '',
          },
        ],
      }),
    ])
  )
  vi.mocked(installMcpCatalogEntry).mockResolvedValue(state)
  vi.mocked(testSpaceMcpServer).mockResolvedValue({
    ok: true,
    tools: [
      { name: 'web_search', description: 'Search the web' },
      { name: 'crawl', description: 'Crawl a page' },
    ],
    error: '',
  } satisfies McpTestResult)
  const { onInstalled } = renderBrowser()

  fireEvent.click(await screen.findByRole('button', { name: 'View details: Exa' }))
  fireEvent.change(screen.getByPlaceholderText('sk-...'), {
    target: { value: 'sk-test' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Install' }))

  await waitFor(() =>
    expect(installMcpCatalogEntry).toHaveBeenCalledWith('/api/space/mcp', 'exa', {
      name: 'exa',
      secrets: { api_key: 'sk-test' },
    })
  )
  expect(onInstalled).toHaveBeenCalledWith(state)
  // Installing a brand-new entry tests the connection automatically — the
  // earliest a credential can be verified.
  await waitFor(() =>
    expect(testSpaceMcpServer).toHaveBeenCalledWith('/api/space/mcp', 'exa', state.servers.exa)
  )
  expect(await screen.findByText('Connected — 2 tools detected')).toBeInTheDocument()
})

it('shows the install failure, keeps the parent untouched and skips the probe', async () => {
  vi.mocked(getMcpCatalog).mockResolvedValue(pageFixture([entryFixture()]))
  vi.mocked(installMcpCatalogEntry).mockRejectedValue(new Error('install refused by policy'))
  const { onInstalled } = renderBrowser()

  fireEvent.click(await screen.findByRole('button', { name: 'View details: Exa' }))
  fireEvent.click(screen.getByRole('button', { name: 'Install' }))

  expect(await screen.findByText('install refused by policy')).toBeInTheDocument()
  expect(onInstalled).not.toHaveBeenCalled()
  expect(testSpaceMcpServer).not.toHaveBeenCalled()
})

it('blocks a new install at the server cap', async () => {
  vi.mocked(getMcpCatalog).mockResolvedValue(pageFixture([entryFixture()]))
  renderBrowser({ atCapacity: true })

  fireEvent.click(await screen.findByRole('button', { name: 'View details: Exa' }))
  expect(
    screen.getByText('You have reached your MCP server limit. Remove one first.')
  ).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Install' })).toBeDisabled()
})

it('still offers Test connection and Reinstall for an installed entry at the cap', async () => {
  const saved = serverCfg('exa')
  vi.mocked(getMcpCatalog).mockResolvedValue(pageFixture([entryFixture()]))
  vi.mocked(installMcpCatalogEntry).mockResolvedValue({
    servers: { exa: saved },
    status: [],
    user: null,
  })
  vi.mocked(testSpaceMcpServer).mockRejectedValue(new Error('connection timed out'))
  renderBrowser({ atCapacity: true, installedServers: { exa: saved } })

  fireEvent.click(await screen.findByRole('button', { name: 'View details: Exa' }))
  // The name box is prefilled with the installed name, so Reinstall replaces
  // that server instead of tripping the cap with a second copy.
  expect(screen.getByPlaceholderText('exa')).toHaveValue('exa')
  const reinstall = screen.getByRole('button', { name: 'Reinstall' })
  expect(reinstall).toBeEnabled()
  expect(screen.getByRole('button', { name: 'Test connection' })).toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: 'Test connection' }))
  expect(await screen.findByText('Connection failed.')).toBeInTheDocument()
  expect(testSpaceMcpServer).toHaveBeenCalledWith('/api/space/mcp', 'exa', saved)

  fireEvent.click(reinstall)
  await waitFor(() =>
    expect(installMcpCatalogEntry).toHaveBeenCalledWith('/api/space/mcp', 'exa', {
      name: 'exa',
      secrets: {},
    })
  )
})
