/**
 * THE single source of truth for every name-shaped value (the design notes §8).
 *
 * `pantler` is the product name. The identifiers below were **decided on 2026-11-01**, before the
 * first installer, because an app id, user-data directory, deep-link scheme or update-feed channel
 * cannot change after a release without orphaning user data and breaking updates. The display name
 * can still change any day; these cannot.
 *
 * This mirrors the pattern of the `product-identity.cjs` we are porting from the Hermes desktop:
 * one module owns the names, everything else derives from it.
 *
 * The web bundle reads `displayName` at build time; the rest is the contract the Electron shell
 * consumes (`app/desktop`).
 */

/** Kept for the build guard and `scripts/identity-check.mjs`: no value below is a placeholder. */
export const PLACEHOLDER = false

export const identity = Object.freeze({
  /** Human-facing. Safe to change at any time. */
  displayName: 'pantler',
  shortName: 'pantler',
  description: 'The business side of a small food producer, run conversationally.',

  /** Decided 2026-11-01 — expensive to change after release. */
  appId: 'app.pantler.desktop',
  bundleId: 'app.pantler.desktop',
  userDataDir: 'pantler',
  deepLinkScheme: 'pantler',
  updateFeedChannel: 'stable',

  /** Artifact + package names. */
  artifactName: 'Pantler-Setup',
  pythonDist: 'pantler-core',
  /**
   * The environment prefix — **not** the source of it. Twenty-one `PANTLER_*` names are spelled
   * where they are read (`plugins/`, `app/`, `scripts/`), and nothing derives them from this
   * value, so changing it here changes nothing. It is here because the Electron shell needs one;
   * making it real is a repository-wide change
   * (the internal audit IDN-2).
   */
  envPrefix: 'PANTLER_'
})

export default identity
