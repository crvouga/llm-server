/** @jsxImportSource hono/jsx */
import type { FC } from 'hono/jsx';
import { CLIENT_SCRIPT_PATH } from '../constants';
import { buildClientPayload } from '../lib/summary';
import { dashboardStyles } from '../styles';
import type { DailyUsageRow, DashboardFilters, UsageSummary } from '../types';
import { AppTopBar } from './AppTopBar';
import { DASHBOARD_FORM_ID, FilterForm } from './FilterForm';
import { SummaryCards } from './SummaryCards';

export const DashboardPage: FC<{
  filters: DashboardFilters;
  models: string[];
  summary: UsageSummary | null;
  dailyRows: DailyUsageRow[];
  errorMessage?: string;
}> = ({ filters, models, summary, dailyRows, errorMessage }) => {
  const hasData = summary !== null && summary.rows.length > 0;
  const scriptData =
    hasData && summary ? JSON.stringify(buildClientPayload(summary, dailyRows, filters)) : null;

  return (
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>LLM Proxy Dashboard</title>
        <style>{dashboardStyles}</style>
      </head>
      <body>
        <AppTopBar formId={DASHBOARD_FORM_ID} />
        <div class="page">
          {errorMessage ? <p class="error">{errorMessage}</p> : null}

          <FilterForm filters={filters} models={models} />

          {summary === null ? null : (
            <>
              <SummaryCards summary={summary} filters={filters} />
              {hasData ? (
                <div id="dashboard-client" />
              ) : (
                <p class="muted">No chat completion usage found for this date range.</p>
              )}
            </>
          )}
        </div>

        {scriptData ? (
          <>
            <script
              dangerouslySetInnerHTML={{
                __html: `window.__DASHBOARD_DATA__=${scriptData};`,
              }}
            />
            <script type="module" src={CLIENT_SCRIPT_PATH} />
          </>
        ) : null}
      </body>
    </html>
  );
};
