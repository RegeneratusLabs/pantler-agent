/**
 * Types for the identity module. Kept beside the implementation so the web bundle and
 * (from Phase 1) the Electron shell share one contract.
 */

export interface Identity {
  displayName: string
  shortName: string
  description: string
  appId: string
  bundleId: string
  userDataDir: string
  deepLinkScheme: string
  updateFeedChannel: string
  artifactName: string
  pythonDist: string
  envPrefix: string
}

export declare const PLACEHOLDER: boolean
export declare const identity: Readonly<Identity>
declare const _default: Readonly<Identity>
export default _default
