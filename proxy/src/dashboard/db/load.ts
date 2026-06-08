import type { DashboardFilters, DailyUsageRow, UsageSummary } from '../types';
import { summarizeUsage } from '../lib/summary';
import { fetchDailyUsageRows, fetchUsageRows } from './queries';

export async function loadDashboardData(
  databaseUrl: string,
  filters: DashboardFilters,
): Promise<{ summary: UsageSummary; dailyRows: DailyUsageRow[] }> {
  const [rawRows, dailyRows] = await Promise.all([
    fetchUsageRows(databaseUrl, filters.startDate, filters.endDate),
    fetchDailyUsageRows(databaseUrl, filters.startDate, filters.endDate),
  ]);
  const summary = summarizeUsage(rawRows, filters);
  return { summary, dailyRows };
}
