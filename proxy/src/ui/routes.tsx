/** @jsxImportSource hono/jsx */
import { NeonDbError } from '@neondatabase/serverless';
import { Hono } from 'hono';
import { defaultSavedCostRates, fetchCostRates, upsertCostRates } from '../dashboard/db/cost-rates';
import { loadDashboardData } from '../dashboard/db/load';
import { fetchEarliestUsageDate, fetchKnownModels } from '../dashboard/db/queries';
import { parseCostPerMillion } from '../dashboard/lib/format';
import { parseFiltersFromQuery } from '../dashboard/lib/query-params';
import { buildClientPayload } from '../dashboard/lib/summary';
import type { DashboardEnv, DashboardFilters, ModelCostRates } from '../dashboard/types';
import { fetchBackendUrl } from '../proxy-state';
import {
  COST_RATES_PATH,
  DASHBOARD_DATA_API_PATH,
  LEGACY_CHAT_PATH,
  LEGACY_DASHBOARD_ALIAS_PATH,
  LEGACY_DASHBOARD_PATH,
  MODELS_API_PATH,
  TAB_DASHBOARD,
  TAB_QUERY_PARAM,
  UI_PATH,
} from '../shared/constants';
import { UiShell } from './components/UiShell';

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

function serializeFilters(filters: DashboardFilters) {
  return {
    dateBucket: filters.dateBucket,
    startDate: filters.startDate,
    endDate: filters.endDate,
    defaultRates: filters.defaultRates,
    modelCosts: Object.fromEntries(filters.modelCosts),
    sortKey: filters.sortKey,
    sortDir: filters.sortDir,
  };
}

function legacyDashboardRedirectUrl(): string {
  return `${UI_PATH}?${TAB_QUERY_PARAM}=${TAB_DASHBOARD}`;
}

function legacyChatRedirectUrl(): string {
  return `${UI_PATH}?${TAB_QUERY_PARAM}=chat`;
}

export const uiRoute = new Hono<DashboardEnv>();

uiRoute.get(LEGACY_DASHBOARD_PATH, (c) => c.redirect(legacyDashboardRedirectUrl(), 301));
uiRoute.get(LEGACY_DASHBOARD_ALIAS_PATH, (c) => c.redirect(legacyDashboardRedirectUrl(), 301));
uiRoute.get(LEGACY_CHAT_PATH, (c) => c.redirect(legacyChatRedirectUrl(), 301));

uiRoute.get(UI_PATH, (c) => c.html(<UiShell />));

uiRoute.get(COST_RATES_PATH, async (c) => {
  if (!c.env?.DATABASE_URL) {
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

uiRoute.post(COST_RATES_PATH, async (c) => {
  if (!c.env?.DATABASE_URL) {
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

uiRoute.get(DASHBOARD_DATA_API_PATH, async (c) => {
  if (!c.env?.DATABASE_URL) {
    return c.json({ error: 'DATABASE_URL not configured' }, 503);
  }

  try {
    const databaseUrl = c.env.DATABASE_URL;
    const [models, earliestDate, savedCostRates] = await Promise.all([
      fetchKnownModels(databaseUrl),
      fetchEarliestUsageDate(databaseUrl),
      fetchCostRates(databaseUrl),
    ]);
    const filters = parseFiltersFromQuery(c.req.query(), earliestDate, models, savedCostRates);
    const { summary, dailyRows } = await loadDashboardData(databaseUrl, filters);
    const hasData = summary.rows.length > 0;

    return c.json({
      filters: serializeFilters(filters),
      models,
      savedCostRates: savedCostRates
        ? {
            defaultRates: savedCostRates.defaultRates,
            modelOverrides: Object.fromEntries(savedCostRates.modelOverrides),
            updatedAt: savedCostRates.updatedAt,
          }
        : null,
      summary,
      payload: hasData ? buildClientPayload(summary, dailyRows, filters) : null,
    });
  } catch (error) {
    const code = error instanceof NeonDbError ? error.code : 'unknown';
    console.error(`Dashboard data API failed (code: ${code ?? 'unknown'})`);
    return c.json({ error: 'Failed to load dashboard data' }, 500);
  }
});

uiRoute.get(MODELS_API_PATH, async (c) => {
  if (!c.env?.DATABASE_URL) {
    return c.json({ error: 'DATABASE_URL not configured' }, 503);
  }

  const backendUrl = await fetchBackendUrl(c.env.DATABASE_URL);
  if (!backendUrl) {
    return c.json({ error: 'Proxy not configured', data: [] }, 503);
  }

  try {
    const response = await fetch(`${backendUrl}/v1/models`);
    const body = await response.text();
    return new Response(body, {
      status: response.status,
      headers: { 'content-type': response.headers.get('content-type') || 'application/json' },
    });
  } catch (error) {
    return c.json(
      { error: 'Backend unavailable', details: String(error), data: [] },
      503,
    );
  }
});
