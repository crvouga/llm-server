import { afterAll, beforeAll, describe, expect, test } from 'bun:test';
import { fetchUsageRows } from '../src/dashboard/db/queries';
import { computeGenerationTps, computeOverallTps } from '../src/dashboard/lib/timing';
import { summarizeUsage } from '../src/dashboard/lib/summary';
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

const modelMixed = sentinelModel(runId, 'mixed-legacy');
const modelZero = sentinelModel(runId, 'zero-completion');
const modelNoGen = sentinelModel(runId, 'no-gen-window');
const modelHybrid = sentinelModel(runId, 'hybrid-stream');

const startDate = '2999-03-01';
const endDate = '2999-03-01';
const day = '2999-03-01T12:00:00Z';

const filters: DashboardFilters = {
  dateBucket: 'all_time',
  startDate,
  endDate,
  defaultRates: { inputPerMillion: 1, outputPerMillion: 2 },
  modelCosts: new Map(),
  sortKey: 'totalTokens',
  sortDir: 'desc',
};

describe('dashboard timing query edge cases', () => {
  beforeAll(async () => {
    databaseUrl = requireDatabaseUrl();

    await insertLogRows([
      {
        createdAt: day,
        model: modelMixed,
        promptTokens: 10,
        completionTokens: 30,
        durationMs: null,
        ttftMs: null,
      },
      {
        createdAt: day,
        model: modelMixed,
        promptTokens: 5,
        completionTokens: 50,
        durationMs: 1000,
        ttftMs: 200,
      },
      {
        createdAt: day,
        model: modelZero,
        promptTokens: 100,
        completionTokens: 0,
        durationMs: 500,
        ttftMs: null,
      },
      {
        createdAt: day,
        model: modelNoGen,
        promptTokens: 0,
        completionTokens: 25,
        durationMs: 100,
        ttftMs: 100,
      },
      {
        createdAt: day,
        model: modelHybrid,
        promptTokens: 0,
        completionTokens: 40,
        durationMs: 400,
        ttftMs: null,
      },
      {
        createdAt: day,
        model: modelHybrid,
        promptTokens: 0,
        completionTokens: 20,
        durationMs: 200,
        ttftMs: 50,
      },
    ]);
  });

  afterAll(async () => {
    await cleanupTestRows(runId);
  });

  test('mixed legacy and timed rows use timed subset for overall TPS', async () => {
    const rows = await fetchUsageRows(databaseUrl, startDate, endDate);
    const mixed = rows.find((row) => row.model === modelMixed);

    expect(mixed).toEqual({
      model: modelMixed,
      requestCount: 2,
      promptTokens: 15,
      completionTokens: 80,
      timedCompletionTokens: 50,
      totalDurationMs: 1000,
      generationCompletionTokens: 50,
      totalGenerationMs: 800,
    });
    expect(computeOverallTps(mixed!.timedCompletionTokens, mixed!.totalDurationMs)).toBeCloseTo(
      50,
      5,
    );
  });

  test('zero completion tokens with timing yields overall TPS of zero', async () => {
    const rows = await fetchUsageRows(databaseUrl, startDate, endDate);
    const zero = rows.find((row) => row.model === modelZero);
    const summary = summarizeUsage(rows, filters);
    const summaryRow = summary.rows.find((row) => row.model === modelZero);

    expect(zero?.timedCompletionTokens).toBe(0);
    expect(zero?.totalDurationMs).toBe(500);
    expect(computeOverallTps(zero!.timedCompletionTokens, zero!.totalDurationMs)).toBe(0);
    expect(summaryRow?.avgOverallTps).toBe(0);
    expect(summaryRow?.avgGenerationTps).toBeNull();
  });

  test('duration equal to ttft excludes row from generation aggregates', async () => {
    const rows = await fetchUsageRows(databaseUrl, startDate, endDate);
    const noGen = rows.find((row) => row.model === modelNoGen);
    const summary = summarizeUsage(rows, filters);
    const summaryRow = summary.rows.find((row) => row.model === modelNoGen);

    expect(noGen).toMatchObject({
      completionTokens: 25,
      timedCompletionTokens: 25,
      totalDurationMs: 100,
      generationCompletionTokens: 0,
      totalGenerationMs: 0,
    });
    expect(computeOverallTps(noGen!.timedCompletionTokens, noGen!.totalDurationMs)).toBeCloseTo(
      250,
      5,
    );
    expect(summaryRow?.avgOverallTps).toBeCloseTo(250, 5);
    expect(summaryRow?.avgGenerationTps).toBeNull();
  });

  test('hybrid blocking and streaming rows split overall vs generation TPS', async () => {
    const rows = await fetchUsageRows(databaseUrl, startDate, endDate);
    const hybrid = rows.find((row) => row.model === modelHybrid);
    const summary = summarizeUsage(rows, filters);
    const summaryRow = summary.rows.find((row) => row.model === modelHybrid);

    expect(hybrid).toEqual({
      model: modelHybrid,
      requestCount: 2,
      promptTokens: 0,
      completionTokens: 60,
      timedCompletionTokens: 60,
      totalDurationMs: 600,
      generationCompletionTokens: 20,
      totalGenerationMs: 150,
    });
    expect(computeOverallTps(hybrid!.timedCompletionTokens, hybrid!.totalDurationMs)).toBeCloseTo(
      100,
      5,
    );
    expect(
      computeGenerationTps(hybrid!.generationCompletionTokens, hybrid!.totalGenerationMs),
    ).toBeCloseTo(20 / 0.15, 2);
    expect(summaryRow?.avgOverallTps).toBeCloseTo(100, 5);
    expect(summaryRow?.avgGenerationTps).toBeCloseTo(20 / 0.15, 2);
  });
});
