import { TAB_CHAT, TAB_DASHBOARD, TAB_QUERY_PARAM } from './constants';

const routeListeners = new Set<() => void>();

export function getTabFromUrl(url = new URL(window.location.href)) {
  const tab = url.searchParams.get(TAB_QUERY_PARAM);
  return tab === TAB_CHAT ? TAB_CHAT : TAB_DASHBOARD;
}

function notifyRouteChange() {
  for (const listener of routeListeners) listener();
}

export function navigateToTab(tab: string, search = window.location.search) {
  const url = new URL(window.location.href);
  url.pathname = '/ui';
  url.search = search.startsWith('?') ? search : search ? `?${search}` : '';
  url.searchParams.set(TAB_QUERY_PARAM, tab);
  window.history.pushState({ tab }, '', url);
  notifyRouteChange();
}

export function navigateToSearch(search: string) {
  const url = new URL(window.location.href);
  url.pathname = '/ui';
  url.search = search.startsWith('?') ? search : `?${search}`;
  if (!url.searchParams.has(TAB_QUERY_PARAM)) {
    url.searchParams.set(TAB_QUERY_PARAM, TAB_DASHBOARD);
  }
  window.history.pushState({}, '', url);
  notifyRouteChange();
}

export function subscribeToRouteChanges(listener: () => void) {
  routeListeners.add(listener);
  window.addEventListener('popstate', listener);
  return () => {
    routeListeners.delete(listener);
    window.removeEventListener('popstate', listener);
  };
}

export function buildDashboardSearch(
  filters: { dateBucket: string; sortKey?: string; sortDir?: string },
  overrides: { dateBucket?: string; sortKey?: string; sortDir?: string } = {},
) {
  const dateBucket = overrides.dateBucket ?? filters.dateBucket;
  const sortKey = overrides.sortKey ?? filters.sortKey ?? 'totalTokens';
  const sortDir = overrides.sortDir ?? filters.sortDir ?? 'desc';
  const params = new URLSearchParams();
  params.set(TAB_QUERY_PARAM, TAB_DASHBOARD);
  if (dateBucket !== 'all_time') params.set('range', dateBucket);
  if (sortKey !== 'totalTokens') params.set('sort', sortKey);
  if (sortDir !== 'desc') params.set('dir', sortDir);
  return `?${params.toString()}`;
}
