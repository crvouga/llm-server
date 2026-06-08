import { afterAll, beforeAll, describe, expect, test } from 'bun:test';
import { loadDashboardData } from '../src/dashboard/db/load';
import type { DashboardFilters } from '../src/dashboard/types';
import {
  cleanupTestRows,
  createRunId,
  insertLogRows,
  requireDatabaseUrl,
  sentinelModel,
} from './helpers/db';

const runId = createRunId();
let databaseUrl = '';
const extraIds: string[] = [];

const modelA = sentinelModel(runId, 'load-a');
const modelB = sentinelModel(runId, 'load-b');

const startDate = '2999-02-20';
const endDate = '2999-02-21';

describe('loadDashboardData integration', () => {
  beforeAll(async () => {
    databaseUrl = requireDatabaseUrl();
    extraIds.push(
      ...(await insertLogRows([
        {
          createdAt: '2999-02-20T08:00:00Z',
          model: modelA,
          promptTokens: 1000,
          completionTokens: 500,
        },
        {
          createdAt: '2999-02-20T09:00:00Z',
          model: modelB,
          promptTokens: 200,
          completionTokens: 100,
        },
        {
          createdAt: '2999-02-21T08:00:00Z',
          model: modelA,
          promptTokens: 50,
          completionTokens: 25,
        },
      ])),
    );
  });

  afterAll(async () => {
    await cleanupTestRows(runId, extraIds);
  });

  test('returns expected summary and daily rows for date range', async () => {
    const filters: DashboardFilters = {
      dateBucket: 'all_time',
      startDate,
      endDate,
      defaultRates: { inputPerMillion: 1, outputPerMillion: 2 },
      modelCosts: new Map(),
      sortKey: 'totalTokens',
      sortDir: 'desc',
    };

    const { summary, dailyRows } = await loadDashboardData(databaseUrl, filters);

    expect(summary.totals.requestCount).toBe(3);
    expect(summary.totals.promptTokens).toBe(1250);
    expect(summary.totals.completionTokens).toBe(625);
    expect(summary.totals.totalTokens).toBe(1875);
    expect(summary.totals.estCostUsd).toBeCloseTo(0.0025, 10);
    expect(summary.totals.modelCount).toBe(2);

    expect(summary.rows.find((row) => row.model === modelA)).toMatchObject({
      requestCount: 2,
      promptTokens: 1050,
      completionTokens: 525,
      totalTokens: 1575,
    });

    expect(summary.rows.find((row) => row.model === modelB)).toMatchObject({
      requestCount: 1,
      promptTokens: 200,
      completionTokens: 100,
      totalTokens: 300,
    });

    expect(dailyRows).toEqual([
      {
        day: '2999-02-20',
        promptTokens: 1200,
        completionTokens: 600,
        totalTokens: 1800,
      },
      {
        day: '2999-02-21',
        promptTokens: 50,
        completionTokens: 25,
        totalTokens: 75,
      },
    ]);
  });
});
