/** @jsxImportSource hono/jsx/dom */
import { useEffect, useRef, useState } from 'hono/jsx';
import { ChatClient } from '../../chat/client/ChatClient';
import { TAB_DASHBOARD } from '../../shared/constants';
import type { TabParam } from '../../shared/types';
import { AppTopBar } from './AppTopBar';
import { DashboardView } from './DashboardView';
import { getTabFromUrl, subscribeToRouteChanges } from './routing';

export function Router() {
  const [tab, setTab] = useState<TabParam>(getTabFromUrl);
  const [dashboardLoading, setDashboardLoading] = useState(false);
  const refreshDashboardRef = useRef<(() => void) | null>(null);

  useEffect(() => subscribeToRouteChanges(() => setTab(getTabFromUrl())), []);

  return (
    <>
      <AppTopBar
        activeTab={tab}
        refreshing={dashboardLoading}
        onRefresh={
          tab === TAB_DASHBOARD
            ? () => {
                refreshDashboardRef.current?.();
              }
            : undefined
        }
      />
      {tab === TAB_DASHBOARD ? (
        <DashboardView
          onLoadingChange={setDashboardLoading}
          onReady={(api) => {
            refreshDashboardRef.current = api.refresh;
          }}
        />
      ) : (
        <ChatClient />
      )}
    </>
  );
}
