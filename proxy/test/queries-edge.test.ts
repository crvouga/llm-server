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
  insertLogRows,
  requireDatabaseUrl,
  sentinelModel,
} from './helpers/db';

const runId = createRunId();
let databaseUrl = '';
const extraIds: string[] = [];

const modelOk = sentinelModel(runId, 'ok');
const modelMulti = sentinelModel(runId, 'multi');
const modelFailed = sentinelModel(runId, 'failed');
const modelUnknown = sentinelModel(runId, 'unknown-body');

const startDate = '2999-02-01';
const endDate = '2999-02-03';
const day1Start = '2999-02-01T00:00:00Z';
const day1Mid = '2999-02-01T12:00:00Z';
const day2Mid = '2999-02-02T12:00:00Z';
const day3End = '2999-02-03T23:59:59Z';
const day4 = '2999-02-04T12:00:00Z';

describe('dashboard query edge cases', () => {
  beforeAll(async () => {
    databaseUrl = requireDatabaseUrl();

    extraIds.push(
      ...(await insertLogRows([
        { createdAt: day1Mid, model: modelOk, statusCode: 200, promptTokens: 10, completionTokens: 5 },
        { createdAt: day1Mid, model: modelOk, statusCode: 299, promptTokens: 20, completionTokens: 10 },
        { createdAt: day2Mid, model: modelMulti, promptTokens: 100, completionTokens: 50 },
        { createdAt: day2Mid, model: modelMulti, promptTokens: 200, completionTokens: 100 },
        { createdAt: day3End, model: modelOk, promptTokens: 5, completionTokens: 2 },
        { createdAt: day1Mid, model: modelOk, promptTokens: 0, completionTokens: 0 },
        {
          createdAt: day2Mid,
          model: modelOk,
          responseBody: { usage: { prompt_tokens: null, completion_tokens: 15 } },
        },
        {
          createdAt: day2Mid,
          model: modelOk,
          responseBody: { usage: { prompt_tokens: 7 } },
        },
        { createdAt: day2Mid, model: modelOk, responseBody: { usage: {} } },
        {
          createdAt: day2Mid,
          model: modelUnknown,
          requestBody: { messages: [] },
        },
        { createdAt: day1Mid, model: modelOk, statusCode: 199, promptTokens: 999, completionTokens: 999 },
        { createdAt: day1Mid, model: modelOk, statusCode: 300, promptTokens: 999, completionTokens: 999 },
        { createdAt: day2Mid, model: modelOk, statusCode: 302, promptTokens: 999, completionTokens: 999 },
        { createdAt: day4, model: modelOk, promptTokens: 999, completionTokens: 999 },
        { createdAt: day2Mid, model: modelFailed, statusCode: 500, promptTokens: 50, completionTokens: 25 },
      ])),
    );
  });

  afterAll(async () => {
    await cleanupTestRows(runId, extraIds);
  });

  test('includes 200 and 299, excludes 199 and 300', async () => {
    const rows = await fetchUsageRows(databaseUrl, startDate, endDate);
    const ok = rows.find((row) => row.model === modelOk);

    expect(ok?.requestCount).toBe(7);
    expect(ok?.promptTokens).toBe(42);
    expect(ok?.completionTokens).toBe(32);
  });

  test('excludes 3xx redirect responses', async () => {
    const rows = await fetchUsageRows(databaseUrl, startDate, endDate);
    const totalRequests = rows.reduce((sum, row) => sum + row.requestCount, 0);
    expect(totalRequests).toBe(10);
  });

  test('accumulates multiple rows for the same model', async () => {
    const rows = await fetchUsageRows(databaseUrl, startDate, endDate);
    const multi = rows.find((row) => row.model === modelMulti);

    expect(multi).toEqual({
      model: modelMulti,
      requestCount: 2,
      promptTokens: 300,
      completionTokens: 150,
      timedCompletionTokens: 0,
      totalDurationMs: 0,
      generationCompletionTokens: 0,
      totalGenerationMs: 0,
    });
  });

  test('groups missing request model as unknown', async () => {
    const rows = await fetchUsageRows(databaseUrl, startDate, endDate);
    const unknown = rows.find((row) => row.model === 'unknown');

    expect(unknown).toEqual({
      model: 'unknown',
      requestCount: 1,
      promptTokens: 0,
      completionTokens: 0,
      timedCompletionTokens: 0,
      totalDurationMs: 0,
      generationCompletionTokens: 0,
      totalGenerationMs: 0,
    });
  });

  test('coalesces null or missing usage token fields to zero', async () => {
    const rows = await fetchUsageRows(databaseUrl, startDate, endDate);
    const ok = rows.find((row) => row.model === modelOk);

    expect(ok?.promptTokens).toBe(42);
    expect(ok?.completionTokens).toBe(32);
  });

  test('single-day range only includes that day', async () => {
    const rows = await fetchUsageRows(databaseUrl, '2999-02-02', '2999-02-02');
    const totals = rows.reduce(
      (acc, row) => ({
        requestCount: acc.requestCount + row.requestCount,
        promptTokens: acc.promptTokens + row.promptTokens,
        completionTokens: acc.completionTokens + row.completionTokens,
      }),
      { requestCount: 0, promptTokens: 0, completionTokens: 0 },
    );

    expect(totals.requestCount).toBe(6);
    expect(totals.promptTokens).toBe(307);
    expect(totals.completionTokens).toBe(165);
  });

  test('date boundaries include start/end of range and exclude next day', async () => {
    const daily = await fetchDailyUsageRows(databaseUrl, startDate, endDate);
    expect(daily.map((row) => row.day)).toEqual(['2999-02-01', '2999-02-02', '2999-02-03']);
    expect(daily.find((row) => row.day === '2999-02-04')).toBeUndefined();
  });

  test('fetchKnownModels includes models from failed chat requests', async () => {
    const models = await fetchKnownModels(databaseUrl);
    expect(models).toContain(modelFailed);
    expect(models).toContain(modelOk);
  });

  test('fetchEarliestUsageDate returns a valid ISO date not in the future', async () => {
    const earliest = await fetchEarliestUsageDate(databaseUrl);
    expect(earliest).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(earliest <= '2999-12-31').toBe(true);
  });

  test('malformed usage token values cause query failure', async () => {
    const badId = await insertLogRow({
      createdAt: day1Mid,
      model: modelOk,
      responseBody: { usage: { prompt_tokens: 'not-a-number', completion_tokens: 1 } },
    });
    extraIds.push(badId);

    await expect(fetchUsageRows(databaseUrl, startDate, endDate)).rejects.toThrow();
  });
});
