/**
 * The renderer's only door to the host.
 *
 * Deliberately almost empty: the renderer talks to the BFF over HTTP like the browser build does,
 * and the host owns only things a page cannot have — nothing here grants disk access or secrets.
 * When it does, it is one method at a time through this bridge, never `nodeIntegration`.
 *
 * `restartEngine` exists for one reason: a saved model key lands in the profile's `.env`, and the
 * engine reads that file when the gateway starts. Without this the operator would have to quit and
 * reopen the app after connecting a provider.
 */

import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld(
  'pantler',
  Object.freeze({
    platform: process.platform,
    versions: Object.freeze({
      electron: process.versions.electron,
      chrome: process.versions.chrome,
      node: process.versions.node
    }),
    restartEngine: () => ipcRenderer.invoke('pantler:restart-engine'),
    updates: {
      state: () => ipcRenderer.invoke('pantler:update-state'),
      check: () => ipcRenderer.invoke('pantler:update-check'),
      install: () => ipcRenderer.invoke('pantler:update-install'),
      /** Follow the host's state; returns the unsubscribe for an effect cleanup. */
      subscribe: listener => {
        const handler = (_event, state) => listener(state)
        ipcRenderer.on('pantler:update-state', handler)
        return () => ipcRenderer.removeListener('pantler:update-state', handler)
      }
    }
  })
)
