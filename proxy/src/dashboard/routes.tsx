/** @jsxImportSource hono/jsx */
import { NeonDbError } from '@neondatabase/serverless';
import { Hono } from 'hono';
import { DashboardPage } from './components/DashboardPage';
import { COST_RATES_PATH, DASHBOARD_PATH, LEGACY_DASHBOARD_PATH } from './constants';
import { defaultSavedCostRates, fetchCostRates, upsertCostRates } from './db/cost-rates';
import { loadDashboardData } from './db/load';
import { fetchEarliestUsageDate, fetchKnownModels } from './db/queries';
import { emptyFilters } from './lib/filters';
import { parseCostPerMillion } from './lib/format';
import { parseFiltersFromQuery } from './lib/query-params';
import type { DashboardEnv, DashboardFilters, ModelCostRates } from './types';

interface CostRatesPostBody {
  defaultRates?: Partial<ModelCostRates>;
  modelCosts?: Record<string, Partial<ModelCostRates>>;
}

function parsePostDefaultRates(body: CostRatesPostBody, fallback: ModelCostRates): ModelCostRates {
  return {
    inputPerMillion: parseCostPerMillion(
      body.defaultRates?.inputPerMillion != null ? String(body.defaultRates.inputPerMillion) : null,
      fallback.inputPerMillion,
    ),
    outputPerMillion: parseCostPerMillion(
      body.defaultRates?.outputPerMillion != null
        ? String(body.defaultRates.outputPerMillion)
        : null,
      fallback.outputPerMillion,
    ),
  };
}

function parsePostModelCosts(
  body: CostRatesPostBody,
  knownModels: string[],
  defaultRates: ModelCostRates,
): Map<string, ModelCostRates> {
  const modelCosts = new Map<string, ModelCostRates>();
  for (const model of knownModels) {
    const override = body.modelCosts?.[model];
    modelCosts.set(model, {
      inputPerMillion: parseCostPerMillion(
        override?.inputPerMillion != null ? String(override.inputPerMillion) : null,
        defaultRates.inputPerMillion,
      ),
      outputPerMillion: parseCostPerMillion(
        override?.outputPerMillion != null ? String(override.outputPerMillion) : null,
        defaultRates.outputPerMillion,
      ),
    });
  }
  return modelCosts;
}

async function renderDashboard(
  databaseUrl: string,
  filters: DashboardFilters,
  models: string[],
  savedCostRates: Awaited<ReturnType<typeof fetchCostRates>>,
  flashMessage?: string,
) {
  const { summary, dailyRows } = await loadDashboardData(databaseUrl, filters);
  return (
    <DashboardPage
      filters={filters}
      models={models}
      summary={summary}
      dailyRows={dailyRows}
      savedCostRates={savedCostRates}
      flashMessage={flashMessage}
    />
  );
}

async function fallbackFilters(databaseUrl: string): Promise<DashboardFilters> {
  try {
    const earliestDate = await fetchEarliestUsageDate(databaseUrl);
    const models = await fetchKnownModels(databaseUrl);
    const savedRates = await fetchCostRates(databaseUrl);
    return parseFiltersFromQuery({}, earliestDate, models, savedRates);
  } catch {
    return emptyFilters();
  }
}

export const dashboardRoute = new Hono<DashboardEnv>();

dashboardRoute.get(LEGACY_DASHBOARD_PATH, (c) => c.redirect(DASHBOARD_PATH, 301));

dashboardRoute.get(COST_RATES_PATH, async (c) => {
  if (!c.env.DATABASE_URL) {
    return c.text('DATABASE_URL not configured', 503);
  }

  try {
    const saved = await fetchCostRates(c.env.DATABASE_URL);
    if (!saved) {
      const defaults = defaultSavedCostRates();
      return c.json({
        defaultRates: defaults.defaultRates,
        modelOverrides: Object.fromEntries(defaults.modelOverrides),
        updatedAt: defaults.updatedAt,
      });
    }

    return c.json({
      defaultRates: saved.defaultRates,
      modelOverrides: Object.fromEntries(saved.modelOverrides),
      updatedAt: saved.updatedAt,
    });
  } catch (error) {
    const code = error instanceof NeonDbError ? error.code : 'unknown';
    console.error(`Cost rates fetch failed (code: ${code ?? 'unknown'})`);
    return c.json({ error: 'Failed to load cost rates' }, 500);
  }
});

dashboardRoute.post(COST_RATES_PATH, async (c) => {
  if (!c.env.DATABASE_URL) {
    return c.text('DATABASE_URL not configured', 503);
  }

  try {
    const databaseUrl = c.env.DATABASE_URL;
    const body = (await c.req.json()) as CostRatesPostBody;
    const savedRates = await fetchCostRates(databaseUrl);
    const fallback = savedRates?.defaultRates ?? defaultSavedCostRates().defaultRates;
    const defaultRates = parsePostDefaultRates(body, fallback);
    const models = await fetchKnownModels(databaseUrl);
    const modelCosts = parsePostModelCosts(body, models, defaultRates);
    const saved = await upsertCostRates(databaseUrl, defaultRates, modelCosts);

    return c.json({
      ok: true,
      defaultRates: saved.defaultRates,
      modelOverrides: Object.fromEntries(saved.modelOverrides),
      updatedAt: saved.updatedAt,
    });
  } catch (error) {
    const code = error instanceof NeonDbError ? error.code : 'unknown';
    console.error(`Cost rates save failed (code: ${code ?? 'unknown'})`);
    return c.json({ error: 'Failed to save cost rates' }, 500);
  }
});

dashboardRoute.get(DASHBOARD_PATH, async (c) => {
  if (!c.env.DATABASE_URL) {
    return c.text('DATABASE_URL not configured', 503);
  }

  try {
    const databaseUrl = c.env.DATABASE_URL;
    const [models, earliestDate, savedCostRates] = await Promise.all([
      fetchKnownModels(databaseUrl),
      fetchEarliestUsageDate(databaseUrl),
      fetchCostRates(databaseUrl),
    ]);
    const filters = parseFiltersFromQuery(c.req.query(), earliestDate, models, savedCostRates);
    const flashMessage =
      c.req.query('saved') === '1' ? 'Cost rates saved and shared across clients.' : undefined;
    return c.html(
      await renderDashboard(databaseUrl, filters, models, savedCostRates, flashMessage),
    );
  } catch (error) {
    const code = error instanceof NeonDbError ? error.code : 'unknown';
    console.error(`Dashboard failed (code: ${code ?? 'unknown'})`);

    return c.html(
      <DashboardPage
        filters={await fallbackFilters(c.env.DATABASE_URL)}
        models={[]}
        summary={null}
        dailyRows={[]}
        savedCostRates={null}
        errorMessage="Failed to load dashboard data. Check database connectivity."
      />,
      500,
    );
  }
});
