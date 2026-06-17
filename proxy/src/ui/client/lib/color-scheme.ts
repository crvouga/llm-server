export type ThemeMode = 'light' | 'dark' | 'system';

export const THEME_STORAGE_KEY = 'llm-proxy-theme';

const DARK_MEDIA = '(prefers-color-scheme: dark)';

export function getStoredThemeMode(): ThemeMode {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === 'light' || stored === 'dark' || stored === 'system') {
      return stored;
    }
  } catch {
    // localStorage may be unavailable
  }
  return 'system';
}

export function resolveIsDark(mode: ThemeMode): boolean {
  if (mode === 'dark') return true;
  if (mode === 'light') return false;
  return window.matchMedia(DARK_MEDIA).matches;
}

export function applyThemeMode(mode: ThemeMode) {
  const isDark = resolveIsDark(mode);
  const root = document.documentElement;
  root.classList.toggle('dark', isDark);
  root.dataset.theme = isDark ? 'dark' : 'light';
  root.dataset.themeMode = mode;
}

export function setThemeMode(mode: ThemeMode) {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, mode);
  } catch {
    // localStorage may be unavailable
  }
  applyThemeMode(mode);
}

export function initColorScheme() {
  applyThemeMode(getStoredThemeMode());

  const media = window.matchMedia(DARK_MEDIA);
  const onSystemChange = () => {
    if (getStoredThemeMode() === 'system') {
      applyThemeMode('system');
    }
  };
  media.addEventListener('change', onSystemChange);
}
