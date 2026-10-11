# 硬编码文案清单（v1.6.14 复扫）

基线：origin/main @ 6cf793bd8 (v1.6.14)。方法：web/scripts/i18n_audit.mjs 启发式（jsxText + title/placeholder/alt/aria-label + alert()/confirm()），并叠加动态 t() 同文件字面量 map 核查。

## 计数

- 启发式命中：31 处，分布在 17 个文件
- 分类后疑似真实文案漂移：0（全部为技术性占位符/单位/符号/语言名：`you@example.com`、`sk-...`、`MB`、`tokens`、`Σ`、`English`/`中文` 等）
- 动态 t() 调用点：278 处 / 118 文件；抽查同文件/导入的字面量 map（如 accountRoleLabelKey → Admin/Teacher/Student/User、inline `{running:"Running"...}`），取值均为有效目录 key，非 key 字面量 0 个

## 全量命中（人工复核为良性）


### app/(auth)/login/page.tsx
- L105 `attr:placeholder`: "you@example.com"

### app/(auth)/register/page.tsx
- L99 `attr:placeholder`: "you@example.com"

### app/(utility)/avatar-preview/page.tsx
- L110 `jsxText`: "px"

### app/(workspace)/partners/new/page.tsx
- L346 `jsxText`: "English"
- L347 `jsxText`: "中文"

### components/knowledge/KbIndexingRun.tsx
- L68 `jsxText`: "s ·"
- L68 `jsxText`: "s ·"

### components/mcp/McpServerForm.tsx
- L196 `attr:placeholder`: "my-server"
- L234 `attr:placeholder`: "npx"
- L259 `attr:placeholder`: "/path/to/workdir"
- L285 `attr:placeholder`: "https://example.com/mcp"

### components/memory/MemoryGraph.tsx
- L551 `jsxText`: "L3"

### components/memory/MemoryRunPanel.tsx
- L775 `jsxText`: "·&nbsp;"

### components/partners/PartnerConfigure.tsx
- L357 `jsxText`: "English"
- L358 `jsxText`: "中文"

### components/partners/SoulEditor.tsx
- L40 `jsxText`: "SOUL.md"

### components/settings/ConnectionsEditor.tsx
- L463 `attr:placeholder`: "sk-..."
- L629 `attr:placeholder`: "sk-..."

### components/settings/ServiceConfigEditor.tsx
- L899 `attr:placeholder`: "gpt-4o"
- L1082 `attr:placeholder`: "alloy"
- L1149 `attr:placeholder`: "1024x1024"
- L1258 `attr:placeholder`: "720p"
- L1714 `attr:placeholder`: "sk-..."
- L1868 `attr:placeholder`: "{\"APP-Code\":\"your-app-code\"}"

### components/settings/VoiceModelFields.tsx
- L123 `attr:placeholder`: "volc.bigasr.auc_turbo"

### features/co-writer/components/CoWriterWorkspace.tsx
- L1275 `jsxText`: "&Sigma;"
- L1760 `jsxText`: "&middot;"

### features/runtime-status/TurnCoordinationSettings.tsx
- L86 `jsxText`: "Redis"

### features/settings/sections/DataMigrationSettingsSection.tsx
- L261 `jsxText`: "MB"
- L319 `jsxText`: "MB"

### features/settings/sections/UsageSettingsSection.tsx
- L212 `jsxText`: "tokens"

## 与 fix-web-hardcoded-i18n 去重

- myfork/fix/web-hardcoded-i18n-20261006（59d77fa9f，未合入 origin/main）修复的 10 个源文件（ConnectedAgents/SettingsNav/SubagentSettingsEditor/EduHubImportModal/SpaceDashboard/ToolsSettingsSection/useTopicSourceLibrary/quiz-types/research-types/tool-availability）在 main 上仍是修复前状态（zh/en 三元文案），按任务口径记为“已覆盖，只核对不重复”。
- 上述修复文件与本清单 17 个文件零交集 → v1.6.14 后无新增硬编码漂移。