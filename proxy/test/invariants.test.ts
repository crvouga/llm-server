import { afterAll, beforeAll, describe, expect, test } from 'bun:test';
import { loadDashboardData } from '../src/dashboard/db/load';
import { fetchDailyUsageRows, fetchUsageRows } from '../src/dashboard/db/queries';
import { buildClientPayload } from '../src/dashboard/lib/summary';
import { computeGenerationTps, computeOverallTps, isValidTimingRow } from '../src/dashboard/lib/timing';
import type { DashboardFilters } from '../src/dashboard/types';
import {
  cleanupTestRows,
  createRunId,
  insertLogRows,
  requireDatabaseUrl,
  sentinelModel,
  sumDailyRows,
  sumUsageRows,
} from './helpers/db';

const runId = createRunId();
let databaseUrl = '';
const extraIds: string[] = [];

const modelA = sentinelModel(runId, 'inv-a');
const modelB = sentinelModel(runId, 'inv-b');

const startDate = '2999-02-10';
const endDate = '2999-02-11';
const day1 = '2999-02-10T10:00:00Z';
const day2 = '2999-02-11T15:00:00Z';

const filters: DashboardFilters = {
  dateBucket: 'all_time',
  startDate,
  endDate,
  defaultRates: { inputPerMillion: 1, outputPerMillion: 2 },
  modelCosts: new Map(),
  sortKey: 'totalTokens',
  sortDir: 'desc',
};

describe('usage tracking invariants', () => {
  beforeAll(async () => {
    databaseUrl = requireDatabaseUrl();
    extraIds.push(
      ...(await insertLogRows([
        {
          createdAt: day1,
          model: modelA,
          promptTokens: 100,
          completionTokens: 40,
          durationMs: 1000,
          ttftMs: 200,
        },
        {
          createdAt: day1,
          model: modelA,
          promptTokens: 50,
          completionTokens: 10,
          durationMs: 500,
          ttftMs: 100,
        },
        {
          createdAt: day2,
          model: modelB,
          promptTokens: 200,
          completionTokens: 80,
          durationMs: 800,
          ttftMs: null,
        },
      ])),
    );
  });

  afterAll(async () => {
    await cleanupTestRows(runId, extraIds);
  });

  test('fetchUsageRows totals match fetchDailyUsageRows totals', async () => {
    const usageRows = await fetchUsageRows(databaseUrl, startDate, endDate);
    const dailyRows = await fetchDailyUsageRows(databaseUrl, startDate, endDate);

    const usageTotals = sumUsageRows(usageRows);
    const dailyTotals = sumDailyRows(dailyRows);

    expect(usageTotals.requestCount).toBe(3);
    expect(usageTotals.promptTokens).toBe(350);
    expect(usageTotals.completionTokens).toBe(130);
    expect(dailyTotals.promptTokens).toBe(usageTotals.promptTokens);
    expect(dailyTotals.completionTokens).toBe(usageTotals.completionTokens);
    expect(dailyTotals.totalTokens).toBe(usageTotals.promptTokens + usageTotals.completionTokens);
    expect(usageTotals.timedCompletionTokens).toBe(130);
    expect(usageTotals.totalDurationMs).toBe(2300);
    expect(usageTotals.generationCompletionTokens).toBe(50);
    expect(usageTotals.totalGenerationMs).toBe(1200);
  });

  test('loadDashboardData summary totals match raw query totals', async () => {
    const usageRows = await fetchUsageRows(databaseUrl, startDate, endDate);
    const usageTotals = sumUsageRows(usageRows);
    const { summary, dailyRows } = await loadDashboardData(databaseUrl, filters);

    expect(summary.totals.requestCount).toBe(usageTotals.requestCount);
    expect(summary.totals.promptTokens).toBe(usageTotals.promptTokens);
    expect(summary.totals.completionTokens).toBe(usageTotals.completionTokens);
    expect(summary.totals.totalTokens).toBe(
      usageTotals.promptTokens + usageTotals.completionTokens,
    );
    expect(summary.totals.modelCount).toBe(2);
    expect(summary.totals.avgOverallTps).toBeCloseTo(130 / 2.3, 2);
    expect(summary.totals.avgGenerationTps).toBeCloseTo(50 / 1.2, 2);
    expect(dailyRows.length).toBe(2);
  });

  test('buildClientPayload arrays match summary rows', async () => {
    const { summary, dailyRows } = await loadDashboardData(databaseUrl, filters);
    const payload = buildClientPayload(summary, dailyRows, filters);

    expect(payload.labels).toEqual(summary.rows.map((row) => row.model));
    expect(payload.totalTokens).toEqual(summary.rows.map((row) => row.totalTokens));
    expect(payload.promptTokens).toEqual(summary.rows.map((row) => row.promptTokens));
    expect(payload.completionTokens).toEqual(summary.rows.map((row) => row.completionTokens));
    expect(payload.estCostUsd).toEqual(summary.rows.map((row) => row.estCostUsd));
    expect(payload.totals).toEqual(summary.totals);
    expect(payload.dailyTotal).toEqual(dailyRows.map((row) => row.totalTokens));
  });

  test('summary TPS matches raw query timing aggregates', async () => {
    const usageRows = await fetchUsageRows(databaseUrl, startDate, endDate);
    const usageTotals = sumUsageRows(usageRows);
    const { summary } = await loadDashboardData(databaseUrl, filters);

    expect(summary.totals.avgOverallTps).toBe(
      computeOverallTps(usageTotals.timedCompletionTokens, usageTotals.totalDurationMs),
    );
    expect(summary.totals.avgGenerationTps).toBe(
      computeGenerationTps(
        usageTotals.generationCompletionTokens,
        usageTotals.totalGenerationMs,
      ),
    );
  });

  test('blocking model has overall TPS but null generation TPS', async () => {
    const { summary } = await loadDashboardData(databaseUrl, filters);
    const blockingRow = summary.rows.find((row) => row.model === modelB);

    expect(blockingRow?.avgOverallTps).toBeCloseTo(80 / 0.8, 2);
    expect(blockingRow?.avgGenerationTps).toBeNull();
  });

  test('every raw usage row satisfies timing invariants', async () => {
    const usageRows = await fetchUsageRows(databaseUrl, startDate, endDate);

    for (const row of usageRows) {
      expect(isValidTimingRow(row)).toBe(true);
    }
  });

  test('percentOfTotal sums to 100% and totalTokens equals prompt plus completion', async () => {
    const { summary } = await loadDashboardData(databaseUrl, filters);
    const percentSum = summary.rows.reduce((sum, row) => sum + row.percentOfTotal, 0);

    expect(percentSum).toBeCloseTo(100, 5);
    for (const row of summary.rows) {
      expect(row.totalTokens).toBe(row.promptTokens + row.completionTokens);
    }
  });
});
