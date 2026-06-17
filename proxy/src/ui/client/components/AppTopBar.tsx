import { Button, Spinner } from '@heroui/react';
import { TAB_CHAT, TAB_DASHBOARD } from '../lib/constants';
import { ClearIcon, RefreshIcon } from './Icons';
import { TabBar } from './TabBar';

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
    <header className="app-top-bar sticky top-0 z-50 border-b border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="mx-auto grid max-w-7xl min-w-0 grid-cols-[1fr_auto_1fr] items-center gap-1.5 px-3 py-2 sm:gap-2 sm:px-4 md:gap-3 md:px-6 md:py-2.5">
        <h1 className="app-top-bar-title shrink-0 justify-self-start text-sm font-bold tracking-tight sm:text-base md:text-lg">
          LLM Proxy
        </h1>
        <TabBar activeTab={activeTab} />
        <div className="justify-self-end">
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
