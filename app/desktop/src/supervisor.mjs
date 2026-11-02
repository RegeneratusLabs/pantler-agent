/**
 * The shell's child-process supervisor.
 *
 * Two children, one lifetime: the engine gateway and the BFF. A desktop app that loses either one
 * looks exactly like a broken product, so the rules are explicit:
 *
 *   * start a child, capture its output to a file, and notice its exit;
 *   * restart it with a bounded, growing delay, and stop restarting after a small budget — a crash
 *     loop must become a visible message, not an invisible fan;
 *   * shutdown is deliberate: no restart may be scheduled after `stop`, and `stopAll` waits for
 *     both children to leave before the app does.
 *
 * `spawn` is injected so the whole thing is testable with fake children; this file imports no
 * Electron.
 */

import { spawn as nodeSpawn } from 'node:child_process'
import { createWriteStream, mkdirSync } from 'node:fs'
import path from 'node:path'

export class Supervisor {
  constructor({
    spawn = nodeSpawn,
    logDir = null,
    maxRestarts = 5,
    restartDelayMs = 1_000,
    maxRestartDelayMs = 30_000,
    setTimeoutFn = setTimeout,
    clearTimeoutFn = clearTimeout,
    onEvent = () => {}
  } = {}) {
    this.spawn = spawn
    this.logDir = logDir
    this.maxRestarts = maxRestarts
    this.restartDelayMs = restartDelayMs
    this.maxRestartDelayMs = maxRestartDelayMs
    this.setTimeoutFn = setTimeoutFn
    this.clearTimeoutFn = clearTimeoutFn
    this.onEvent = onEvent
    this.children = new Map()
    if (logDir) mkdirSync(logDir, { recursive: true })
  }

  /** Start one named child. Starting a name twice is a programming error, not a restart. */
  start(name, command, args = [], { env = process.env, cwd = undefined } = {}) {
    if (this.children.has(name)) {
      throw new Error(`supervisor: ${name} is already started`)
    }
    const record = {
      name,
      command,
      args,
      env,
      cwd,
      child: null,
      pid: null,
      restarts: 0,
      stopping: false,
      timer: null,
      state: 'starting'
    }
    this.children.set(name, record)
    this.#spawn(record)
    return record
  }

  #spawn(record) {
    const child = this.spawn(record.command, record.args, {
      env: record.env,
      cwd: record.cwd,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe']
    })
    record.child = child
    record.pid = child.pid ?? null
    record.state = 'running'
    this.#pipeOutput(record, child)
    child.once('error', error => {
      this.onEvent({ type: 'error', name: record.name, error })
      if (!record.stopping) this.#scheduleRestart(record)
    })
    child.once('exit', (code, signal) => {
      record.state = 'exited'
      record.child = null
      this.onEvent({ type: 'exit', name: record.name, code, signal })
      if (!record.stopping) this.#scheduleRestart(record)
    })
  }

  #pipeOutput(record, child) {
    if (!this.logDir) return
    const stream = createWriteStream(path.join(this.logDir, `${record.name}.log`), { flags: 'a' })
    for (const [source, prefix] of [
      [child.stdout, `${record.name}: `],
      [child.stderr, `${record.name}: `]
    ]) {
      if (!source?.on) continue
      source.on('data', chunk => stream.write(`${prefix}${chunk.toString()}`))
    }
    child.once('exit', () => stream.end())
  }

  #scheduleRestart(record) {
    if (record.restarts >= this.maxRestarts) {
      record.state = 'gave-up'
      this.onEvent({ type: 'gave-up', name: record.name, restarts: record.restarts })
      return
    }
    const delay = Math.min(
      this.restartDelayMs * 2 ** record.restarts,
      this.maxRestartDelayMs
    )
    record.restarts += 1
    record.state = 'restarting'
    this.onEvent({ type: 'restarting', name: record.name, delay, attempt: record.restarts })
    record.timer = this.setTimeoutFn(() => {
      record.timer = null
      if (record.stopping) return
      this.#spawn(record)
    }, delay)
    // Do not keep a desktop app alive just because a restart is pending.
    if (typeof record.timer?.unref === 'function') record.timer.unref()
  }

  /** Stop one child (or every child) and wait for it to exit. No restart is scheduled after this. */
  async stop(name, { graceMs = 5_000 } = {}) {
    const record = this.children.get(name)
    if (!record) return
    record.stopping = true
    if (record.timer) {
      this.clearTimeoutFn(record.timer)
      record.timer = null
    }
    const child = record.child
    if (!child) {
      record.state = 'stopped'
      return
    }
    await new Promise(resolve => {
      let settled = false
      const finish = () => {
        if (settled) return
        settled = true
        resolve()
      }
      child.once('exit', finish)
      try {
        child.kill()
      } catch {
        finish()
      }
      this.setTimeoutFn(() => {
        try {
          child.kill('SIGKILL')
        } catch {
          // It is already gone; the exit handler (or this timeout) settles the promise.
        }
        finish()
      }, graceMs).unref?.()
    })
    record.state = 'stopped'
    record.child = null
  }

  async stopAll(options) {
    await Promise.all([...this.children.keys()].map(name => this.stop(name, options)))
  }

  status() {
    return Object.fromEntries(
      [...this.children.entries()].map(([name, record]) => [
        name,
        { state: record.state, pid: record.pid, restarts: record.restarts }
      ])
    )
  }
}
