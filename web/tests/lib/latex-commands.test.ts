import assert from 'node:assert/strict'
import test from 'node:test'

import {
  KATEX_COMMANDS,
  isKnownLatexCommand,
  isMathTriggerCommand,
} from '../../lib/latex-commands'

test('KATEX_COMMANDS contains representative control sequences', () => {
  for (const name of [
    'overline',
    'frac',
    'alpha',
    'sum',
    'sqrt',
    'textbf',
    'Overrightarrow',
    'redA',
  ]) {
    assert.ok(KATEX_COMMANDS.has(name), `expected ${name} in command table`)
  }
})

test('KATEX_COMMANDS lists only alphabetic names of three characters or more', () => {
  for (const name of KATEX_COMMANDS) {
    assert.match(name, /^[a-zA-Z]{3,}$/)
    assert.equal(name, name.trim())
  }
  assert.ok(KATEX_COMMANDS.size >= 900, `unexpectedly small table: ${KATEX_COMMANDS.size}`)
  assert.ok(!KATEX_COMMANDS.has(''), 'empty token must never enter the table')
})

test('isKnownLatexCommand accepts known multi-character commands', () => {
  for (const name of ['overline', 'frac', 'sqrt', 'textbf', 'sum', 'binom']) {
    assert.equal(isKnownLatexCommand(name), true, name)
  }
})

test('isKnownLatexCommand accepts one- and two-letter names unconditionally', () => {
  for (const name of ['i', 'to', 'ne', 'x', 'zz']) {
    assert.equal(isKnownLatexCommand(name), true, name)
  }
})

test('isKnownLatexCommand is case sensitive', () => {
  assert.equal(isKnownLatexCommand('overline'), true)
  assert.equal(isKnownLatexCommand('Overline'), false)
  assert.equal(isKnownLatexCommand('OVERLINE'), false)
  assert.equal(isKnownLatexCommand('Frac'), false)
})

test('isKnownLatexCommand rejects unknown multi-character names', () => {
  for (const name of ['notacommand', 'sinhxx', 'latexcommand', 'fracfrac']) {
    assert.equal(isKnownLatexCommand(name), false, name)
  }
})

test('isMathTriggerCommand admits strong math commands', () => {
  for (const name of ['overline', 'frac', 'alpha', 'sum', 'binom', 'sqrt']) {
    assert.equal(isMathTriggerCommand(name), true, name)
  }
})

test('isMathTriggerCommand rejects weak colour and markup helpers even when known', () => {
  const weakButKnown = [
    'red',
    'blue',
    'textbf',
    'text',
    'textrm',
    'url',
    'href',
    'LaTeX',
    'KaTeX',
    'relax',
    'includegraphics',
    'redA',
    'blueE',
    'kaBlue',
  ]
  for (const name of weakButKnown) {
    assert.equal(isKnownLatexCommand(name), true, `${name} should stay a known command`)
    assert.equal(isMathTriggerCommand(name), false, `${name} must not trigger`)
  }
})

test('isMathTriggerCommand never fires for one- and two-letter names', () => {
  for (const name of ['i', 'to', 'ne', 'ab']) {
    assert.equal(isMathTriggerCommand(name), false, name)
  }
})

test('isMathTriggerCommand rejects unknown names', () => {
  for (const name of ['notacommand', 'Overline', 'teal', 'gold', 'maroon', 'mint']) {
    assert.equal(isMathTriggerCommand(name), false, name)
  }
})

test('empty input stays safe for both predicates', () => {
  assert.equal(isKnownLatexCommand(''), true)
  assert.equal(isMathTriggerCommand(''), false)
})

test('padded, backslash-prefixed and punctuated names fall back to unknown', () => {
  const malformed = [
    ' overline',
    'overline ',
    '\\overline',
    'overline\n',
    'frac(',
    'red1',
    'al-pha',
    'αlpha',
  ]
  for (const name of malformed) {
    assert.equal(isKnownLatexCommand(name), false, JSON.stringify(name))
    assert.equal(isMathTriggerCommand(name), false, JSON.stringify(name))
  }
})
