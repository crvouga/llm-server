/** @jsxImportSource hono/jsx/dom */
import type { TabParam } from '../../shared/types';
import { TAB_DASHBOARD } from '../../shared/constants';
import { Spinner } from './Spinner';
import { TabBar } from './TabBar';

const REFRESH_ICON = (
  <svg
    class="btn-refresh-icon"
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path d="M21 12a9 9 0 1 1-2.64-6.36" />
    <path d="M21 3v6h-6" />
  </svg>
);

export function AppTopBar({
  activeTab,
  onRefresh,
  refreshing = false,
}: {
  activeTab: TabParam;
  onRefresh?: () => void;
  refreshing?: boolean;
}) {
  return (
    <header class="top-bar">
      <div class="top-bar-inner">
        <h1 class="top-bar-title">LLM Proxy</h1>
        <TabBar activeTab={activeTab} />
        {activeTab === TAB_DASHBOARD && onRefresh ? (
          <button
            type="button"
            class="btn-refresh btn-with-spinner"
            disabled={refreshing}
            aria-busy={refreshing}
            onClick={onRefresh}
          >
            {refreshing ? <Spinner size="sm" /> : REFRESH_ICON}
            {refreshing ? 'Refreshing…' : 'Refresh'}
          </button>
        ) : (
          <span class="top-bar-spacer" aria-hidden="true" />
        )}
      </div>
    </header>
  );
}
