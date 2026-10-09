import assert from 'node:assert/strict'
import test from 'node:test'

import { CODE_EXTS, CODE_EXT_TO_LANG, langForFilename } from '../../lib/code-languages'

// ---------------------------------------------------------------------------
// Mapping-table invariants
// ---------------------------------------------------------------------------

test('CODE_EXT_TO_LANG keys are normalized lowercase extensions with a leading dot', () => {
  const keys = Object.keys(CODE_EXT_TO_LANG)
  assert.ok(keys.length > 0, 'mapping table must not be empty')
  for (const key of keys) {
    assert.match(key, /^\.[a-z0-9]+$/, `extension key must look like ".py": ${key}`)
  }
})

test('CODE_EXT_TO_LANG values are non-empty lowercase Prism language names', () => {
  for (const [ext, lang] of Object.entries(CODE_EXT_TO_LANG)) {
    assert.match(lang, /^[a-z]+$/, `Prism name for ${ext} must be lowercase letters: ${lang}`)
  }
})

test('CODE_EXTS mirrors every key of CODE_EXT_TO_LANG', () => {
  const keys = Object.keys(CODE_EXT_TO_LANG)
  assert.equal(CODE_EXTS.size, keys.length)
  for (const key of keys) {
    assert.ok(CODE_EXTS.has(key), `CODE_EXTS missing ${key}`)
  }
})

// ---------------------------------------------------------------------------
// langForFilename — mainstream extensions
// ---------------------------------------------------------------------------

const NORMAL_CASES: Array<[filename: string, expected: string]> = [
  ['main.py', 'python'],
  ['app.ts', 'typescript'],
  ['Component.tsx', 'tsx'],
  ['Index.jsx', 'jsx'],
  ['Server.java', 'java'],
  ['server.go', 'go'],
  ['lib.rs', 'rust'],
  ['build.sh', 'bash'],
  ['package.json', 'json'],
  ['schema.sql', 'sql'],
  ['styles.scss', 'scss'],
  ['docker-compose.yaml', 'yaml'],
  ['MAIN.PY', 'python'],
  ['App.TSX', 'tsx'],
  ['src/utils/helpers.js', 'javascript'],
  ['a.b/c.ts', 'typescript'],
]

test('langForFilename resolves mainstream extensions to Prism names', () => {
  for (const [filename, expected] of NORMAL_CASES) {
    assert.equal(langForFilename(filename), expected, `langForFilename(${filename})`)
  }
})

// ---------------------------------------------------------------------------
// langForFilename — alias extensions sharing one Prism language
// ---------------------------------------------------------------------------

const ALIAS_GROUPS: Array<[aliases: string[], expected: string]> = [
  [['.js', '.mjs', '.cjs'], 'javascript'],
  [['.ts', '.mts', '.cts'], 'typescript'],
  [['.c', '.h'], 'c'],
  [['.cpp', '.cc', '.cxx', '.hpp', '.hh', '.hxx'], 'cpp'],
  [['.cs'], 'csharp'],
  [['.kt', '.kts'], 'kotlin'],
  [['.m', '.mm'], 'objectivec'],
  [['.rb'], 'ruby'],
  [['.pl', '.pm'], 'perl'],
  [['.html', '.htm', '.xml', '.vue', '.svelte'], 'markup'],
  [['.css'], 'css'],
  [['.scss'], 'scss'],
  [['.sass'], 'sass'],
  [['.less'], 'less'],
  [['.json', '.jsonc', '.json5'], 'json'],
  [['.yaml', '.yml'], 'yaml'],
  [['.ini', '.cfg', '.properties'], 'ini'],
  [['.sh', '.bash', '.zsh', '.fish'], 'bash'],
  [['.graphql', '.gql'], 'graphql'],
  [['.tf', '.hcl'], 'hcl'],
  [['.tex', '.latex', '.bib'], 'latex'],
  [['.ex', '.exs'], 'elixir'],
  [['.clj', '.cljs', '.cljc'], 'clojure'],
  [['.fs', '.fsx'], 'fsharp'],
  [['.ml', '.mli'], 'ocaml'],
]

test('langForFilename maps every alias of a group to the same Prism language', () => {
  for (const [aliases, expected] of ALIAS_GROUPS) {
    for (const ext of aliases) {
      assert.ok(ext in CODE_EXT_TO_LANG, `${ext} must stay registered in CODE_EXT_TO_LANG`)
      assert.equal(
        langForFilename(`file${ext}`),
        expected,
        `langForFilename(file${ext}) must resolve like its group`
      )
    }
  }
})

// ---------------------------------------------------------------------------
// langForFilename — special filenames take precedence
// ---------------------------------------------------------------------------

const NAMED_CASES: Array<[filename: string, expected: string]> = [
  ['Dockerfile', 'docker'],
  ['dockerfile', 'docker'],
  ['deploy/Dockerfile', 'docker'],
  ['Makefile', 'makefile'],
  ['makefile', 'makefile'],
  ['CMakeLists.txt', 'cmake'],
  ['cmakelists', 'cmake'],
  ['Rakefile', 'ruby'],
  ['Gemfile', 'ruby'],
  ['nginx.conf', 'nginx'],
  ['etc/nginx/nginx.conf', 'nginx'],
  ['.bashrc', 'bash'],
  ['.zshrc', 'bash'],
  ['.bash_profile', 'bash'],
  ['.profile', 'bash'],
  ['home/xzh/.bashrc', 'bash'],
]

test('langForFilename resolves special filenames before extension lookup', () => {
  for (const [filename, expected] of NAMED_CASES) {
    assert.equal(langForFilename(filename), expected, `langForFilename(${filename})`)
  }
})

// ---------------------------------------------------------------------------
// langForFilename — unknown input falls back to null
// ---------------------------------------------------------------------------

const UNKNOWN_CASES: string[] = [
  '',
  'README',
  'notes.txt',
  'archive.tar.gz',
  'file.',
  '/',
  'Dockerfile.backup',
  'data.unknown',
]

test('langForFilename returns null for unrecognised filenames', () => {
  for (const filename of UNKNOWN_CASES) {
    assert.equal(langForFilename(filename), null, `langForFilename(${filename})`)
  }
})
