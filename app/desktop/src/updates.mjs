/**
 * The updater, without Electron.
 *
 * `electron-updater` owns the download and the installer launch; this owns the one thing it gets
 * wrong for a supervised app: **the installer is spawned before the app quits**, and Pantler's
 * engine and BFF are children running from the directory the installer replaces. `install()`
 * therefore stops them first and only then calls `quitAndInstall`. Windows will not replace a
 * running `runtime/python.exe`, so the order is the feature.
 *
 * It is Electron-free so the state machine and that order can be tested with a fake updater.
 * `main.mjs` builds it, feeds it `autoUpdater`, and broadcasts the states to the window.
 */

export const UPDATE_INTERVAL_MS = 4 * 60 * 60 * 1000
export const UPDATE_FIRST_DELAY_MS = 15_000

/** @typedef {'idle'|'checking'|'available'|'downloading'|'downloaded'|'error'} UpdateStatus */

function messageOf(error) {
  return error instanceof Error ? error.message : String(error)
}

export function createUpdater({
  updater,
  stopChildren,
  onState = () => {},
  trace = () => {},
  currentVersion = '',
  intervalMs = UPDATE_INTERVAL_MS,
  firstDelayMs = UPDATE_FIRST_DELAY_MS,
  setIntervalFn = setInterval,
  clearIntervalFn = clearInterval,
  setTimeoutFn = setTimeout,
  clearTimeoutFn = clearTimeout
} = {}) {
  let state = {
    status: /** @type {UpdateStatus} */ ('idle'),
    currentVersion,
    version: null,
    percent: null,
    error: null,
    checkedAt: null
  }
  let installing = false
  let interval = null
  let first = null
  let started = false

  const snapshot = () => ({ ...state })

  function publish(patch) {
    state = { ...state, ...patch }
    onState(snapshot())
  }

  function attach() {
    // Download in the background; install only when the operator says so. The auto-install-on-quit
    // path would replace a working app on an ordinary quit, which is not what "prompted" means.
    updater.autoDownload = true
    updater.autoInstallOnAppQuit = false

    updater.on('checking-for-update', () => publish({ status: 'checking', error: null }))
    updater.on('update-available', info =>
      publish({ status: 'available', version: info?.version ?? null, percent: 0 })
    )
    updater.on('download-progress', progress =>
      publish({ status: 'downloading', percent: Math.round(progress?.percent ?? 0) })
    )
    updater.on('update-downloaded', info =>
      publish({ status: 'downloaded', version: info?.version ?? null, percent: 100, error: null })
    )
    updater.on('update-not-available', () =>
      publish({ status: 'idle', version: null, percent: null, error: null, checkedAt: Date.now() })
    )
    updater.on('error', error =>
      publish({ status: 'error', error: messageOf(error), checkedAt: Date.now() })
    )
  }

  /** Check now (the timer, or the button in About). Never two at once. */
  async function check() {
    if (installing) return snapshot()
    if (['checking', 'available', 'downloading', 'downloaded'].includes(state.status)) {
      return snapshot()
    }
    publish({ status: 'checking', error: null })
    try {
      await updater.checkForUpdates()
    } catch (error) {
      // A check that throws before the first event (offline, no app-update.yml) still has to end.
      publish({ status: 'error', error: messageOf(error), checkedAt: Date.now() })
    }
    return snapshot()
  }

  /**
   * Stop the children, then hand the app to the installer.
   *
   * `quitAndInstall` spawns the installer and *then* quits; without the stop, the installer races
   * the engine's file handles and the update silently leaves the old version in place.
   */
  async function install() {
    if (state.status !== 'downloaded') {
      return { ok: false, error: 'No update is ready to install.' }
    }
    if (installing) return { ok: false, error: 'The update is already installing.' }

    installing = true
    trace('updates: stopping the engine and server before install')
    try {
      await stopChildren()
    } catch (error) {
      installing = false
      const message = `Could not stop the engine before installing: ${messageOf(error)}`
      publish({ status: 'error', error: message })
      return { ok: false, error: message }
    }

    try {
      trace('updates: quitAndInstall (silent, relaunch after)')
      updater.quitAndInstall(true, true)
      return { ok: true }
    } catch (error) {
      installing = false
      publish({ status: 'error', error: messageOf(error) })
      return { ok: false, error: messageOf(error) }
    }
  }

  function start({ defer = true } = {}) {
    if (started) return snapshot()
    started = true
    attach()

    if (defer) {
      first = setTimeoutFn(() => {
        first = null
        void check()
      }, firstDelayMs)
      if (typeof first?.unref === 'function') first.unref()
    } else {
      void check()
    }

    interval = setIntervalFn(() => void check(), intervalMs)
    if (typeof interval?.unref === 'function') interval.unref()
    return snapshot()
  }

  function dispose() {
    if (first) {
      clearTimeoutFn(first)
      first = null
    }
    if (interval) {
      clearIntervalFn(interval)
      interval = null
    }
    started = false
  }

  return { start, check, install, dispose, snapshot }
}
