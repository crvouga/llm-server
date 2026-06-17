import { useState, type MouseEvent } from 'react';
import { Button, Card, Chip, Input, Spinner } from '@heroui/react';
import {
  DASHBOARD_FORM_ID,
  DATE_BUCKETS,
  DEFAULT_INPUT_COST,
  DEFAULT_OUTPUT_COST,
  TAB_DASHBOARD,
  TAB_QUERY_PARAM,
} from '../lib/constants';
import { rowRates } from '../lib/format';
import { useSaveCostRatesMutation } from '../hooks/queries';
import { buildDashboardSearch, navigateToSearch } from '../lib/routing';
import type { DashboardFilters, SavedCostRates } from '../lib/types';

function CostRateInput({ name, value }: { name: string; value: number }) {
  return (
    <div className="flex items-center gap-1">
      <span className="text-sm font-semibold text-muted">$</span>
      <Input
        type="number"
        name={name}
        defaultValue={String(value)}
        min={0}
        step={0.01}
        className="min-w-0 flex-1"
        variant="secondary"
      />
    </div>
  );
}

function ModelCostTable({
  models,
  filters,
}: {
  models: string[];
  filters: Pick<DashboardFilters, 'modelCosts' | 'defaultRates'>;
}) {
  if (models.length === 0) {
    return <p className="text-sm text-muted">No models logged yet. Defaults apply once traffic arrives.</p>;
  }

  return (
    <div className="overflow-x-auto -mx-2 px-2">
      <table className="w-full text-xs md:text-sm">
        <thead>
          <tr className="border-b border-separator text-left text-xs font-semibold uppercase tracking-wide text-muted">
            <th className="px-3 py-2">Model</th>
            <th className="px-3 py-2">Input $/1M tokens</th>
            <th className="px-3 py-2">Output $/1M tokens</th>
          </tr>
        </thead>
        <tbody>
          {models.map((model) => {
            const rates = rowRates(filters, model);
            return (
              <tr key={model} className="border-b border-separator/60">
                <td className="px-3 py-2">
                  <Chip size="sm" variant="soft" color="accent">
                    <Chip.Label>{model}</Chip.Label>
                  </Chip>
                </td>
                <td className="px-3 py-2">
                  <CostRateInput name={`input_cost[${model}]`} value={rates.inputPerMillion} />
                </td>
                <td className="px-3 py-2">
                  <CostRateInput name={`output_cost[${model}]`} value={rates.outputPerMillion} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

interface FilterFormProps {
  filters: Pick<DashboardFilters, 'dateBucket' | 'sortKey' | 'sortDir' | 'defaultRates' | 'modelCosts'>;
  models: string[];
  savedCostRates: SavedCostRates | null;
}

export function FilterForm({ filters, models, savedCostRates }: FilterFormProps) {
  const [status, setStatus] = useState('');
  const [statusError, setStatusError] = useState(false);
  const saveRates = useSaveCostRatesMutation();

  function savedRatesLabel() {
    if (!savedCostRates?.updatedAt) {
      return `Using built-in defaults: $${DEFAULT_INPUT_COST.toFixed(2)} input / $${DEFAULT_OUTPUT_COST.toFixed(2)} output per 1M tokens.`;
    }
    const { inputPerMillion, outputPerMillion } = savedCostRates.defaultRates;
    const updated = new Date(savedCostRates.updatedAt).toLocaleString();
    return `Saved rates: $${inputPerMillion.toFixed(2)} input / $${outputPerMillion.toFixed(2)} output per 1M tokens (updated ${updated}).`;
  }

  function onDateBucketClick(event: MouseEvent<HTMLAnchorElement>, dateBucket: string) {
    event.preventDefault();
    navigateToSearch(buildDashboardSearch(filters, { dateBucket }));
  }

  function onSaveRates() {
    const form = document.getElementById(DASHBOARD_FORM_ID) as HTMLFormElement | null;
    if (!form) return;
    setStatus('');
    setStatusError(false);

    const formData = new FormData(form);
    const defaultRates = {
      inputPerMillion: Number(formData.get('input_cost')),
      outputPerMillion: Number(formData.get('output_cost')),
    };
    const modelCosts: Record<string, { inputPerMillion?: number; outputPerMillion?: number }> = {};
    for (const [key, value] of formData.entries()) {
      const inputMatch = key.match(/^input_cost\[(.+)\]$/);
      if (inputMatch) {
        modelCosts[inputMatch[1]] = modelCosts[inputMatch[1]] || {};
        modelCosts[inputMatch[1]].inputPerMillion = Number(value);
        continue;
      }
      const outputMatch = key.match(/^output_cost\[(.+)\]$/);
      if (outputMatch) {
        modelCosts[outputMatch[1]] = modelCosts[outputMatch[1]] || {};
        modelCosts[outputMatch[1]].outputPerMillion = Number(value);
      }
    }

    saveRates.mutate(
      { defaultRates, modelCosts },
      {
        onError: () => {
          setStatus('Failed to save cost rates. Check database connectivity.');
          setStatusError(true);
        },
      },
    );
  }

  return (
    <Card className="min-w-0 w-full max-w-full">
      <Card.Header>
        <Card.Title>Filters &amp; cost rates</Card.Title>
        <Card.Description>
          Est. cost = (prompt tokens × input $/1M + completion tokens × output $/1M) ÷ 1,000,000. Local inference is
          assumed free.
        </Card.Description>
      </Card.Header>
      <Card.Content>
        <p className="text-sm text-muted">{savedRatesLabel()}</p>
        <form id={DASHBOARD_FORM_ID} className="mt-4 space-y-4">
          <input type="hidden" name={TAB_QUERY_PARAM} value={TAB_DASHBOARD} />
          <input type="hidden" name="range" value={filters.dateBucket} />
          {filters.sortKey !== 'totalTokens' ? <input type="hidden" name="sort" value={filters.sortKey} /> : null}
          {filters.sortDir !== 'desc' ? <input type="hidden" name="dir" value={filters.sortDir} /> : null}

          <fieldset className="rounded-lg border border-separator p-4">
            <legend className="px-1 text-sm font-semibold">Date range</legend>
            <div className="mt-2 flex flex-wrap gap-2">
              {DATE_BUCKETS.map((bucket) => (
                <a
                  key={bucket.id}
                  href={buildDashboardSearch(filters, { dateBucket: bucket.id })}
                  onClick={(e) => onDateBucketClick(e, bucket.id)}
                >
                  <Chip
                    size="md"
                    variant={filters.dateBucket === bucket.id ? 'primary' : 'secondary'}
                    color={filters.dateBucket === bucket.id ? 'accent' : 'default'}
                    className="cursor-pointer touch-manipulation"
                  >
                    <Chip.Label>{bucket.label}</Chip.Label>
                  </Chip>
                </a>
              ))}
            </div>
          </fieldset>

          <fieldset className="rounded-lg border border-separator p-4">
            <legend className="px-1 text-sm font-semibold">Default cloud rates (USD per 1M tokens)</legend>
            <div className="mt-2 grid gap-4 sm:grid-cols-2">
              <label className="block text-sm">
                <span className="mb-1 block font-semibold text-muted">Input</span>
                <CostRateInput name="input_cost" value={filters.defaultRates.inputPerMillion} />
              </label>
              <label className="block text-sm">
                <span className="mb-1 block font-semibold text-muted">Output</span>
                <CostRateInput name="output_cost" value={filters.defaultRates.outputPerMillion} />
              </label>
            </div>
          </fieldset>

          <fieldset className="rounded-lg border border-separator p-4">
            <legend className="px-1 text-sm font-semibold">Per-model rate overrides</legend>
            <div className="mt-2">
              <ModelCostTable models={models} filters={filters} />
            </div>
          </fieldset>

          <div className="flex flex-wrap items-center gap-3">
            <Button
              type="button"
              variant="primary"
              isDisabled={saveRates.isPending}
              onPress={() => onSaveRates()}
            >
              {saveRates.isPending ? <Spinner size="sm" color="current" /> : null}
              {saveRates.isPending ? 'Saving…' : 'Save rates'}
            </Button>
            <p className="text-sm text-muted">
              Save persists rates to the database for all clients. Refresh applies unsaved edits for this session only.
            </p>
            {status ? (
              <p
                className={`w-full text-sm ${statusError ? 'font-semibold text-danger' : 'text-muted'}`}
                role="status"
              >
                {status}
              </p>
            ) : null}
          </div>
        </form>
      </Card.Content>
    </Card>
  );
}

export function applyDashboardFormToUrl() {
  const form = document.getElementById(DASHBOARD_FORM_ID) as HTMLFormElement | null;
  if (!form) return window.location.search;
  const params = new URLSearchParams();
  for (const [key, value] of new FormData(form).entries()) {
    if (typeof value === 'string') params.append(key, value);
  }
  params.set(TAB_QUERY_PARAM, TAB_DASHBOARD);
  const search = `?${params.toString()}`;
  navigateToSearch(search);
  return search;
}
