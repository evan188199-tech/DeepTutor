import { expect, it } from 'vitest'
import { ensureLanguage, initI18n } from '@/i18n/init'

// Workspace-resource copy that must stay present in the live zh "app"
// namespace. Previously sourced from the unwired zh/common.json (removed
// as a dead locale file); the catalog is inlined so the coverage pin
// outlives that file.
const WORKSPACE_RESOURCE_KEYS = [
  'Suggestions could not be generated. Please try again.',
  'Assigned resources',
  'Resources are managed in Learning Space. Assigning them creates references; removing an assignment keeps the original resource.',
  'MCP services',
  'Knowledge bases',
  '{{resource}} assignment mode',
  'Inherit available resources',
  'Only selected resources',
  'Manage library',
  'Keeps existing access rules. Newly available resources are included automatically.',
  'Loading resources…',
  'No resources available. Add resources in Learning Space first.',
  'Currently unavailable',
  'Resource missing or access removed',
  '{{count}} resources selected',
  'None selected. This resource type is unavailable in this workspace.',
  'Changes apply to subsequent turns. Existing conversations and files are kept.',
  'Account resource library. Manage resources here and assign them to workspaces in Settings.',
  'Skill library',
  'Account shared skills',
  'Skills created here belong to this workspace. Same-name skills override shared versions when enabled.',
  'Shared skills can be assigned to multiple workspaces.',
  'Used by workspaces: {{names}}',
  'account',
  'workspace',
  'builtin',
  'deployment',
  'admin',
  'Account library',
  '{{count}} resources selected_one',
  '{{count}} resources selected_other',
]

it('loads all workspace resource translations in the runtime namespace', async () => {
  const i18n = initI18n()
  await ensureLanguage('zh')
  const t = i18n.getFixedT('zh', 'app')
  for (const key of WORKSPACE_RESOURCE_KEYS) {
    expect(i18n.exists(key, { lng: 'zh', ns: 'app' }), key).toBe(true)
  }
  expect(t('Assigned resources')).toBe('分配资源')
  expect(t('MCP services')).toBe('MCP 服务')
  expect(t('{{count}} resources selected', { count: 2 })).toBe('已选择 2 项资源')
})
