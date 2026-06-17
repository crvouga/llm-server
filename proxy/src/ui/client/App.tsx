import { useCallback, useRef } from 'react';
import { TAB_CHAT, TAB_DASHBOARD } from './lib/constants';
import { useDashboardQuery } from './hooks/queries';
import { useTab } from './hooks/use-tab';
import { useUrlSearch } from './hooks/use-url-search';
import { AppTopBar } from './components/AppTopBar';
import { ChatView } from './components/ChatView';
import { applyDashboardFormToUrl } from './components/FilterForm';
import { DashboardView } from './components/DashboardView';
import { ErrorBoundary } from './components/ErrorBoundary';

export function App() {
  const tab = useTab();
  const search = useUrlSearch();
  const { isFetching: dashboardFetching } = useDashboardQuery(search, tab === TAB_DASHBOARD);
  const clearChatRef = useRef<(() => void) | null>(null);

  const refreshDashboard = useCallback(() => {
    applyDashboardFormToUrl();
  }, []);

  return (
    <div
      className={`flex min-h-screen w-full max-w-full flex-col ${tab === TAB_CHAT ? 'h-screen overflow-hidden' : 'min-w-0'}`}
    >
      <AppTopBar
        activeTab={tab}
        refreshing={dashboardFetching}
        onRefresh={tab === TAB_DASHBOARD ? refreshDashboard : undefined}
        onClearChat={tab === TAB_CHAT ? () => clearChatRef.current?.() : undefined}
      />
      <main className="flex min-h-0 flex-1 flex-col">
        {tab === TAB_DASHBOARD ? (
          <ErrorBoundary>
            <DashboardView search={search} />
          </ErrorBoundary>
        ) : (
          <ErrorBoundary>
            <ChatView
              onRegisterClear={(clear) => {
                clearChatRef.current = clear;
              }}
            />
          </ErrorBoundary>
        )}
      </main>
    </div>
  );
}
