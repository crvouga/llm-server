import type { DashboardPayload } from '../../dashboard/types';
import type { TabParam } from '../../shared/types';

export interface UiClientData {
  tab: TabParam;
  dashboard: DashboardPayload | null;
}
