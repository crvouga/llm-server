import { TAB_CHAT, TAB_DASHBOARD, TAB_QUERY_PARAM, UI_PATH } from '../../shared/constants';
import type { TabParam } from '../../shared/types';

export function getTabFromUrl(url: URL = new URL(window.location.href)): TabParam {
  const tab = url.searchParams.get(TAB_QUERY_PARAM);
  return tab === TAB_CHAT ? TAB_CHAT : TAB_DASHBOARD;
}

export function navigateToTab(tab: TabParam, search = window.location.search): void {
  const url = new URL(window.location.href);
  url.pathname = UI_PATH;
  url.search = search.startsWith('?') ? search : search ? `?${search}` : '';
  url.searchParams.set(TAB_QUERY_PARAM, tab);
  window.history.pushState({ tab }, '', url);
  window.dispatchEvent(new PopStateEvent('popstate'));
}

export function navigateToSearch(search: string): void {
  const url = new URL(window.location.href);
  url.pathname = UI_PATH;
  url.search = search.startsWith('?') ? search : `?${search}`;
  if (!url.searchParams.has(TAB_QUERY_PARAM)) {
    url.searchParams.set(TAB_QUERY_PARAM, TAB_DASHBOARD);
  }
  window.history.pushState({}, '', url);
  window.dispatchEvent(new PopStateEvent('popstate'));
}

export function subscribeToRouteChanges(listener: () => void): () => void {
  window.addEventListener('popstate', listener);
  return () => window.removeEventListener('popstate', listener);
}
