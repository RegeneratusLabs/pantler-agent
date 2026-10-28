/**
 * THE single source of truth for every name-shaped value (the design notes §8).
 *
 * `pantler` is the product name. Every identifier that would be expensive to change
 * *after a release* — app id, bundle id, userData directory, update-feed channel,
 * deep-link scheme — is still an obvious placeholder rather than the product name, on
 * purpose (the design notes §8). A display name can change any day; an app id cannot change
 * without orphaning user data and breaking updates.
 *
 * This mirrors the pattern of the `product-identity.cjs` we are porting from the Hermes
 * desktop: one module owns the names, everything else derives from it. A future rename
 * is therefore one file plus prose.
 *
 * Nothing here is used by the web bundle at build time except `displayName` — the rest
 * is the contract the Electron shell will consume in Phase 1.
 */

/** True while every identifier below is a placeholder. A release build must refuse this. */
export const PLACEHOLDER = true

export const identity = Object.freeze({
  /** Human-facing. Safe to change at any time. */
  displayName: 'pantler',
  shortName: 'pantler',
  description: 'The business side of a small food producer, run conversationally.',

  /** Expensive to change after release — deliberately a placeholder, not the product name. */
  appId: 'app.placeholder.pantler',
  bundleId: 'app.placeholder.pantler',
  userDataDir: 'pantler-placeholder',
  deepLinkScheme: 'pantler-placeholder',
  updateFeedChannel: 'placeholder',

  /** Artifact + package names. */
  artifactName: 'pantler-placeholder',
  pythonDist: 'pantler-core',
  /**
   * The environment prefix — **not** the source of it. Twenty-one `PANTLER_*` names are spelled
   * where they are read (`plugins/`, `app/`, `scripts/`), and nothing derives them from this
   * value, so changing it here changes nothing. It is here because the Electron shell will need
   * one; making it real is a repository-wide change
   * (the internal audit IDN-2).
   */
  envPrefix: 'PANTLER_'
})

export default identity
