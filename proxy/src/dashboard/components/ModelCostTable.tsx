/** @jsxImportSource hono/jsx */
import type { FC } from 'hono/jsx';
import { rowRates } from '../lib/cost';
import type { DashboardFilters } from '../types';

export const ModelCostTable: FC<{ models: string[]; filters: DashboardFilters }> = ({
  models,
  filters,
}) => {
  if (models.length === 0) {
    return <p class="muted">No models logged yet. Defaults apply once traffic arrives.</p>;
  }

  return (
    <div class="table-scroll">
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
            const rates = rowRates(filters, model);
            return (
              <tr>
                <td>
                  <code>{model}</code>
                </td>
                <td>
                  <div class="input-shell">
                    <span class="input-prefix">$</span>
                    <input
                      type="number"
                      class="number-input"
                      name={`input_cost[${model}]`}
                      value={rates.inputPerMillion}
                      min={0}
                      step={0.01}
                    />
                  </div>
                </td>
                <td>
                  <div class="input-shell">
                    <span class="input-prefix">$</span>
                    <input
                      type="number"
                      class="number-input"
                      name={`output_cost[${model}]`}
                      value={rates.outputPerMillion}
                      min={0}
                      step={0.01}
                    />
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};
