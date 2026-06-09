/** @jsxImportSource hono/jsx/dom */
import { rowRates } from '../../dashboard/lib/cost';
import type { SerializedDashboardFilters } from './api';

function CostRateInput({ name, value }: { name: string; value: number }) {
  return (
    <div class="input-shell">
      <span class="input-prefix">$</span>
      <input type="number" class="number-input" name={name} value={value} min={0} step={0.01} />
    </div>
  );
}

function toFilterShape(filters: SerializedDashboardFilters) {
  return {
    ...filters,
    modelCosts: new Map(Object.entries(filters.modelCosts)),
  };
}

export function ModelCostTable({
  models,
  filters,
}: {
  models: string[];
  filters: SerializedDashboardFilters;
}) {
  if (models.length === 0) {
    return <p class="muted">No models logged yet. Defaults apply once traffic arrives.</p>;
  }

  const filterShape = toFilterShape(filters);

  return (
    <div class="table-scroll model-cost-overrides">
      <table>
        <thead>
          <tr>
            <th>Model</th>
            <th>Input $/1M tokens</th>
            <th>Output $/1M tokens</th>
          </tr>
        </thead>
        <tbody>
          {models.map((model) => {
            const rates = rowRates(filterShape, model);
            return (
              <tr key={model}>
                <td>
                  <code>{model}</code>
                </td>
                <td data-label="Input $/1M tokens">
                  <CostRateInput name={`input_cost[${model}]`} value={rates.inputPerMillion} />
                </td>
                <td data-label="Output $/1M tokens">
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
