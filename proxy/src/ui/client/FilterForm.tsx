/** @jsxImportSource hono/jsx/dom */
import { useState } from 'hono/jsx';
import {
  DEFAULT_INPUT_COST_PER_MILLION,
  DEFAULT_OUTPUT_COST_PER_MILLION,
} from '../../dashboard/constants';
import { DATE_BUCKETS } from '../../dashboard/lib/date-range';
import { formatUsd } from '../../dashboard/lib/format';
import { buildDashboardUrl } from '../../dashboard/lib/query-params';
import type { DashboardFilters } from '../../dashboard/types';
import { TAB_DASHBOARD, TAB_QUERY_PARAM, UI_PATH } from '../../shared/constants';
import type { SerializedDashboardFilters, SerializedSavedCostRates } from './api';
import { saveCostRates } from './api';
import { ModelCostTable } from './ModelCostTable';
import { Spinner } from './Spinner';
import { navigateToSearch } from './routing';

export const DASHBOARD_FORM_ID = 'dashboard-form';

function savedRatesLabel(savedCostRates: SerializedSavedCostRates | null): string {
  if (!savedCostRates?.updatedAt) {
    return `Using built-in defaults: $${DEFAULT_INPUT_COST_PER_MILLION.toFixed(2)} input / $${DEFAULT_OUTPUT_COST_PER_MILLION.toFixed(2)} output per 1M tokens.`;
  }

  const { inputPerMillion, outputPerMillion } = savedCostRates.defaultRates;
  const updated = new Date(savedCostRates.updatedAt).toLocaleString();
  return `Saved rates: $${inputPerMillion.toFixed(2)} input / $${outputPerMillion.toFixed(2)} output per 1M tokens (updated ${updated}).`;
}

function toDashboardFilters(filters: SerializedDashboardFilters): DashboardFilters {
  return {
    ...filters,
    modelCosts: new Map(Object.entries(filters.modelCosts)),
  };
}

function readFormSearch(form: HTMLFormElement): string {
  const params = new URLSearchParams();
  for (const [key, value] of new FormData(form).entries()) {
    if (typeof value === 'string') {
      params.append(key, value);
    }
  }
  params.set(TAB_QUERY_PARAM, TAB_DASHBOARD);
  return `?${params.toString()}`;
}

export function FilterForm({
  filters,
  models,
  savedCostRates,
  onApply,
}: {
  filters: SerializedDashboardFilters;
  models: string[];
  savedCostRates: SerializedSavedCostRates | null;
  onApply: (search: string) => void;
}) {
  const [status, setStatus] = useState('');
  const [statusError, setStatusError] = useState(false);
  const [saving, setSaving] = useState(false);
  const dashboardFilters = toDashboardFilters(filters);

  function onDateBucketClick(event: Event, dateBucket: DashboardFilters['dateBucket']) {
    event.preventDefault();
    const href = buildDashboardUrl(dashboardFilters, { dateBucket });
    navigateToSearch(href.slice(UI_PATH.length));
    onApply(href.slice(UI_PATH.length));
  }

  async function onSaveRates() {
    const form = document.getElementById(DASHBOARD_FORM_ID) as HTMLFormElement | null;
    if (!form) {
      return;
    }

    setSaving(true);
    setStatus('');
    setStatusError(false);

    const formData = new FormData(form);
    const defaultRates = {
      inputPerMillion: Number(formData.get('input_cost')),
      outputPerMillion: Number(formData.get('output_cost')),
    };
    const modelCosts: Record<string, Partial<{ inputPerMillion: number; outputPerMillion: number }>> =
      {};

    for (const [key, value] of formData.entries()) {
      const inputMatch = key.match(/^input_cost\[(.+)\]$/);
      if (inputMatch) {
        const model = inputMatch[1];
        modelCosts[model] = modelCosts[model] || {};
        modelCosts[model].inputPerMillion = Number(value);
        continue;
      }
      const outputMatch = key.match(/^output_cost\[(.+)\]$/);
      if (outputMatch) {
        const model = outputMatch[1];
        modelCosts[model] = modelCosts[model] || {};
        modelCosts[model].outputPerMillion = Number(value);
      }
    }

    try {
      await saveCostRates({ defaultRates, modelCosts });
      const search = `?${TAB_QUERY_PARAM}=${TAB_DASHBOARD}&saved=1`;
      navigateToSearch(search);
      onApply(search);
      setStatus('');
    } catch {
      setStatus('Failed to save cost rates. Check database connectivity.');
      setStatusError(true);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div class="card">
      <h2>Filters &amp; cost rates</h2>
      <p class="card-subtitle">
        Est. cost = (prompt tokens × input $/1M + completion tokens × output $/1M) ÷ 1,000,000. Local
        inference is assumed free.
      </p>
      <p class="muted" id="cost-rates-source">
        {savedRatesLabel(savedCostRates)}
      </p>
      <form id={DASHBOARD_FORM_ID}>
        <input type="hidden" name={TAB_QUERY_PARAM} value={TAB_DASHBOARD} />
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
                href={buildDashboardUrl(dashboardFilters, { dateBucket: bucket.id })}
                class={`date-bucket${filters.dateBucket === bucket.id ? ' active' : ''}`}
                onClick={(event: Event) => onDateBucketClick(event, bucket.id)}
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
          <button
            type="button"
            class="btn-primary btn-with-spinner"
            disabled={saving}
            aria-busy={saving}
            onClick={() => void onSaveRates()}
          >
            {saving ? <Spinner size="sm" /> : null}
            {saving ? 'Saving…' : 'Save rates'}
          </button>
          <p class="muted form-action-hint">
            Save persists rates to the database for all clients. Refresh applies unsaved edits for
            this session only.
          </p>
          {status ? (
            <p
              id="cost-rates-status"
              class={`cost-rates-status${statusError ? ' error' : ''}`}
              role="status"
              aria-live="polite"
            >
              {status}
            </p>
          ) : null}
        </div>
      </form>
    </div>
  );
}

export function applyDashboardFormToUrl(): string {
  const form = document.getElementById(DASHBOARD_FORM_ID) as HTMLFormElement | null;
  if (!form) {
    return window.location.search;
  }
  const search = readFormSearch(form);
  navigateToSearch(search);
  return search;
}
