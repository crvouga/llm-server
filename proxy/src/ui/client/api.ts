import type { SavedCostRates } from '../../dashboard/db/cost-rates';
import type { DashboardFilters, DashboardPayload, UsageSummary } from '../../dashboard/types';
import {
  COST_RATES_PATH,
  DASHBOARD_DATA_API_PATH,
  MODELS_API_PATH,
} from '../../shared/constants';
import type { ModelCostRates } from '../../dashboard/types';

export interface SerializedDashboardFilters {
  dateBucket: DashboardFilters['dateBucket'];
  startDate: string;
  endDate: string;
  defaultRates: ModelCostRates;
  modelCosts: Record<string, ModelCostRates>;
  sortKey: DashboardFilters['sortKey'];
  sortDir: DashboardFilters['sortDir'];
}

export interface SerializedSavedCostRates {
  defaultRates: ModelCostRates;
  modelOverrides: Record<string, ModelCostRates>;
  updatedAt: string | null;
}

export interface DashboardDataResponse {
  filters: SerializedDashboardFilters;
  models: string[];
  savedCostRates: SerializedSavedCostRates | null;
  summary: UsageSummary | null;
  payload: DashboardPayload | null;
  error?: string;
}

export async function fetchDashboardData(search: string): Promise<DashboardDataResponse> {
  const query = search.startsWith('?') ? search : search ? `?${search}` : '';
  const response = await fetch(`${DASHBOARD_DATA_API_PATH}${query}`);

  if (!response.ok) {
    let details = `Request failed (${response.status})`;
    try {
      const json = (await response.json()) as { error?: string };
      if (json.error) {
        details = json.error;
      }
    } catch {
      const text = await response.text();
      if (text) {
        details = text;
      }
    }
    throw new Error(details);
  }

  return (await response.json()) as DashboardDataResponse;
}

export async function fetchModels(): Promise<string[]> {
  const response = await fetch(MODELS_API_PATH);
  if (!response.ok) {
    return [];
  }

  try {
    const json = (await response.json()) as { data?: Array<{ id?: string }> };
    return (json.data ?? [])
      .map((entry) => entry.id)
      .filter((id): id is string => typeof id === 'string' && id.length > 0);
  } catch {
    return [];
  }
}

export async function saveCostRates(body: {
  defaultRates: ModelCostRates;
  modelCosts: Record<string, Partial<ModelCostRates>>;
}): Promise<SavedCostRates & { modelOverrides: Record<string, ModelCostRates> }> {
  const response = await fetch(COST_RATES_PATH, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    throw new Error('Failed to save cost rates');
  }

  const json = (await response.json()) as {
    defaultRates: ModelCostRates;
    modelOverrides: Record<string, ModelCostRates>;
    updatedAt: string | null;
  };

  return {
    defaultRates: json.defaultRates,
    modelOverrides: json.modelOverrides,
    updatedAt: json.updatedAt,
  };
}
