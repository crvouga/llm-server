import { TAB_CHAT, TAB_DASHBOARD, TAB_QUERY_PARAM } from './constants';
import type { TabParam } from './types';

export function parseTabFromQuery(
  query: Record<string, string | string[] | undefined>,
): TabParam {
  const raw = query[TAB_QUERY_PARAM];
  const value = Array.isArray(raw) ? raw[0] : raw;
  return value === TAB_CHAT ? TAB_CHAT : TAB_DASHBOARD;
}
