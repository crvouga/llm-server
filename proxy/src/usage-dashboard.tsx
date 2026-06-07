/** @jsxImportSource hono/jsx */
// Usage dashboard — pure HTML forms, no client-side JavaScript.
// Serves GET/POST /usage-dashboard with token usage and money-saved estimates.

import { neon, NeonDbError } from '@neondatabase/serverless';
import { Hono } from 'hono';
import type { FC } from 'hono/jsx';

export const DASHBOARD_PATH = '/usage-dashboard';

const DEFAULT_INPUT_COST_PER_TOKEN = 0.000001;
const DEFAULT_OUTPUT_COST_PER_TOKEN = 0.000002;

interface ModelUsageRow {
  model: string;
  requestCount: number;
  promptTokens: number;
  completionTokens: number;
}

interface ModelCostRates {
  inputPerToken: number;
  outputPerToken: number;
}

interface DashboardFilters {
  startDate: string;
  endDate: string;
  defaultRates: ModelCostRates;
  modelCosts: Map<string, ModelCostRates>;
}

interface UsageSummary {
  rows: ModelUsageRow[];
  totals: {
    requestCount: number;
    promptTokens: number;
    completionTokens: number;
    totalTokens: number;
    moneySavedUsd: number;
  };
}

type DashboardEnv = {
  Bindings: {
    DATABASE_URL: string;
  };
};

const dashboardStyles = `
  :root {
    color-scheme: light dark;
    font-family: ui-sans-serif, system-ui, sans-serif;
    line-height: 1.5;
  }
  body {
    margin: 0 auto;
    max-width: 960px;
    padding: 1.5rem;
  }
  h1, h2 { margin-top: 0; }
  form, section {
    margin-bottom: 2rem;
  }
  fieldset {
    border: 1px solid color-mix(in srgb, currentColor 20%, transparent);
    border-radius: 8px;
    margin-bottom: 1rem;
    padding: 1rem;
  }
  legend { font-weight: 600; }
  label {
    display: block;
    margin-bottom: 0.75rem;
  }
  input[type="date"], input[type="number"] {
    margin-left: 0.5rem;
    max-width: 100%;
  }
  table {
    border-collapse: collapse;
    width: 100%;
  }
  th, td {
    border-bottom: 1px solid color-mix(in srgb, currentColor 15%, transparent);
    padding: 0.5rem;
    text-align: left;
    vertical-align: top;
  }
  .num { text-align: right; font-variant-numeric: tabular-nums; }
  .total-row td { border-top: 2px solid currentColor; }
  .muted { opacity: 0.75; }
  .error { color: #c0392b; font-weight: 600; }
  button {
    cursor: pointer;
    font: inherit;
    padding: 0.5rem 1rem;
  }
`;

function formatUsd(amount: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  }).format(amount);
}

function formatInt(value: number): string {
  return new Intl.NumberFormat('en-US').format(value);
}

function todayIsoDate(): string {
  return new Date().toISOString().slice(0, 10);
}

function parseIsoDate(value: string | null, fallback: string): string {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return fallback;
  }
  return value;
}

function parseCost(value: string | null, fallback: number): number {
  if (!value || value.trim() === '') {
    return fallback;
  }
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0) {
    return fallback;
  }
  return parsed;
}

function defaultFilters(models: string[]): DashboardFilters {
  const defaultRates: ModelCostRates = {
    inputPerToken: DEFAULT_INPUT_COST_PER_TOKEN,
    outputPerToken: DEFAULT_OUTPUT_COST_PER_TOKEN,
  };

  return {
    startDate: todayIsoDate(),
    endDate: todayIsoDate(),
    defaultRates,
    modelCosts: new Map(models.map((model) => [model, { ...defaultRates }])),
  };
}

function parseDashboardFilters(formData: FormData, knownModels: string[]): DashboardFilters {
  const endDefault = todayIsoDate();

  const startDate = parseIsoDate(formData.get('start_date')?.toString() ?? null, endDefault);
  const endDate = parseIsoDate(formData.get('end_date')?.toString() ?? null, endDefault);

  const defaultRates: ModelCostRates = {
    inputPerToken: parseCost(
      formData.get('default_input_cost')?.toString() ?? null,
      DEFAULT_INPUT_COST_PER_TOKEN,
    ),
    outputPerToken: parseCost(
      formData.get('default_output_cost')?.toString() ?? null,
      DEFAULT_OUTPUT_COST_PER_TOKEN,
    ),
  };

  const modelCosts = new Map<string, ModelCostRates>();
  for (const model of knownModels) {
    const inputPerToken = parseCost(
      formData.get(`input_cost[${model}]`)?.toString() ?? null,
      defaultRates.inputPerToken,
    );
    const outputPerToken = parseCost(
      formData.get(`output_cost[${model}]`)?.toString() ?? null,
      defaultRates.outputPerToken,
    );
    modelCosts.set(model, { inputPerToken, outputPerToken });
  }

  return { startDate, endDate, defaultRates, modelCosts };
}

async function fetchKnownModels(databaseUrl: string): Promise<string[]> {
  const sql = neon(databaseUrl);
  const rows = await sql`
    SELECT DISTINCT COALESCE(request_body->>'model', 'unknown') AS model
    FROM llm_proxy.http_log
    WHERE request_path = '/v1/chat/completions'
      AND request_body ? 'model'
    ORDER BY model ASC
  `;

  return rows.map((row) => String(row.model));
}

async function fetchUsageRows(
  databaseUrl: string,
  startDate: string,
  endDate: string,
): Promise<ModelUsageRow[]> {
  const sql = neon(databaseUrl);

  const rows = await sql`
    SELECT
      COALESCE(request_body->>'model', 'unknown') AS model,
      COUNT(*)::int AS request_count,
      COALESCE(SUM((response_body->'usage'->>'prompt_tokens')::bigint), 0)::bigint AS prompt_tokens,
      COALESCE(SUM((response_body->'usage'->>'completion_tokens')::bigint), 0)::bigint AS completion_tokens
    FROM 
      llm_proxy.http_log
    WHERE request_path = '/v1/chat/completions'
      AND response_status_code >= 200
      AND response_status_code < 300
      AND response_body ? 'usage'
      AND created_at >= ${startDate}::date
      AND created_at < (${endDate}::date + INTERVAL '1 day')
    GROUP BY 1
    ORDER BY (
      COALESCE(SUM((response_body->'usage'->>'prompt_tokens')::bigint), 0)
      + COALESCE(SUM((response_body->'usage'->>'completion_tokens')::bigint), 0)
    ) DESC
  `;

  return rows.map((row) => ({
    model: String(row.model),
    requestCount: Number(row.request_count),
    promptTokens: Number(row.prompt_tokens),
    completionTokens: Number(row.completion_tokens),
  }));
}

function rowRates(filters: DashboardFilters, model: string): ModelCostRates {
  return filters.modelCosts.get(model) ?? filters.defaultRates;
}

function rowCost(row: ModelUsageRow, rates: ModelCostRates): number {
  return row.promptTokens * rates.inputPerToken + row.completionTokens * rates.outputPerToken;
}

function summarizeUsage(rows: ModelUsageRow[], filters: DashboardFilters): UsageSummary {
  let requestCount = 0;
  let promptTokens = 0;
  let completionTokens = 0;
  let moneySavedUsd = 0;

  for (const row of rows) {
    const rates = rowRates(filters, row.model);
    requestCount += row.requestCount;
    promptTokens += row.promptTokens;
    completionTokens += row.completionTokens;
    moneySavedUsd += rowCost(row, rates);
  }

  return {
    rows,
    totals: {
      requestCount,
      promptTokens,
      completionTokens,
      totalTokens: promptTokens + completionTokens,
      moneySavedUsd,
    },
  };
}

const ModelCostTable: FC<{ models: string[]; filters: DashboardFilters }> = ({
  models,
  filters,
}) => {
  if (models.length === 0) {
    return <p class="muted">No models logged yet. Defaults below apply once traffic arrives.</p>;
  }

  return (
    <table>
      <thead>
        <tr>
          <th>Model</th>
          <th>Input $/token</th>
          <th>Output $/token</th>
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
                <input
                  type="number"
                  name={`input_cost[${model}]`}
                  value={rates.inputPerToken}
                  min={0}
                  step={0.0000001}
                />
              </td>
              <td>
                <input
                  type="number"
                  name={`output_cost[${model}]`}
                  value={rates.outputPerToken}
                  min={0}
                  step={0.0000001}
                />
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
};

const UsageResultsTable: FC<{ summary: UsageSummary; filters: DashboardFilters }> = ({
  summary,
  filters,
}) => {
  if (summary.rows.length === 0) {
    return <p class="muted">No chat completion usage found for this date range.</p>;
  }

  return (
    <table>
      <thead>
        <tr>
          <th>Model</th>
          <th>Requests</th>
          <th>Prompt tokens</th>
          <th>Completion tokens</th>
          <th>Total tokens</th>
          <th>Money saved</th>
        </tr>
      </thead>
      <tbody>
        {summary.rows.map((row) => {
          const rates = rowRates(filters, row.model);
          const totalTokens = row.promptTokens + row.completionTokens;
          return (
            <tr>
              <td>
                <code>{row.model}</code>
              </td>
              <td class="num">{formatInt(row.requestCount)}</td>
              <td class="num">{formatInt(row.promptTokens)}</td>
              <td class="num">{formatInt(row.completionTokens)}</td>
              <td class="num">{formatInt(totalTokens)}</td>
              <td class="num">{formatUsd(rowCost(row, rates))}</td>
            </tr>
          );
        })}
        <tr class="total-row">
          <td>
            <strong>Total</strong>
          </td>
          <td class="num">
            <strong>{formatInt(summary.totals.requestCount)}</strong>
          </td>
          <td class="num">
            <strong>{formatInt(summary.totals.promptTokens)}</strong>
          </td>
          <td class="num">
            <strong>{formatInt(summary.totals.completionTokens)}</strong>
          </td>
          <td class="num">
            <strong>{formatInt(summary.totals.totalTokens)}</strong>
          </td>
          <td class="num">
            <strong>{formatUsd(summary.totals.moneySavedUsd)}</strong>
          </td>
        </tr>
      </tbody>
    </table>
  );
};

const UsageDashboardPage: FC<{
  filters: DashboardFilters;
  models: string[];
  summary: UsageSummary | null;
  errorMessage?: string;
}> = ({ filters, models, summary, errorMessage }) => (
  <html lang="en">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>LLM Proxy Usage Dashboard</title>
      <style>{dashboardStyles}</style>
    </head>
    <body>
      <h1>LLM Proxy Usage Dashboard</h1>
      <p class="muted">Pure HTML forms — no client-side JavaScript.</p>
      {errorMessage ? <p class="error">{errorMessage}</p> : null}
      <form method="post" action={DASHBOARD_PATH}>
        <fieldset>
          <legend>Date range</legend>
          <label>
            Start
            <input type="date" name="start_date" value={filters.startDate} required />
          </label>
          <label>
            End
            <input type="date" name="end_date" value={filters.endDate} required />
          </label>
        </fieldset>

        <fieldset>
          <legend>Default cloud rates (USD per token)</legend>
          <label>
            Input
            <input
              type="number"
              name="default_input_cost"
              value={filters.defaultRates.inputPerToken}
              min={0}
              step={0.0000001}
              required
            />
          </label>
          <label>
            Output
            <input
              type="number"
              name="default_output_cost"
              value={filters.defaultRates.outputPerToken}
              min={0}
              step={0.0000001}
              required
            />
          </label>
          <p class="muted">Defaults: $1.00 / 1M input tokens, $2.00 / 1M output tokens.</p>
        </fieldset>

        <fieldset>
          <legend>Per-model overrides</legend>
          <ModelCostTable models={models} filters={filters} />
        </fieldset>

        <button type="submit">Calculate usage</button>
      </form>
      {summary === null ? null : (
        <section>
          <h2>Usage results</h2>
          <p class="muted">
            Range: {filters.startDate} through {filters.endDate}. Money saved = tokens × configured
            cloud rates (local inference assumed free).
          </p>
          <UsageResultsTable summary={summary} filters={filters} />
        </section>
      )}
    </body>
  </html>
);

export const usageDashboardRoute = new Hono<DashboardEnv>();

usageDashboardRoute.get(DASHBOARD_PATH, async (c) => {
  if (!c.env.DATABASE_URL) {
    return c.text('DATABASE_URL not configured', 503);
  }

  try {
    const models = await fetchKnownModels(c.env.DATABASE_URL);
    return c.html(
      <UsageDashboardPage filters={defaultFilters(models)} models={models} summary={null} />,
    );
  } catch (error) {
    const code = error instanceof NeonDbError ? error.code : 'unknown';
    console.error(`Usage dashboard failed (code: ${code ?? 'unknown'})`);

    return c.html(
      <UsageDashboardPage
        filters={defaultFilters([])}
        models={[]}
        summary={null}
        errorMessage="Failed to load usage data. Check database connectivity."
      />,
      500,
    );
  }
});

usageDashboardRoute.post(DASHBOARD_PATH, async (c) => {
  if (!c.env.DATABASE_URL) {
    return c.text('DATABASE_URL not configured', 503);
  }

  try {
    const models = await fetchKnownModels(c.env.DATABASE_URL);
    const formData = await c.req.formData();
    const filters = parseDashboardFilters(formData, models);
    const rows = await fetchUsageRows(c.env.DATABASE_URL, filters.startDate, filters.endDate);
    const summary = summarizeUsage(rows, filters);

    return c.html(<UsageDashboardPage filters={filters} models={models} summary={summary} />);
  } catch (error) {
    const code = error instanceof NeonDbError ? error.code : 'unknown';
    console.error(`Usage dashboard failed (code: ${code ?? 'unknown'})`);

    return c.html(
      <UsageDashboardPage
        filters={defaultFilters([])}
        models={[]}
        summary={null}
        errorMessage="Failed to load usage data. Check database connectivity."
      />,
      500,
    );
  }
});
