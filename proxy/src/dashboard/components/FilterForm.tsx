/** @jsxImportSource hono/jsx */
import type { FC } from 'hono/jsx';
import { DASHBOARD_PATH } from '../constants';
import { DATE_BUCKETS } from '../lib/date-range';
import { buildDashboardUrl } from '../lib/query-params';
import type { DashboardFilters } from '../types';
import { ModelCostTable } from './ModelCostTable';

export const DASHBOARD_FORM_ID = 'dashboard-form';

export const FilterForm: FC<{ filters: DashboardFilters; models: string[] }> = ({
  filters,
  models,
}) => (
  <div class="card">
    <h2>Filters &amp; cost rates</h2>
    <p class="card-subtitle">
      Est. cost = (prompt tokens × input $/1M + completion tokens × output $/1M) ÷ 1,000,000. Local
      inference is assumed free.
    </p>
    <form id={DASHBOARD_FORM_ID} method="get" action={DASHBOARD_PATH}>
      <input type="hidden" name="range" value={filters.dateBucket} />
      {filters.sortKey !== 'totalTokens' ? (
        <input type="hidden" name="sort" value={filters.sortKey} />
      ) : null}
      {filters.sortDir !== 'desc' ? (
        <input type="hidden" name="dir" value={filters.sortDir} />
      ) : null}

      <fieldset>
        <legend>Date range</legend>
        <div class="date-buckets">
          {DATE_BUCKETS.map((bucket) => (
            <a
              href={buildDashboardUrl(filters, { dateBucket: bucket.id })}
              class={`date-bucket${filters.dateBucket === bucket.id ? ' active' : ''}`}
            >
              {bucket.label}
            </a>
          ))}
        </div>
      </fieldset>

      <fieldset>
        <legend>Default cloud rates (USD per 1M tokens)</legend>
        <div class="form-row">
          <label>
            Input
            <input
              type="number"
              name="input_cost"
              value={filters.defaultRates.inputPerMillion}
              min={0}
              step={0.01}
              required
            />
          </label>
          <label>
            Output
            <input
              type="number"
              name="output_cost"
              value={filters.defaultRates.outputPerMillion}
              min={0}
              step={0.01}
              required
            />
          </label>
        </div>
        <p class="muted">Defaults: $1.00 / 1M input, $2.00 / 1M output.</p>
      </fieldset>

      <fieldset>
        <legend>Per-model rate overrides</legend>
        <ModelCostTable models={models} filters={filters} />
      </fieldset>
    </form>
  </div>
);
