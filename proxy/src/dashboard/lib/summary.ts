import { CHART_COLORS } from '../constants';
import type {
  DailyUsageRow,
  DashboardFilters,
  DashboardPayload,
  ModelUsageRow,
  RawModelUsageRow,
  UsageSummary,
} from '../types';
import { rowCostUsd, rowRates } from './cost';

export function summarizeUsage(
  rawRows: RawModelUsageRow[],
  filters: DashboardFilters,
): UsageSummary {
  let requestCount = 0;
  let promptTokens = 0;
  let completionTokens = 0;
  let estCostUsd = 0;

  const rows: ModelUsageRow[] = rawRows.map((row) => {
    const totalTokens = row.promptTokens + row.completionTokens;
    requestCount += row.requestCount;
    promptTokens += row.promptTokens;
    completionTokens += row.completionTokens;
    const cost = rowCostUsd(row.promptTokens, row.completionTokens, rowRates(filters, row.model));
    estCostUsd += cost;
    return {
      ...row,
      totalTokens,
      avgTokensPerRequest: row.requestCount > 0 ? totalTokens / row.requestCount : 0,
      percentOfTotal: 0,
      estCostUsd: cost,
    };
  });

  const grandTotal = promptTokens + completionTokens;
  for (const row of rows) {
    row.percentOfTotal = grandTotal > 0 ? (row.totalTokens / grandTotal) * 100 : 0;
  }

  return {
    rows,
    totals: {
      requestCount,
      promptTokens,
      completionTokens,
      totalTokens: grandTotal,
      estCostUsd,
      modelCount: rows.length,
    },
  };
}

export function buildClientPayload(
  summary: UsageSummary,
  dailyRows: DailyUsageRow[],
  filters: DashboardFilters,
): DashboardPayload {
  const labels = summary.rows.map((r) => r.model);
  return {
    models: labels,
    labels,
    totalTokens: summary.rows.map((r) => r.totalTokens),
    promptTokens: summary.rows.map((r) => r.promptTokens),
    completionTokens: summary.rows.map((r) => r.completionTokens),
    estCostUsd: summary.rows.map((r) => r.estCostUsd),
    dailyLabels: dailyRows.map((r) => r.day),
    dailyPrompt: dailyRows.map((r) => r.promptTokens),
    dailyCompletion: dailyRows.map((r) => r.completionTokens),
    dailyTotal: dailyRows.map((r) => r.totalTokens),
    colors: CHART_COLORS,
    rows: summary.rows,
    totals: summary.totals,
    sortKey: filters.sortKey,
    sortDir: filters.sortDir,
  };
}
