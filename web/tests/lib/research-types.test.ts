import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildResearchWSConfig,
  createEmptyResearchConfig,
  normalizeResearchConfig,
  summarizeResearchConfig,
  validateResearchConfig,
} from '../../lib/research-types'
import type {
  DeepResearchFormConfig,
  OutlineItem,
  ResearchDepth,
  ResearchMode,
} from '../../lib/research-types'

// ── fixtures ──────────────────────────────────────────────────────────

const outline = (title: string, overview = `overview of ${title}`): OutlineItem => ({
  title,
  overview,
})

const config = (overrides: Partial<DeepResearchFormConfig> = {}): DeepResearchFormConfig => ({
  mode: 'report',
  depth: 'standard',
  ...overrides,
})

// ── createEmptyResearchConfig ─────────────────────────────────────────

test('createEmptyResearchConfig: blank form starts with empty mode and depth', () => {
  assert.deepEqual(createEmptyResearchConfig(), { mode: '', depth: '' })
})

test('createEmptyResearchConfig: returns a fresh object each call', () => {
  const a = createEmptyResearchConfig()
  const b = createEmptyResearchConfig()
  assert.notEqual(a, b)
  assert.deepEqual(a, b)
})

// ── normalizeResearchConfig ───────────────────────────────────────────

test('normalizeResearchConfig: accepts every whitelisted mode/depth pair', () => {
  const cases: Array<{ raw: Record<string, unknown>; mode: ResearchMode; depth: ResearchDepth }> = [
    { raw: { mode: 'notes', depth: 'quick' }, mode: 'notes', depth: 'quick' },
    { raw: { mode: 'report', depth: 'standard' }, mode: 'report', depth: 'standard' },
    { raw: { mode: 'comparison', depth: 'deep' }, mode: 'comparison', depth: 'deep' },
    { raw: { mode: 'learning_path', depth: 'manual' }, mode: 'learning_path', depth: 'manual' },
  ]
  for (const c of cases) {
    assert.deepEqual(normalizeResearchConfig(c.raw), { mode: c.mode, depth: c.depth }, c.mode)
  }
})

test('normalizeResearchConfig: normalizes each field independently against its whitelist', () => {
  const cases: Array<{
    name: string
    raw?: Record<string, unknown>
    mode: ResearchMode
    depth: ResearchDepth
  }> = [
    { name: 'undefined raw', raw: undefined, mode: '', depth: '' },
    { name: 'empty object', raw: {}, mode: '', depth: '' },
    { name: 'unknown mode', raw: { mode: 'summary', depth: 'quick' }, mode: '', depth: 'quick' },
    {
      name: 'unknown depth',
      raw: { mode: 'report', depth: 'exhaustive' },
      mode: 'report',
      depth: '',
    },
    {
      name: 'case-sensitive mode',
      raw: { mode: 'Report', depth: 'quick' },
      mode: '',
      depth: 'quick',
    },
    {
      name: 'case-sensitive depth',
      raw: { mode: 'notes', depth: 'Quick' },
      mode: 'notes',
      depth: '',
    },
    { name: 'non-string mode', raw: { mode: 7, depth: 'deep' }, mode: '', depth: 'deep' },
    { name: 'non-string depth', raw: { mode: 'notes', depth: null }, mode: 'notes', depth: '' },
    { name: 'empty strings', raw: { mode: '', depth: '' }, mode: '', depth: '' },
  ]
  for (const c of cases) {
    assert.deepEqual(normalizeResearchConfig(c.raw), { mode: c.mode, depth: c.depth }, c.name)
  }
})

test('normalizeResearchConfig: drops fields outside the form contract', () => {
  const raw = {
    mode: 'notes',
    depth: 'deep',
    manual_subtopics: 3,
    confirmed_outline: [outline('Intro')],
    extra: 'ignored',
  }
  assert.deepEqual(normalizeResearchConfig(raw), { mode: 'notes', depth: 'deep' })
})

// ── validateResearchConfig ────────────────────────────────────────────

test('validateResearchConfig: complete configs are valid with no errors', () => {
  const cases = [config(), config({ mode: 'learning_path', depth: 'manual' })]
  for (const cfg of cases) {
    assert.deepEqual(validateResearchConfig(cfg), { valid: true, errors: {} })
  }
})

test('validateResearchConfig: missing fields are reported as Required', () => {
  const cases: Array<{
    name: string
    cfg: DeepResearchFormConfig
    errors: Record<string, string>
  }> = [
    { name: 'mode missing', cfg: config({ mode: '' }), errors: { mode: 'Required' } },
    { name: 'depth missing', cfg: config({ depth: '' }), errors: { depth: 'Required' } },
    {
      name: 'both missing',
      cfg: config({ mode: '', depth: '' }),
      errors: { mode: 'Required', depth: 'Required' },
    },
  ]
  for (const c of cases) {
    const result = validateResearchConfig(c.cfg)
    assert.equal(result.valid, false, c.name)
    assert.deepEqual(result.errors, c.errors, c.name)
  }
})

// ── buildResearchWSConfig ─────────────────────────────────────────────

test('buildResearchWSConfig: valid configs emit the ws payload contract', () => {
  const cases: Array<{ cfg: DeepResearchFormConfig; expected: Record<string, unknown> }> = [
    { cfg: config({ mode: 'notes', depth: 'quick' }), expected: { mode: 'notes', depth: 'quick' } },
    {
      cfg: config({ mode: 'comparison', depth: 'standard' }),
      expected: { mode: 'comparison', depth: 'standard' },
    },
  ]
  for (const c of cases) {
    assert.deepEqual(buildResearchWSConfig(c.cfg), c.expected)
  }
})

test('buildResearchWSConfig: incomplete configs are rejected before any payload is built', () => {
  const cases: Array<{ name: string; cfg: DeepResearchFormConfig }> = [
    { name: 'mode missing', cfg: config({ mode: '' }) },
    { name: 'depth missing', cfg: config({ depth: '' }) },
    { name: 'both missing', cfg: config({ mode: '', depth: '' }) },
  ]
  for (const c of cases) {
    assert.throws(
      () => buildResearchWSConfig(c.cfg),
      {
        name: 'Error',
        message: 'Deep research settings are incomplete.',
      },
      c.name
    )
  }
})

test('buildResearchWSConfig: manual depth carries manual tuning fields', () => {
  const cases: Array<{
    name: string
    cfg: DeepResearchFormConfig
    expected: Record<string, unknown>
  }> = [
    {
      name: 'both fields set',
      cfg: config({
        mode: 'learning_path',
        depth: 'manual',
        manual_subtopics: 3,
        manual_max_iterations: 2,
      }),
      expected: {
        mode: 'learning_path',
        depth: 'manual',
        manual_subtopics: 3,
        manual_max_iterations: 2,
      },
    },
    {
      name: 'zero values are kept',
      cfg: config({ depth: 'manual', manual_subtopics: 0, manual_max_iterations: 0 }),
      expected: { mode: 'report', depth: 'manual', manual_subtopics: 0, manual_max_iterations: 0 },
    },
  ]
  for (const c of cases) {
    assert.deepEqual(buildResearchWSConfig(c.cfg), c.expected, c.name)
  }
})

test('buildResearchWSConfig: nullish manual fields are omitted, even at manual depth', () => {
  const cfg = config({
    depth: 'manual',
    manual_subtopics: null as unknown as number,
    manual_max_iterations: undefined,
  })
  assert.deepEqual(buildResearchWSConfig(cfg), { mode: 'report', depth: 'manual' })
})

test('buildResearchWSConfig: manual fields are omitted outside manual depth', () => {
  const cfg = config({
    mode: 'notes',
    depth: 'deep',
    manual_subtopics: 5,
    manual_max_iterations: 9,
  })
  assert.deepEqual(buildResearchWSConfig(cfg), { mode: 'notes', depth: 'deep' })
})

test('buildResearchWSConfig: outline argument takes precedence over the form value', () => {
  const argOutline = [outline('From Arg')]
  const cfg = config({ confirmed_outline: [outline('From Config')] })
  assert.deepEqual(buildResearchWSConfig(cfg, argOutline), {
    mode: 'report',
    depth: 'standard',
    confirmed_outline: argOutline,
  })
})

test('buildResearchWSConfig: form outline is used when no argument is given', () => {
  const cfgOutline = [outline('From Config', 'overview')]
  const cfg = config({ confirmed_outline: cfgOutline })
  assert.deepEqual(buildResearchWSConfig(cfg), {
    mode: 'report',
    depth: 'standard',
    confirmed_outline: cfgOutline,
  })
})

test('buildResearchWSConfig: empty outlines are not sent to the backend', () => {
  const cases: Array<{ name: string; cfg: DeepResearchFormConfig; arg?: OutlineItem[] }> = [
    { name: 'no outline anywhere', cfg: config() },
    { name: 'empty form outline', cfg: config({ confirmed_outline: [] }) },
    {
      name: 'empty argument shadows form outline',
      cfg: config({ confirmed_outline: [outline('Kept')] }),
      arg: [],
    },
  ]
  for (const c of cases) {
    assert.deepEqual(
      buildResearchWSConfig(c.cfg, c.arg),
      { mode: 'report', depth: 'standard' },
      c.name
    )
  }
})

// ── summarizeResearchConfig ───────────────────────────────────────────

test('summarizeResearchConfig: known mode/depth pairs map to their labels', () => {
  const cases: Array<{ mode: ResearchMode; depth: ResearchDepth; expected: string }> = [
    { mode: 'notes', depth: 'quick', expected: 'Study Notes · Quick' },
    { mode: 'report', depth: 'standard', expected: 'Report · Standard' },
    { mode: 'comparison', depth: 'deep', expected: 'Comparison · Deep' },
    { mode: 'learning_path', depth: 'manual', expected: 'Learning Path · Manual' },
  ]
  for (const c of cases) {
    assert.equal(summarizeResearchConfig(config({ mode: c.mode, depth: c.depth })), c.expected)
  }
})

test('summarizeResearchConfig: incomplete configs summarize as a single message', () => {
  const cases = [config({ mode: '', depth: 'quick' }), config({ mode: 'report', depth: '' })]
  for (const cfg of cases) {
    assert.equal(summarizeResearchConfig(cfg), 'Incomplete settings')
  }
})

test('summarizeResearchConfig: unknown values fall back to humanized raw strings', () => {
  const cases: Array<{ name: string; cfg: DeepResearchFormConfig; expected: string }> = [
    {
      name: 'snake_case mode is humanized with the first underscore',
      cfg: config({ mode: 'custom_mode' as ResearchMode, depth: 'deep' }),
      expected: 'custom mode · Deep',
    },
    {
      name: 'only the first underscore is replaced',
      cfg: config({ mode: 'foo_bar_baz' as ResearchMode, depth: 'deep' }),
      expected: 'foo bar_baz · Deep',
    },
    {
      name: 'unknown depth is echoed verbatim',
      cfg: config({ mode: 'notes', depth: 'extreme' as ResearchDepth }),
      expected: 'Study Notes · extreme',
    },
  ]
  for (const c of cases) {
    assert.equal(summarizeResearchConfig(c.cfg), c.expected, c.name)
  }
})

test('summarizeResearchConfig: translate hook covers labels and the fallback message', () => {
  const zh: Record<string, string> = {
    'Learning Path': '学习路径',
    Manual: '手动',
    'Incomplete settings': '设置未完成',
  }
  const translate = (key: string) => zh[key] ?? key
  assert.equal(
    summarizeResearchConfig(config({ mode: 'learning_path', depth: 'manual' }), translate),
    '学习路径 · 手动'
  )
  assert.equal(
    summarizeResearchConfig(config({ mode: '', depth: 'quick' }), translate),
    '设置未完成'
  )
})
