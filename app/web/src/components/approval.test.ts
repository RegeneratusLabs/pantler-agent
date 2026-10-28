/**
 * The translation from the engine's rule names to words an operator can act on.
 *
 * The cases that matter are the ones where being wrong is dangerous: a destructive pattern
 * that reads as routine, or a sentence that reassures where it should warn. So the table
 * below is mostly the *engine's own* names — taken from `tools/approval_detection.py`, where
 * there are 117 of them — with the tone each one has to produce.
 */

import { describe, expect, it } from 'vitest'
import { ALWAYS_WARNING, choiceLabel, flaggedAs, NO_ANSWER, readApproval, resolvedLabel } from './approval'

const reading = (description: string, command?: string, smartDenied = false) =>
  readApproval({ description, command, smartDenied })

describe('readApproval', () => {
  it('reads the screenshot’s own card as a question, not an alarm', () => {
    const read = reading('script execution via -e/-c flag', 'python -c "print(1)"')

    expect(read.kind).toBe('command')
    expect(read.tone).toBe('normal')
    expect(read.what).toContain('small program written on the spot')
    expect(read.override).toBe(false)
  })

  it.each([
    ['recursive delete of home directory', 'delete files or data'],
    ['recursive delete of root filesystem', 'delete files or data'],
    ['find -delete', 'delete files or data'],
    ['git clean with force (deletes untracked files)', 'delete files or data'],
    ['package manager uninstall', 'delete files or data'],
    ['SQL DELETE without WHERE', 'delete files or data'],
    ['format filesystem (mkfs)', 'how the computer itself is set up'],
    ['sudo with privilege flag (stdin/askpass/shell/list)', 'how the computer itself is set up'],
    ['system shutdown/reboot', 'how the computer itself is set up'],
    ['stop/delete service (sc)', 'how the computer itself is set up'],
    ['pipe remote content to shell', 'fetch something from the internet and run it'],
    ['execute remote content via Invoke-Expression', 'fetch something from the internet and run it'],
    ['upload a secret or credential file via curl/wget (possible exfiltration)', 'send data off this computer'],
    ['access to SSH keys (Windows path)', 'saved keys, passwords or settings'],
    ['in-place edit of Hermes config/env', 'saved keys, passwords or settings'],
    ['force kill processes (taskkill /F)', 'stop or restart something that is running'],
    ['stop/restart hermes gateway (kills running agents)', 'stop or restart something that is running'],
    ['git force push (rewrites remote history)', 'rewrite saved history in your project'],
    ['git reset --hard (destroys uncommitted changes)', 'rewrite saved history in your project']
  ])('warns plainly about %s', (description, expected) => {
    const read = reading(description, 'rm -rf ~')
    expect(read.tone).toBe('high')
    expect(read.what).toContain(expected)
  })

  it('keeps an inline-code pattern at question weight, because opaque is not destructive', () => {
    expect(reading('script execution via heredoc', 'node <<EOF').tone).toBe('normal')
    expect(reading('shell command via -c/-lc flag', 'bash -c ls').tone).toBe('normal')
  })

  it('never echoes the engine’s rule name as the sentence', () => {
    // The whole point: "recursive delete of home directory" is a rule name, not an answer.
    for (const name of [
      'recursive delete of home directory',
      'script execution via -e/-c flag',
      'docker with remote daemon redirect (-H/--host)'
    ]) {
      expect(reading(name, 'cmd').what).not.toContain(name)
    }
  })

  it('says so when it cannot place the pattern, rather than calling it harmless', () => {
    const read = reading('some future pattern nobody has seen', 'cmd')
    expect(read.tone).toBe('normal')
    expect(read.what).toContain('does not have plain words')
  })

  it('treats a guardian override as the serious thing it is', () => {
    const read = reading('recursive delete', 'rm -rf build', true)
    expect(read.override).toBe(true)
    expect(read.tone).toBe('high')
    expect(read.what).toContain('already checked this and said no')
    expect(read.what).toContain('this one time only')
  })

  it('knows an approval that is not about a command', () => {
    // Nothing in pantler raises one today, but the engine may, and "run it" would be wrong.
    expect(reading('some future pack action').kind).toBe('action')
    expect(reading('some future pack action', 'a command').kind).toBe('command')
  })

  it('reads a connector write as a change in a connected app', () => {
    const read = reading(
      'Connected app change: GMAIL_SEND_EMAIL on gmail. This can send an email. Arguments: {"to":"sam"}'
    )

    expect(read.kind).toBe('action')
    expect(read.tone).toBe('high')
    expect(read.what).toBe('This would change something in one of your connected apps.')
  })

  it('copes with an empty description without inventing anything', () => {
    const read = reading('')
    expect(read.what.length).toBeGreaterThan(0)
    expect(flaggedAs('')).toBe('unnamed pattern')
  })
})

describe('choiceLabel', () => {
  it('never says "send" — the retired gate wrote these and it was never true of a command', () => {
    const labels = (['once', 'session', 'always', 'deny'] as const).map(choice =>
      choiceLabel(choice, 'command')
    )
    expect(labels.join(' ')).not.toMatch(/send/i)
  })

  it('offers a command in command words', () => {
    expect(choiceLabel('once', 'command')).toBe('Run it once')
    expect(choiceLabel('session', 'command')).toBe('Allow this kind for now')
    expect(choiceLabel('deny', 'command')).toBe('No, don’t run it')
  })

  it('offers an unnamed action in action words', () => {
    expect(choiceLabel('once', 'action')).toBe('Do it once')
    expect(choiceLabel('deny', 'action')).toBe('No, don’t do it')
  })

  it('says the permanent grant is permanent', () => {
    expect(choiceLabel('always', 'command')).toMatch(/won’t ask again/)
    expect(ALWAYS_WARNING).toMatch(/after a restart/)
    expect(ALWAYS_WARNING).toMatch(/not watching/)
  })
})

describe('resolvedLabel', () => {
  it('uses the engine’s own words for the three grants', () => {
    expect(resolvedLabel('once')).toBe('Allowed once')
    expect(resolvedLabel('session')).toBe('Allowed for this session')
    expect(resolvedLabel('always')).toBe('Allowed permanently')
    expect(resolvedLabel('deny')).toBe('Denied')
  })
})

describe('the promise made before an answer', () => {
  it('says a parked run is not a trap', () => {
    expect(NO_ANSWER).toMatch(/won’t run/)
  })
})
