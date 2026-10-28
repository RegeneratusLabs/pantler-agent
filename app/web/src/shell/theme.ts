/**
 * Theme — dark by default, daylight on request.
 *
 * One attribute on <html>, because every colour is a CSS variable consumed through
 * `@theme inline` in styles.css. The initial value is applied before React mounts (see
 * main.tsx) so there is no flash of the wrong theme.
 */

export type Theme = 'dark' | 'light'

const THEME_KEY = 'pantler.theme'

export function loadTheme(): Theme {
  try {
    const stored = localStorage.getItem(THEME_KEY)
    if (stored === 'light' || stored === 'dark') return stored
  } catch {
    // Storage denied: fall through to the default.
  }
  return 'dark'
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme
}

export function saveTheme(theme: Theme): void {
  try {
    localStorage.setItem(THEME_KEY, theme)
  } catch {
    // Not worth a banner; the theme simply will not persist.
  }
}
