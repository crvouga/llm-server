/** @jsxImportSource hono/jsx */
import type { FC } from 'hono/jsx';
import { formatDateRangeLabel } from '../lib/date-range';
import type { DashboardFilters, UsageSummary } from '../types';
import { formatInt, formatUsd } from '../lib/format';

export const SummaryCards: FC<{
  summary: UsageSummary;
  filters: DashboardFilters;
}> = ({ summary, filters }) => (
  <>
    <div class="summary-grid">
      <div class="stat-card stat-card-hero">
        <div class="stat-label">Est. cloud cost</div>
        <div class="stat-value">{formatUsd(summary.totals.estCostUsd)}</div>
        <div class="stat-detail">
          What this proxy would have cost on cloud — local inference assumed free
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Total requests</div>
        <div class="stat-value">{formatInt(summary.totals.requestCount)}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Total tokens</div>
        <div class="stat-value">{formatInt(summary.totals.totalTokens)}</div>
        <div class="stat-detail">
          {formatInt(summary.totals.promptTokens)} prompt ·{' '}
          {formatInt(summary.totals.completionTokens)} completion
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Models queried</div>
        <div class="stat-value">{formatInt(summary.totals.modelCount)}</div>
      </div>
    </div>
    <div class="summary-meta">
      <span class="range-badge">{formatDateRangeLabel(filters)}</span>
    </div>
  </>
);
