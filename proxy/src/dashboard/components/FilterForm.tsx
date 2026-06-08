/** @jsxImportSource hono/jsx */
import type { FC } from 'hono/jsx';
import {
  COST_RATES_PATH,
  DASHBOARD_PATH,
  DEFAULT_INPUT_COST_PER_MILLION,
  DEFAULT_OUTPUT_COST_PER_MILLION,
} from '../constants';
import type { SavedCostRates } from '../db/cost-rates';
import { DATE_BUCKETS } from '../lib/date-range';
import { formatUsd } from '../lib/format';
import { buildDashboardUrl } from '../lib/query-params';
import type { DashboardFilters } from '../types';
import { ModelCostTable } from './ModelCostTable';

export const DASHBOARD_FORM_ID = 'dashboard-form';

function savedRatesLabel(savedCostRates: SavedCostRates | null): string {
  if (!savedCostRates?.updatedAt) {
    return `Using built-in defaults: $${DEFAULT_INPUT_COST_PER_MILLION.toFixed(2)} input / $${DEFAULT_OUTPUT_COST_PER_MILLION.toFixed(2)} output per 1M tokens.`;
  }

  const { inputPerMillion, outputPerMillion } = savedCostRates.defaultRates;
  const updated = new Date(savedCostRates.updatedAt).toLocaleString();
  return `Saved rates: $${inputPerMillion.toFixed(2)} input / $${outputPerMillion.toFixed(2)} output per 1M tokens (updated ${updated}).`;
}

export const FilterForm: FC<{
  filters: DashboardFilters;
  models: string[];
  savedCostRates: SavedCostRates | null;
}> = ({ filters, models, savedCostRates }) => (
  <div class="card">
    <h2>Filters &amp; cost rates</h2>
    <p class="card-subtitle">
      Est. cost = (prompt tokens × input $/1M + completion tokens × output $/1M) ÷ 1,000,000. Local
      inference is assumed free.
    </p>
    <p class="muted" id="cost-rates-source">
      {savedRatesLabel(savedCostRates)}
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
        <div class="cost-input-grid">
          <div class="input-field">
            <span class="input-field-label">Input</span>
            <div class="input-shell">
              <span class="input-prefix">$</span>
              <input
                type="number"
                class="number-input"
                name="input_cost"
                value={filters.defaultRates.inputPerMillion}
                min={0}
                step={0.01}
                required
              />
            </div>
          </div>
          <div class="input-field">
            <span class="input-field-label">Output</span>
            <div class="input-shell">
              <span class="input-prefix">$</span>
              <input
                type="number"
                class="number-input"
                name="output_cost"
                value={filters.defaultRates.outputPerMillion}
                min={0}
                step={0.01}
                required
              />
            </div>
          </div>
        </div>
        <p class="muted">
          Built-in defaults: {formatUsd(DEFAULT_INPUT_COST_PER_MILLION)} / 1M input,{' '}
          {formatUsd(DEFAULT_OUTPUT_COST_PER_MILLION)} / 1M output.
        </p>
      </fieldset>

      <fieldset>
        <legend>Per-model rate overrides</legend>
        <ModelCostTable models={models} filters={filters} />
      </fieldset>

      <div class="form-actions">
        <button type="button" id="save-cost-rates" class="btn-primary">
          Save rates
        </button>
        <p class="muted form-action-hint">
          Save persists rates to the database for all clients. Refresh applies unsaved edits for
          this session only.
        </p>
        <p id="cost-rates-status" class="cost-rates-status" role="status" aria-live="polite" />
      </div>
    </form>

    <script
      dangerouslySetInnerHTML={{
        __html: `
(function () {
  const form = document.getElementById(${JSON.stringify(DASHBOARD_FORM_ID)});
  const saveBtn = document.getElementById('save-cost-rates');
  const status = document.getElementById('cost-rates-status');
  if (!form || !saveBtn || !status) return;

  saveBtn.addEventListener('click', async () => {
    status.textContent = 'Saving…';
    status.className = 'cost-rates-status';

    const formData = new FormData(form);
    const defaultRates = {
      inputPerMillion: Number(formData.get('input_cost')),
      outputPerMillion: Number(formData.get('output_cost')),
    };
    const modelCosts = {};
    for (const [key, value] of formData.entries()) {
      const inputMatch = key.match(/^input_cost\\[(.+)\\]$/);
      if (inputMatch) {
        const model = inputMatch[1];
        modelCosts[model] = modelCosts[model] || {};
        modelCosts[model].inputPerMillion = Number(value);
        continue;
      }
      const outputMatch = key.match(/^output_cost\\[(.+)\\]$/);
      if (outputMatch) {
        const model = outputMatch[1];
        modelCosts[model] = modelCosts[model] || {};
        modelCosts[model].outputPerMillion = Number(value);
      }
    }

    try {
      const response = await fetch(${JSON.stringify(COST_RATES_PATH)}, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ defaultRates, modelCosts }),
      });
      if (!response.ok) {
        throw new Error('Save failed');
      }
      window.location.assign(${JSON.stringify(DASHBOARD_PATH)} + '?saved=1');
    } catch {
      status.textContent = 'Failed to save cost rates. Check database connectivity.';
      status.className = 'cost-rates-status error';
    }
  });
})();
`,
      }}
    />
  </div>
);
