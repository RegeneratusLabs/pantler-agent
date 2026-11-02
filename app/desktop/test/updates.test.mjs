import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import test from 'node:test'

import { createUpdater } from '../src/updates.mjs'

class FakeUpdater extends EventEmitter {
  constructor(order) {
    super()
    this.order = order
    this.autoDownload = false
    this.autoInstallOnAppQuit = true
    this.checks = 0
    this.installs = []
  }

  async checkForUpdates() {
    this.checks += 1
    return null
  }

  quitAndInstall(...args) {
    this.order.push('install')
    this.installs.push(args)
  }
}

function harness({ stopChildren } = {}) {
  const order = []
  const timers = { timeouts: [], intervals: [] }
  const cleared = []
  const states = []
  const updater = new FakeUpdater(order)
  const controller = createUpdater({
    updater,
    currentVersion: '0.0.4',
    stopChildren: stopChildren ?? (async () => order.push('stop')),
    onState: state => states.push(state),
    trace: () => {},
    intervalMs: 1_000,
    firstDelayMs: 500,
    setTimeoutFn: (fn, ms) => {
      const timer = { fn, ms, unref() {} }
      timers.timeouts.push(timer)
      return timer
    },
    clearTimeoutFn: timer => cleared.push(timer),
    setIntervalFn: (fn, ms) => {
      const timer = { fn, ms, unref() {} }
      timers.intervals.push(timer)
      return timer
    },
    clearIntervalFn: timer => cleared.push(timer)
  })
  return { controller, updater, timers, cleared, states, order }
}

test('start downloads in the background but never installs on quit', () => {
  const { controller, updater, timers } = harness()
  const state = controller.start()

  assert.equal(state.status, 'idle')
  assert.equal(updater.autoDownload, true)
  assert.equal(updater.autoInstallOnAppQuit, false)
  assert.equal(timers.timeouts.length, 1)
  assert.equal(timers.timeouts[0].ms, 500)
  assert.equal(timers.intervals.length, 1)
})

test('the first check is deferred, then runs', () => {
  const { controller, updater, timers } = harness()
  controller.start()
  assert.equal(updater.checks, 0)

  timers.timeouts[0].fn()
  assert.equal(updater.checks, 1)
  assert.equal(controller.snapshot().status, 'checking')
})

test('the events become the state the page reads', () => {
  const { controller, updater, states } = harness()
  controller.start()

  updater.emit('checking-for-update')
  updater.emit('update-available', { version: '0.0.5' })
  updater.emit('download-progress', { percent: 42.4 })
  updater.emit('update-downloaded', { version: '0.0.5' })

  assert.deepEqual(
    states.map(state => state.status),
    ['checking', 'available', 'downloading', 'downloaded']
  )
  const state = controller.snapshot()
  assert.equal(state.version, '0.0.5')
  assert.equal(state.percent, 100)
  assert.equal(state.currentVersion, '0.0.4')
})

test('no update leaves the state idle with the time it was checked', () => {
  const { controller, updater } = harness()
  controller.start()
  updater.emit('update-not-available')

  const state = controller.snapshot()
  assert.equal(state.status, 'idle')
  assert.equal(typeof state.checkedAt, 'number')
})

test('an updater error is a state, not a thrown boot', () => {
  const { controller, updater } = harness()
  controller.start()
  updater.emit('error', new Error('feed unreachable'))

  const state = controller.snapshot()
  assert.equal(state.status, 'error')
  assert.match(state.error, /feed unreachable/)
})

test('install without a downloaded update is refused', async () => {
  const { controller, updater } = harness()
  controller.start()

  const result = await controller.install()
  assert.equal(result.ok, false)
  assert.equal(updater.installs.length, 0)
})

test('install stops the children before the installer runs', async () => {
  const { controller, updater, order } = harness()
  controller.start()
  updater.emit('update-downloaded', { version: '0.0.5' })

  const result = await controller.install()

  assert.equal(result.ok, true)
  // The whole point: the engine must be gone before `quitAndInstall` spawns the installer.
  assert.deepEqual(order, ['stop', 'install'])
  assert.deepEqual(updater.installs[0], [true, true])
})

test('a child that will not stop is a failed install, not a half-closed app', async () => {
  const { controller, updater } = harness({
    stopChildren: async () => {
      throw new Error('engine did not exit')
    }
  })
  controller.start()
  updater.emit('update-downloaded', { version: '0.0.5' })

  const result = await controller.install()

  assert.equal(result.ok, false)
  assert.match(result.error, /engine did not exit/)
  assert.equal(updater.installs.length, 0)
  assert.equal(controller.snapshot().status, 'error')
})

test('a check is not started over a download in flight', async () => {
  const { controller, updater } = harness()
  controller.start()
  updater.emit('update-available', { version: '0.0.5' })

  await controller.check()
  assert.equal(updater.checks, 0)
})

test('dispose clears both timers', () => {
  const { controller, cleared } = harness()
  controller.start()
  controller.dispose()
  assert.equal(cleared.length, 2)
})
