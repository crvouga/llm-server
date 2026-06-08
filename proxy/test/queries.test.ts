import { afterAll, beforeAll, describe, expect, test } from 'bun:test';
import {
  fetchDailyUsageRows,
  fetchEarliestUsageDate,
  fetchKnownModels,
  fetchUsageRows,
} from '../src/dashboard/db/queries';
import {
  cleanupTestRows,
  createRunId,
  insertLogRow,
  requireDatabaseUrl,
  sentinelModel,
} from './helpers/db';

const runId = createRunId();
let databaseUrl = '';

const modelA = sentinelModel(runId, 'model-a');
const modelB = sentinelModel(runId, 'model-b');

const startDate = '2999-01-01';
const endDate = '2999-01-03';
const day1 = '2999-01-01T12:00:00Z';
const day2 = '2999-01-02T12:00:00Z';
const day3 = '2999-01-03T12:00:00Z';
const outOfRange = '2999-01-04T12:00:00Z';

describe('dashboard query aggregation', () => {
  beforeAll(async () => {
    databaseUrl = requireDatabaseUrl();

    await insertLogRow({
      createdAt: day1,
      model: modelA,
      promptTokens: 100,
      completionTokens: 50,
    });
    await insertLogRow({
      createdAt: day1,
      model: modelA,
      promptTokens: 20,
      completionTokens: 10,
    });
    await insertLogRow({
      createdAt: day2,
      model: modelB,
      promptTokens: 300,
      completionTokens: 200,
    });
    await insertLogRow({
      createdAt: day3,
      model: modelB,
      promptTokens: 1_000_000_000,
      completionTokens: 2_000_000_000,
    });

    // Excluded rows
    await insertLogRow({
      createdAt: day2,
      model: modelA,
      statusCode: 500,
      promptTokens: 999,
      completionTokens: 999,
    });
    await insertLogRow({
      createdAt: day2,
      model: modelA,
      includeUsage: false,
      promptTokens: 999,
      completionTokens: 999,
    });
    await insertLogRow({
      createdAt: day2,
      model: modelA,
      path: '/v1/models',
      promptTokens: 999,
      completionTokens: 999,
    });
    await insertLogRow({
      createdAt: outOfRange,
      model: modelA,
      promptTokens: 999,
      completionTokens: 999,
    });
  });

  afterAll(async () => {
    await cleanupTestRows(runId);
  });

  test('fetchUsageRows groups by model and sums tokens', async () => {
    const rows = await fetchUsageRows(databaseUrl, startDate, endDate);

    const modelARow = rows.find((row) => row.model === modelA);
    const modelBRow = rows.find((row) => row.model === modelB);

    expect(modelARow).toEqual({
      model: modelA,
      requestCount: 2,
      promptTokens: 120,
      completionTokens: 60,
    });
    expect(modelBRow).toEqual({
      model: modelB,
      requestCount: 2,
      promptTokens: 1_000_000_300,
      completionTokens: 2_000_000_200,
    });
  });

  test('fetchDailyUsageRows groups by day and sums tokens', async () => {
    const rows = await fetchDailyUsageRows(databaseUrl, startDate, endDate);

    expect(rows).toEqual([
      {
        day: '2999-01-01',
        promptTokens: 120,
        completionTokens: 60,
        totalTokens: 180,
      },
      {
        day: '2999-01-02',
        promptTokens: 300,
        completionTokens: 200,
        totalTokens: 500,
      },
      {
        day: '2999-01-03',
        promptTokens: 1_000_000_000,
        completionTokens: 2_000_000_000,
        totalTokens: 3_000_000_000,
      },
    ]);
  });

  test('fetchKnownModels includes sentinel models', async () => {
    const models = await fetchKnownModels(databaseUrl);
    expect(models).toContain(modelA);
    expect(models).toContain(modelB);
  });

  test('fetchEarliestUsageDate returns a valid ISO date', async () => {
    const earliest = await fetchEarliestUsageDate(databaseUrl);
    expect(earliest).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});
