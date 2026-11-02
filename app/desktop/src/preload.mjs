/**
 * The renderer's only door to the host.
 *
 * Deliberately almost empty: the renderer talks to the BFF over HTTP like the browser build does,
 * and the host owns only things a page cannot have — nothing here grants disk access or secrets
 * yet. When it does, it is one method at a time through this bridge, never `nodeIntegration`.
 */

import { contextBridge } from 'electron'

contextBridge.exposeInMainWorld(
  'pantler',
  Object.freeze({
    platform: process.platform,
    versions: Object.freeze({
      electron: process.versions.electron,
      chrome: process.versions.chrome,
      node: process.versions.node
    })
  })
)
