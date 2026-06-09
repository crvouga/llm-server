import { fetchCostRates, defaultSavedCostRates } from './cost-rates';
import { fetchInvestmentConfig } from './investment';
import { loadDashboardData } from './load';
import { fetchEarliestUsageDate, fetchKnownModels } from './queries';
import { computeInvestmentMetrics, type InvestmentMetrics } from '../lib/investment';
import { todayIsoDate } from '../lib/format';
import { resolveDateRange } from '../lib/date-range';
import type { DashboardFilters } from '../types';

export async function loadInvestmentMetrics(databaseUrl: string): Promise<InvestmentMetrics> {
  const [savedConfig, earliestDate, savedCostRates, models] = await Promise.all([
    fetchInvestmentConfig(databaseUrl),
    fetchEarliestUsageDate(databaseUrl),
    fetchCostRates(databaseUrl),
    fetchKnownModels(databaseUrl),
  ]);

  const today = todayIsoDate();
  const savedRates = savedCostRates ?? defaultSavedCostRates();
  const { startDate, endDate } = resolveDateRange('all_time', earliestDate, today);
  const defaultRates = savedRates.defaultRates;
  const modelCosts = new Map<string, typeof defaultRates>();
  for (const model of models) {
    modelCosts.set(model, savedRates.modelOverrides.get(model) ?? defaultRates);
  }

  const filters: DashboardFilters = {
    dateBucket: 'all_time',
    startDate,
    endDate,
    defaultRates,
    modelCosts,
    sortKey: 'totalTokens',
    sortDir: 'desc',
  };

  const { summary, dailyRows } = await loadDashboardData(databaseUrl, filters);

  return computeInvestmentMetrics({
    investmentUsd: savedConfig.investmentUsd,
    projectedDailySpendUsd: savedConfig.projectedDailySpendUsd,
    totalSavingsToDateUsd: summary.totals.estCostUsd,
    earliestUsageDate: earliestDate,
    today,
    dailyRows,
    defaultRates,
  });
}
