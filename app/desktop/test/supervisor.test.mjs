import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import test from 'node:test'

import { Supervisor } from '../src/supervisor.mjs'

class FakeChild extends EventEmitter {
  constructor(pid) {
    super()
    this.pid = pid
    this.stdout = new EventEmitter()
    this.stderr = new EventEmitter()
    this.signals = []
  }

  kill(signal = 'SIGTERM') {
    this.signals.push(signal)
    queueMicrotask(() => this.emit('exit', 0, signal))
  }
}

function harness({ maxRestarts = 5 } = {}) {
  const children = []
  const timers = []
  const cleared = []
  const events = []
  const spawn = (command, args) => {
    const child = new FakeChild(1000 + children.length)
    children.push({ command, args, child })
    return child
  }
  const supervisor = new Supervisor({
    spawn,
    maxRestarts,
    setTimeoutFn: (fn, delay) => {
      const timer = { fn, delay, unref() {} }
      timers.push(timer)
      return timer
    },
    clearTimeoutFn: timer => {
      cleared.push(timer)
    },
    onEvent: event => events.push(event)
  })
  return { supervisor, children, timers, cleared, events }
}

test('start records the child and its pid', () => {
  const { supervisor, children } = harness()
  supervisor.start('engine', 'hermes', ['-p', 'pantler', 'gateway', 'run'])
  assert.equal(children.length, 1)
  assert.equal(children[0].command, 'hermes')
  assert.deepEqual(supervisor.status().engine, { state: 'running', pid: 1000, restarts: 0 })
})

test('starting the same name twice is refused', () => {
  const { supervisor } = harness()
  supervisor.start('engine', 'hermes', [])
  assert.throws(() => supervisor.start('engine', 'hermes', []), /already started/)
})

test('an exit schedules a growing restart, and running it respawns', () => {
  const { supervisor, children, timers } = harness()
  supervisor.start('bff', 'python', ['server.py'])
  children[0].child.emit('exit', 1, null)

  assert.equal(supervisor.status().bff.state, 'restarting')
  assert.equal(timers.length, 1)
  assert.equal(timers[0].delay, 1_000)

  timers[0].fn()
  assert.equal(children.length, 2)
  assert.equal(supervisor.status().bff.state, 'running')
  assert.equal(supervisor.status().bff.restarts, 1)

  children[1].child.emit('exit', 1, null)
  assert.equal(timers.at(-1).delay, 2_000)
})

test('the restart budget is bounded and then the supervisor gives up visibly', () => {
  const { supervisor, children, timers, events } = harness({ maxRestarts: 1 })
  supervisor.start('engine', 'hermes', [])

  children[0].child.emit('exit', 1, null)
  assert.equal(timers.length, 1)
  timers[0].fn()

  children[1].child.emit('exit', 1, null)
  assert.equal(supervisor.status().engine.state, 'gave-up')
  assert.equal(events.at(-1).type, 'gave-up')
  assert.equal(timers.length, 1, 'no second timer was scheduled')
})

test('stop cancels a pending restart and waits for the child to leave', async () => {
  const { supervisor, children, cleared } = harness()
  supervisor.start('engine', 'hermes', [])
  const child = children[0].child

  const stopping = supervisor.stop('engine')
  assert.deepEqual(child.signals, ['SIGTERM'])
  await stopping

  assert.equal(supervisor.status().engine.state, 'stopped')
  assert.equal(cleared.length, 0, 'no timer existed to clear')

  // A deliberate stop must not schedule a restart when the exit arrives late.
  child.emit('exit', 0, 'SIGTERM')
  assert.equal(supervisor.status().engine.state, 'stopped')
})

test('stop clears a restart that was already scheduled', async () => {
  const { supervisor, children, cleared } = harness()
  supervisor.start('engine', 'hermes', [])
  children[0].child.emit('exit', 1, null)
  await supervisor.stop('engine')
  assert.equal(cleared.length, 1)
  assert.equal(supervisor.status().engine.state, 'stopped')
})

test('a spawn error is reported and also restarted', () => {
  const { supervisor, children, timers, events } = harness()
  supervisor.start('engine', 'missing-binary', [])
  children[0].child.emit('error', new Error('ENOENT'))
  assert.equal(events[0].type, 'error')
  assert.equal(timers.length, 1)
})

test('stopAll stops every child', async () => {
  const { supervisor } = harness()
  supervisor.start('engine', 'hermes', [])
  supervisor.start('bff', 'python', [])
  await supervisor.stopAll()
  assert.deepEqual(
    Object.values(supervisor.status()).map(entry => entry.state),
    ['stopped', 'stopped']
  )
})
