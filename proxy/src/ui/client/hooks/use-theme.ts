import { useCallback, useState } from 'react';
import { getStoredThemeMode, setThemeMode, type ThemeMode } from '../lib/color-scheme';

export function useTheme() {
  const [mode, setMode] = useState<ThemeMode>(() => getStoredThemeMode());

  const setTheme = useCallback((next: ThemeMode) => {
    setThemeMode(next);
    setMode(next);
  }, []);

  return { mode, setTheme };
}
