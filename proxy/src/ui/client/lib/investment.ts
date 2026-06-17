function addCalendarDays(isoDate: string, days: number) {
  const [year, month, day] = isoDate.split('-').map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

export function computeBreakEvenPreview(
  investmentUsd: string | number | null | undefined,
  projectedDailySpendUsd: string | number | null | undefined,
  metrics: {
    totalSavingsToDateUsd?: number;
    historicalAverageDailySpendUsd?: number | null;
    today?: string;
    actualBreakEvenDate?: string | null;
  } | null,
) {
  if (!metrics) return null;
  const investment = investmentUsd === '' || investmentUsd == null ? null : Number(investmentUsd);
  const projected =
    projectedDailySpendUsd === '' || projectedDailySpendUsd == null
      ? null
      : Number(projectedDailySpendUsd);
  const normalizedInvestment = Number.isFinite(investment) && investment! >= 0 ? investment : null;
  const normalizedProjected = Number.isFinite(projected) && projected! >= 0 ? projected : null;
  const totalSavings = metrics.totalSavingsToDateUsd ?? 0;
  const historicalAverage = metrics.historicalAverageDailySpendUsd;
  const effectiveDailySpend = normalizedProjected ?? historicalAverage;
  const remaining = Math.max(0, (normalizedInvestment ?? 0) - totalSavings);
  const hasBrokenEven =
    normalizedInvestment != null && normalizedInvestment > 0 && totalSavings >= normalizedInvestment;

  let projectedBreakEvenDate: string | null = null;
  if (
    normalizedInvestment != null &&
    normalizedInvestment > 0 &&
    !hasBrokenEven &&
    effectiveDailySpend != null &&
    effectiveDailySpend > 0
  ) {
    projectedBreakEvenDate = addCalendarDays(
      metrics.today || new Date().toISOString().slice(0, 10),
      Math.ceil(remaining / effectiveDailySpend),
    );
  }

  return {
    investmentUsd: normalizedInvestment,
    projectedDailySpendUsd: normalizedProjected,
    effectiveDailySpendUsd: effectiveDailySpend,
    remainingInvestmentUsd: remaining,
    hasBrokenEven,
    projectedBreakEvenDate,
    actualBreakEvenDate: metrics.actualBreakEvenDate,
    totalSavingsToDateUsd: totalSavings,
    historicalAverageDailySpendUsd: historicalAverage,
  };
}
