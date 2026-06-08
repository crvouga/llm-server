/** @jsxImportSource hono/jsx */
import { NeonDbError } from '@neondatabase/serverless';
import { Hono } from 'hono';
import { DashboardPage } from './components/DashboardPage';
import { DASHBOARD_PATH, LEGACY_DASHBOARD_PATH } from './constants';
import { loadDashboardData } from './db/load';
import { fetchEarliestUsageDate, fetchKnownModels } from './db/queries';
import { emptyFilters } from './lib/filters';
import { parseFiltersFromQuery } from './lib/query-params';
import type { DashboardEnv, DashboardFilters } from './types';

async function renderDashboard(databaseUrl: string, filters: DashboardFilters, models: string[]) {
  const { summary, dailyRows } = await loadDashboardData(databaseUrl, filters);
  return (
    <DashboardPage filters={filters} models={models} summary={summary} dailyRows={dailyRows} />
  );
}

async function fallbackFilters(databaseUrl: string): Promise<DashboardFilters> {
  try {
    const earliestDate = await fetchEarliestUsageDate(databaseUrl);
    const models = await fetchKnownModels(databaseUrl);
    return parseFiltersFromQuery({}, earliestDate, models);
  } catch {
    return emptyFilters();
  }
}

export const dashboardRoute = new Hono<DashboardEnv>();

dashboardRoute.get(LEGACY_DASHBOARD_PATH, (c) => c.redirect(DASHBOARD_PATH, 301));

dashboardRoute.get(DASHBOARD_PATH, async (c) => {
  if (!c.env.DATABASE_URL) {
    return c.text('DATABASE_URL not configured', 503);
  }

  try {
    const databaseUrl = c.env.DATABASE_URL;
    const [models, earliestDate] = await Promise.all([
      fetchKnownModels(databaseUrl),
      fetchEarliestUsageDate(databaseUrl),
    ]);
    const filters = parseFiltersFromQuery(c.req.query(), earliestDate, models);
    return c.html(await renderDashboard(databaseUrl, filters, models));
  } catch (error) {
    const code = error instanceof NeonDbError ? error.code : 'unknown';
    console.error(`Dashboard failed (code: ${code ?? 'unknown'})`);

    return c.html(
      <DashboardPage
        filters={await fallbackFilters(c.env.DATABASE_URL)}
        models={[]}
        summary={null}
        dailyRows={[]}
        errorMessage="Failed to load dashboard data. Check database connectivity."
      />,
      500,
    );
  }
});
