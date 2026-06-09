import type { DailyUsageRow, ModelCostRates } from '../types';
import { rowCostUsd } from './cost';

export interface InvestmentMetricsInput {
  investmentUsd: number | null;
  projectedDailySpendUsd: number | null;
  totalSavingsToDateUsd: number;
  earliestUsageDate: string;
  today: string;
  dailyRows: DailyUsageRow[];
  defaultRates: ModelCostRates;
}

export interface InvestmentMetrics {
  investmentUsd: number | null;
  projectedDailySpendUsd: number | null;
  historicalAverageDailySpendUsd: number | null;
  totalSavingsToDateUsd: number;
  remainingInvestmentUsd: number;
  effectiveDailySpendUsd: number | null;
  projectedBreakEvenDate: string | null;
  actualBreakEvenDate: string | null;
  hasBrokenEven: boolean;
  calendarDays: number;
  today: string;
}

export function calendarDaysInclusive(startDate: string, endDate: string): number {
  const startMs = Date.parse(`${startDate}T00:00:00Z`);
  const endMs = Date.parse(`${endDate}T00:00:00Z`);
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs < startMs) {
    return 1;
  }
  return Math.max(1, Math.floor((endMs - startMs) / 86_400_000) + 1);
}

export function addCalendarDays(isoDate: string, days: number): string {
  const [year, month, day] = isoDate.split('-').map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function dailyRowCostUsd(row: DailyUsageRow, rates: ModelCostRates): number {
  return rowCostUsd(row.promptTokens, row.completionTokens, rates);
}

function findActualBreakEvenDate(
  investmentUsd: number,
  dailyRows: DailyUsageRow[],
  defaultRates: ModelCostRates,
): string | null {
  let cumulative = 0;
  for (const row of dailyRows) {
    cumulative += dailyRowCostUsd(row, defaultRates);
    if (cumulative >= investmentUsd) {
      return row.day;
    }
  }
  return null;
}

export function computeInvestmentMetrics(input: InvestmentMetricsInput): InvestmentMetrics {
  const {
    investmentUsd,
    projectedDailySpendUsd,
    totalSavingsToDateUsd,
    earliestUsageDate,
    today,
    dailyRows,
    defaultRates,
  } = input;

  const calendarDays = calendarDaysInclusive(earliestUsageDate, today);
  const historicalAverageDailySpendUsd =
    totalSavingsToDateUsd > 0 ? totalSavingsToDateUsd / calendarDays : null;
  const effectiveDailySpendUsd = projectedDailySpendUsd ?? historicalAverageDailySpendUsd;
  const normalizedInvestment = investmentUsd ?? 0;
  const remainingInvestmentUsd = Math.max(0, normalizedInvestment - totalSavingsToDateUsd);
  const hasBrokenEven =
    investmentUsd != null && investmentUsd > 0 && totalSavingsToDateUsd >= investmentUsd;

  let projectedBreakEvenDate: string | null = null;
  if (
    investmentUsd != null &&
    investmentUsd > 0 &&
    !hasBrokenEven &&
    effectiveDailySpendUsd != null &&
    effectiveDailySpendUsd > 0
  ) {
    const daysUntilBreakEven = Math.ceil(remainingInvestmentUsd / effectiveDailySpendUsd);
    projectedBreakEvenDate = addCalendarDays(today, daysUntilBreakEven);
  }

  const actualBreakEvenDate =
    investmentUsd != null && investmentUsd > 0
      ? findActualBreakEvenDate(investmentUsd, dailyRows, defaultRates)
      : null;

  return {
    investmentUsd,
    projectedDailySpendUsd,
    historicalAverageDailySpendUsd,
    totalSavingsToDateUsd,
    remainingInvestmentUsd,
    effectiveDailySpendUsd,
    projectedBreakEvenDate,
    actualBreakEvenDate,
    hasBrokenEven,
    calendarDays,
    today,
  };
}
