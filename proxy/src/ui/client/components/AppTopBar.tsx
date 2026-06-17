import { Button, Spinner } from '@heroui/react';
import { TAB_CHAT, TAB_DASHBOARD } from '../lib/constants';
import { PAGE_CONTENT_CLASS, PAGE_PADDING_CLASS } from '../lib/layout';
import { ClearIcon, RefreshIcon } from './Icons';
import { TabBar } from './TabBar';
import { ThemeModeSwitcher } from './ThemeModeSwitcher';

interface AppTopBarProps {
  activeTab: string;
  onRefresh?: () => void;
  refreshing?: boolean;
  onClearChat?: () => void;
}

export function AppTopBar({
  activeTab,
  onRefresh,
  refreshing,
  onClearChat,
}: AppTopBarProps) {
  const refreshLabel = refreshing ? 'Refreshing dashboard' : 'Refresh dashboard';
  const clearLabel = 'Clear chat';

  return (
    <header className="app-top-bar sticky top-0 z-50 border-b border-separator bg-surface shadow-sm">
      <div className={`${PAGE_CONTENT_CLASS} ${PAGE_PADDING_CLASS} grid min-w-0 grid-cols-[1fr_auto_1fr] items-center gap-1.5 py-2 sm:gap-2 md:gap-3 md:py-2.5`}>
        <h1 className="app-top-bar-title shrink-0 justify-self-start text-sm font-bold tracking-tight sm:text-base md:text-lg">
          LLM Proxy
        </h1>
        <TabBar activeTab={activeTab} />
        <div className="flex items-center justify-end gap-1 sm:gap-1.5">
          <ThemeModeSwitcher />
          {activeTab === TAB_DASHBOARD && onRefresh ? (
            <Button
              variant="secondary"
              size="sm"
              className="app-top-bar-action"
              isDisabled={refreshing}
              onPress={onRefresh}
              aria-label={refreshLabel}
            >
              {refreshing ? <Spinner size="sm" /> : <RefreshIcon className="h-4 w-4 md:hidden" />}
              <span className="hidden md:inline">{refreshing ? 'Refreshing…' : 'Refresh'}</span>
            </Button>
          ) : activeTab === TAB_CHAT && onClearChat ? (
            <Button
              variant="secondary"
              size="sm"
              className="app-top-bar-action"
              onPress={onClearChat}
              aria-label={clearLabel}
            >
              <ClearIcon className="h-4 w-4 md:hidden" />
              <span className="hidden md:inline">Clear chat</span>
            </Button>
          ) : null}
        </div>
      </div>
    </header>
  );
}
