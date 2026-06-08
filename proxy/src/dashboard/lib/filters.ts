import { DEFAULT_INPUT_COST_PER_MILLION, DEFAULT_OUTPUT_COST_PER_MILLION } from '../constants';
import type { DashboardFilters, ModelCostRates } from '../types';
import { fetchEarliestUsageDate } from '../db/queries';
import { resolveDateRange } from './date-range';
import { todayIsoDate } from './format';

export async function defaultFilters(
  databaseUrl: string,
  models: string[],
): Promise<DashboardFilters> {
  const defaultRates: ModelCostRates = {
    inputPerMillion: DEFAULT_INPUT_COST_PER_MILLION,
    outputPerMillion: DEFAULT_OUTPUT_COST_PER_MILLION,
  };

  const earliestDate = await fetchEarliestUsageDate(databaseUrl);
  const { startDate, endDate } = resolveDateRange('all_time', earliestDate);

  return {
    dateBucket: 'all_time',
    startDate,
    endDate,
    defaultRates,
    modelCosts: new Map(models.map((model) => [model, { ...defaultRates }])),
    sortKey: 'totalTokens',
    sortDir: 'desc',
  };
}

export function emptyFilters(): DashboardFilters {
  const today = todayIsoDate();
  return {
    dateBucket: 'all_time',
    startDate: today,
    endDate: today,
    defaultRates: {
      inputPerMillion: DEFAULT_INPUT_COST_PER_MILLION,
      outputPerMillion: DEFAULT_OUTPUT_COST_PER_MILLION,
    },
    modelCosts: new Map(),
    sortKey: 'totalTokens',
    sortDir: 'desc',
  };
}
