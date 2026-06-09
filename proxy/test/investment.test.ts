import { describe, expect, test } from 'bun:test';
import {
  addCalendarDays,
  calendarDaysInclusive,
  computeInvestmentMetrics,
} from '../src/dashboard/lib/investment';

describe('investment metrics', () => {
  test('calendarDaysInclusive counts both endpoints', () => {
    expect(calendarDaysInclusive('2026-06-01', '2026-06-01')).toBe(1);
    expect(calendarDaysInclusive('2026-06-01', '2026-06-03')).toBe(3);
  });

  test('addCalendarDays advances by whole days', () => {
    expect(addCalendarDays('2026-06-01', 10)).toBe('2026-06-11');
  });

  test('computes historical average and projected break-even date', () => {
    const metrics = computeInvestmentMetrics({
      investmentUsd: 100,
      projectedDailySpendUsd: null,
      totalSavingsToDateUsd: 30,
      earliestUsageDate: '2026-06-01',
      today: '2026-06-10',
      dailyRows: [
        { day: '2026-06-05', promptTokens: 1_000_000, completionTokens: 0, totalTokens: 1_000_000 },
        { day: '2026-06-08', promptTokens: 2_000_000, completionTokens: 0, totalTokens: 2_000_000 },
      ],
      defaultRates: { inputPerMillion: 1, outputPerMillion: 2 },
    });

    expect(metrics.historicalAverageDailySpendUsd).toBeCloseTo(30 / 10, 5);
    expect(metrics.effectiveDailySpendUsd).toBeCloseTo(3, 5);
    expect(metrics.remainingInvestmentUsd).toBe(70);
    expect(metrics.projectedBreakEvenDate).toBe('2026-07-04');
    expect(metrics.hasBrokenEven).toBe(false);
  });

  test('marks break-even when savings exceed investment', () => {
    const metrics = computeInvestmentMetrics({
      investmentUsd: 50,
      projectedDailySpendUsd: 5,
      totalSavingsToDateUsd: 75,
      earliestUsageDate: '2026-06-01',
      today: '2026-06-10',
      dailyRows: [
        { day: '2026-06-02', promptTokens: 25_000_000, completionTokens: 0, totalTokens: 25_000_000 },
        { day: '2026-06-05', promptTokens: 50_000_000, completionTokens: 0, totalTokens: 50_000_000 },
      ],
      defaultRates: { inputPerMillion: 1, outputPerMillion: 2 },
    });

    expect(metrics.hasBrokenEven).toBe(true);
    expect(metrics.remainingInvestmentUsd).toBe(0);
    expect(metrics.projectedBreakEvenDate).toBeNull();
    expect(metrics.actualBreakEvenDate).toBe('2026-06-05');
  });

  test('uses manual projected daily spend override', () => {
    const metrics = computeInvestmentMetrics({
      investmentUsd: 100,
      projectedDailySpendUsd: 10,
      totalSavingsToDateUsd: 0,
      earliestUsageDate: '2026-06-01',
      today: '2026-06-01',
      dailyRows: [],
      defaultRates: { inputPerMillion: 1, outputPerMillion: 2 },
    });

    expect(metrics.effectiveDailySpendUsd).toBe(10);
    expect(metrics.projectedBreakEvenDate).toBe('2026-06-11');
  });
});
