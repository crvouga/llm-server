import { describe, expect, test } from 'bun:test';
import { perMillionToPerToken, rowCostUsd } from '../src/dashboard/lib/cost';
import { buildClientPayload, summarizeUsage } from '../src/dashboard/lib/summary';
import type { DashboardFilters, DailyUsageRow, RawModelUsageRow } from '../src/dashboard/types';

function makeFilters(overrides: Partial<DashboardFilters> = {}): DashboardFilters {
  return {
    dateBucket: 'all_time',
    startDate: '2025-01-01',
    endDate: '2025-01-31',
    defaultRates: { inputPerMillion: 1, outputPerMillion: 2 },
    modelCosts: new Map(),
    sortKey: 'totalTokens',
    sortDir: 'desc',
    ...overrides,
  };
}

describe('perMillionToPerToken', () => {
  test('converts per-million rate to per-token rate', () => {
    expect(perMillionToPerToken(1_000_000)).toBe(1);
    expect(perMillionToPerToken(2)).toBe(0.000002);
  });
});

describe('rowCostUsd', () => {
  test('computes cost from prompt and completion tokens', () => {
    const cost = rowCostUsd(1_000_000, 500_000, {
      inputPerMillion: 1,
      outputPerMillion: 2,
    });
    expect(cost).toBeCloseTo(2, 6);
  });

  test('returns zero when both token counts are zero', () => {
    expect(rowCostUsd(0, 0, { inputPerMillion: 1, outputPerMillion: 2 })).toBe(0);
  });
});

describe('summarizeUsage', () => {
  test('returns zero totals for empty input', () => {
    const summary = summarizeUsage([], makeFilters());

    expect(summary.rows).toEqual([]);
    expect(summary.totals).toEqual({
      requestCount: 0,
      promptTokens: 0,
      completionTokens: 0,
      totalTokens: 0,
      estCostUsd: 0,
      modelCount: 0,
    });
  });

  test('sums totals across models', () => {
    const rawRows: RawModelUsageRow[] = [
      { model: 'alpha', requestCount: 2, promptTokens: 100, completionTokens: 50 },
      { model: 'beta', requestCount: 1, promptTokens: 200, completionTokens: 100 },
    ];

    const summary = summarizeUsage(rawRows, makeFilters());

    expect(summary.totals.requestCount).toBe(3);
    expect(summary.totals.promptTokens).toBe(300);
    expect(summary.totals.completionTokens).toBe(150);
    expect(summary.totals.totalTokens).toBe(450);
    expect(summary.totals.modelCount).toBe(2);
  });

  test('computes avgTokensPerRequest and percentOfTotal per row', () => {
    const rawRows: RawModelUsageRow[] = [
      { model: 'alpha', requestCount: 2, promptTokens: 100, completionTokens: 100 },
      { model: 'beta', requestCount: 1, promptTokens: 100, completionTokens: 100 },
    ];

    const summary = summarizeUsage(rawRows, makeFilters());
    const alpha = summary.rows.find((row) => row.model === 'alpha');
    const beta = summary.rows.find((row) => row.model === 'beta');

    expect(alpha?.avgTokensPerRequest).toBe(100);
    expect(beta?.avgTokensPerRequest).toBe(200);
    expect(alpha?.percentOfTotal).toBeCloseTo(50, 5);
    expect(beta?.percentOfTotal).toBeCloseTo(50, 5);
  });

  test('uses per-model rates when configured', () => {
    const rawRows: RawModelUsageRow[] = [
      { model: 'cheap', requestCount: 1, promptTokens: 1_000_000, completionTokens: 0 },
      { model: 'expensive', requestCount: 1, promptTokens: 0, completionTokens: 1_000_000 },
    ];

    const filters = makeFilters({
      modelCosts: new Map([
        ['cheap', { inputPerMillion: 0.5, outputPerMillion: 0.5 }],
        ['expensive', { inputPerMillion: 10, outputPerMillion: 20 }],
      ]),
    });

    const summary = summarizeUsage(rawRows, filters);
    const cheap = summary.rows.find((row) => row.model === 'cheap');
    const expensive = summary.rows.find((row) => row.model === 'expensive');

    expect(cheap?.estCostUsd).toBeCloseTo(0.5, 6);
    expect(expensive?.estCostUsd).toBeCloseTo(20, 6);
    expect(summary.totals.estCostUsd).toBeCloseTo(20.5, 6);
  });

  test('falls back to default rates for unknown models', () => {
    const rawRows: RawModelUsageRow[] = [
      { model: 'unknown-model', requestCount: 1, promptTokens: 1_000_000, completionTokens: 1_000_000 },
    ];

    const summary = summarizeUsage(rawRows, makeFilters());
    expect(summary.rows[0]?.estCostUsd).toBeCloseTo(3, 6);
  });

  test('percentOfTotal across three uneven models sums to 100%', () => {
    const rawRows: RawModelUsageRow[] = [
      { model: 'a', requestCount: 1, promptTokens: 100, completionTokens: 0 },
      { model: 'b', requestCount: 1, promptTokens: 200, completionTokens: 0 },
      { model: 'c', requestCount: 1, promptTokens: 700, completionTokens: 0 },
    ];

    const summary = summarizeUsage(rawRows, makeFilters());
    const percentSum = summary.rows.reduce((sum, row) => sum + row.percentOfTotal, 0);

    expect(percentSum).toBeCloseTo(100, 5);
    expect(summary.rows.find((row) => row.model === 'c')?.percentOfTotal).toBeCloseTo(70, 5);
  });
});

describe('buildClientPayload', () => {
  test('chart arrays align with summary rows and daily totals', () => {
    const filters = makeFilters();
    const rawRows: RawModelUsageRow[] = [
      { model: 'alpha', requestCount: 1, promptTokens: 10, completionTokens: 5 },
    ];
    const summary = summarizeUsage(rawRows, filters);
    const dailyRows: DailyUsageRow[] = [
      { day: '2025-01-01', promptTokens: 10, completionTokens: 5, totalTokens: 15 },
    ];

    const payload = buildClientPayload(summary, dailyRows, filters);

    expect(payload.labels).toEqual(['alpha']);
    expect(payload.totalTokens).toEqual([15]);
    expect(payload.dailyLabels).toEqual(['2025-01-01']);
    expect(payload.dailyTotal).toEqual([15]);
    expect(payload.totals.totalTokens).toBe(15);
  });
});
