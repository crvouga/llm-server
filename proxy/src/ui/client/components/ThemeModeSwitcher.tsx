import { useEffect, useRef, useState } from 'react';
import { Button } from '@heroui/react';
import { TOP_BAR_ACTION_CLASS } from '../lib/constants';
import type { ThemeMode } from '../lib/color-scheme';
import { useTheme } from '../hooks/use-theme';
import { MonitorIcon, MoonIcon, SunIcon } from './Icons';

const THEME_OPTIONS: { mode: ThemeMode; label: string; Icon: typeof SunIcon }[] = [
  { mode: 'light', label: 'Light', Icon: SunIcon },
  { mode: 'dark', label: 'Dark', Icon: MoonIcon },
  { mode: 'system', label: 'System', Icon: MonitorIcon },
];

export function ThemeModeSwitcher() {
  const { mode, setTheme } = useTheme();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;

    const onPointerDown = (event: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };

    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [open]);

  const current =
    THEME_OPTIONS.find((option) => option.mode === mode) ?? THEME_OPTIONS[2];
  const CurrentIcon = current.Icon;

  return (
    <div ref={rootRef} className="relative">
      <Button
        variant="secondary"
        size="sm"
        className={TOP_BAR_ACTION_CLASS}
        aria-label={`Theme: ${current.label}. Change theme`}
        aria-expanded={open}
        aria-haspopup="menu"
        onPress={() => setOpen((value) => !value)}
      >
        <CurrentIcon className="h-4 w-4" />
        <span className="hidden md:inline">{current.label}</span>
      </Button>
      {open ? (
        <div
          role="menu"
          className="absolute right-0 top-full z-50 mt-1 min-w-34 rounded-lg border border-slate-200 bg-surface py-1 shadow-lg dark:border-slate-700"
        >
          {THEME_OPTIONS.map(({ mode: optionMode, label, Icon }) => (
            <button
              key={optionMode}
              type="button"
              role="menuitemradio"
              aria-checked={mode === optionMode}
              className={`flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition hover:bg-slate-100 dark:hover:bg-slate-800 ${
                mode === optionMode
                  ? 'font-semibold text-blue-600 dark:text-blue-400'
                  : 'text-foreground'
              }`}
              onClick={() => {
                setTheme(optionMode);
                setOpen(false);
              }}
            >
              <Icon className="h-4 w-4" />
              {label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
