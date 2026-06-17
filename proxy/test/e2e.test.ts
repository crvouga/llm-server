import { afterAll, beforeAll, describe, expect, test } from 'bun:test';
import { createApp } from '../src/index';
import { fetchUsageRows } from '../src/dashboard/db/queries';
import { computeGenerationTps, computeOverallTps } from '../src/dashboard/lib/timing';
import { createTestCtx } from './helpers/ctx';
import {
  cleanupTestRows,
  createRunId,
  fetchLatestLogRowByModel,
  fetchLatestLogRowByPath,
  getBackendUrl,
  requireDatabaseUrl,
  sentinelModel,
  restoreBackendUrl,
  setBackendUrl,
  todayIsoDate,
} from './helpers/db';
import { startMockBackend } from './helpers/mock-backend';
import { proxyRequest } from './helpers/proxy';

const runId = createRunId();
let databaseUrl = '';
const model = sentinelModel(runId, 'e2e');
const promptTokens = 42;
const completionTokens = 17;

describe('proxy usage tracking e2e', () => {
  let originalBackendUrl: string | null;
  let mock: ReturnType<typeof startMockBackend>;
  const extraLogIds: string[] = [];

  beforeAll(async () => {
    databaseUrl = requireDatabaseUrl();
    originalBackendUrl = await getBackendUrl();
    mock = startMockBackend({ model, promptTokens, completionTokens });
    await setBackendUrl(mock.url);
  });

  afterAll(async () => {
    mock.stop();
    if (originalBackendUrl) {
      await restoreBackendUrl(originalBackendUrl);
    }
    await cleanupTestRows(runId, extraLogIds);
  });

  test('logs chat completion usage and reports it in fetchUsageRows', async () => {
    const app = createApp();
    const { ctx, drain } = createTestCtx();

    const response = await proxyRequest({
      app,
      databaseUrl,
      ctx,
      drain,
      model,
    });

    expect(response.status).toBe(200);
    const payload = (await response.json()) as {
      usage: { prompt_tokens: number; completion_tokens: number };
    };
    expect(payload.usage.prompt_tokens).toBe(promptTokens);
    expect(payload.usage.completion_tokens).toBe(completionTokens);

    const logRow = await fetchLatestLogRowByModel(model);
    expect(logRow).not.toBeNull();
    expect(logRow?.request_path).toBe('/v1/chat/completions');
    expect(logRow?.response_status_code).toBe(200);

    const requestBody = logRow?.request_body as { model?: string };
    const responseBody = logRow?.response_body as {
      usage?: { prompt_tokens?: number; completion_tokens?: number };
    };

    expect(requestBody.model).toBe(model);
    expect(responseBody.usage?.prompt_tokens).toBe(promptTokens);
    expect(responseBody.usage?.completion_tokens).toBe(completionTokens);
    expect(Number(logRow?.duration_ms)).toBeGreaterThan(0);
    expect(logRow?.ttft_ms).toBeNull();

    const today = await todayIsoDate();
    const usageRows = await fetchUsageRows(databaseUrl, today, today);
    const modelRow = usageRows.find((row) => row.model === model);

    expect(modelRow).toMatchObject({
      model,
      requestCount: 1,
      promptTokens,
      completionTokens,
      timedCompletionTokens: completionTokens,
    });
    expect(modelRow?.totalDurationMs).toBeGreaterThan(0);
    expect(computeOverallTps(modelRow!.timedCompletionTokens, modelRow!.totalDurationMs)).not.toBeNull();
  });

  test('injects thinking default while preserving client model in logged body', async () => {
    const app = createApp();
    const { ctx, drain } = createTestCtx();
    const thinkingModel = sentinelModel(runId, 'thinking');

    await proxyRequest({
      app,
      databaseUrl,
      ctx,
      drain,
      model: thinkingModel,
      body: {
        model: thinkingModel,
        messages: [{ role: 'user', content: 'hello' }],
      },
    });

    const logRow = await fetchLatestLogRowByModel(thinkingModel);
    const requestBody = logRow?.request_body as {
      model?: string;
      chat_template_kwargs?: { enable_thinking?: boolean };
    };

    expect(requestBody.model).toBe(thinkingModel);
    expect(requestBody.chat_template_kwargs?.enable_thinking).toBe(false);
  });

  test('logs streaming chat completion usage and reports it in fetchUsageRows', async () => {
    const streamModel = sentinelModel(runId, 'stream');
    const streamMock = startMockBackend({
      model: streamModel,
      streamChatCompletions: true,
      promptTokens: 55,
      completionTokens: 23,
    });

    const prevBackend = await getBackendUrl();
    await setBackendUrl(streamMock.url);

    try {
      const app = createApp();
      const { ctx, drain } = createTestCtx();

      const response = await proxyRequest({
        app,
        databaseUrl,
        ctx,
        drain,
        model: streamModel,
        body: {
          model: streamModel,
          stream: true,
          messages: [{ role: 'user', content: 'hello' }],
        },
      });

      expect(response.status).toBe(200);
      expect(response.headers.get('content-type')).toContain('text/event-stream');

      const sseText = await response.text();
      expect(sseText).toContain('data:');
      expect(sseText).toContain('[DONE]');

      const logRow = await fetchLatestLogRowByModel(streamModel);
      expect(logRow?.request_path).toBe('/v1/chat/completions');
      expect(logRow?.response_status_code).toBe(200);

      const requestBody = logRow?.request_body as {
        stream?: boolean;
        stream_options?: { include_usage?: boolean };
      };
      expect(requestBody.stream).toBe(true);
      expect(requestBody.stream_options?.include_usage).toBe(true);

      const responseBody = logRow?.response_body as {
        usage?: { prompt_tokens?: number; completion_tokens?: number };
      };
      expect(responseBody.usage?.prompt_tokens).toBe(55);
      expect(responseBody.usage?.completion_tokens).toBe(23);
      expect(Number(logRow?.duration_ms)).toBeGreaterThan(0);
      expect(Number(logRow?.ttft_ms)).toBeGreaterThan(0);
      expect(Number(logRow?.ttft_ms)).toBeLessThanOrEqual(Number(logRow?.duration_ms));

      const today = await todayIsoDate();
      const usageRows = await fetchUsageRows(databaseUrl, today, today);
      const modelRow = usageRows.find((row) => row.model === streamModel);

      expect(modelRow).toMatchObject({
        model: streamModel,
        requestCount: 1,
        promptTokens: 55,
        completionTokens: 23,
        timedCompletionTokens: 23,
      });
      expect(modelRow?.totalDurationMs).toBeGreaterThan(0);
    } finally {
      streamMock.stop();
      if (prevBackend) {
        await restoreBackendUrl(prevBackend);
      }
    }
  });

  test('logs blocking request timing for weighted TPS aggregation', async () => {
    const timingModel = sentinelModel(runId, 'timing-blocking');
    const timingMock = startMockBackend({
      model: timingModel,
      promptTokens: 0,
      completionTokens: 20,
      responseDelayMs: 200,
    });

    const prevBackend = await getBackendUrl();
    await setBackendUrl(timingMock.url);

    try {
      const app = createApp();
      const { ctx, drain } = createTestCtx();
      await proxyRequest({ app, databaseUrl, ctx, drain, model: timingModel });

      const logRow = await fetchLatestLogRowByModel(timingModel);
      expect(Number(logRow?.duration_ms)).toBeGreaterThanOrEqual(200);
      expect(logRow?.ttft_ms).toBeNull();

      const today = await todayIsoDate();
      const usageRows = await fetchUsageRows(databaseUrl, today, today);
      const modelRow = usageRows.find((row) => row.model === timingModel);

      expect(modelRow).toMatchObject({
        model: timingModel,
        requestCount: 1,
        completionTokens: 20,
        timedCompletionTokens: 20,
      });
      expect(computeOverallTps(modelRow!.timedCompletionTokens, modelRow!.totalDurationMs)).toBeLessThanOrEqual(
        100,
      );
      expect(computeOverallTps(modelRow!.timedCompletionTokens, modelRow!.totalDurationMs)).toBeGreaterThan(
        0,
      );
    } finally {
      timingMock.stop();
      if (prevBackend) {
        await restoreBackendUrl(prevBackend);
      }
    }
  });

  test('logs usage-only stream with duration but null ttft', async () => {
    const usageOnlyModel = sentinelModel(runId, 'usage-only-stream');
    const usageOnlyMock = startMockBackend({
      model: usageOnlyModel,
      streamChatCompletions: true,
      usageOnlyStream: true,
      promptTokens: 12,
      completionTokens: 8,
    });

    const prevBackend = await getBackendUrl();
    await setBackendUrl(usageOnlyMock.url);

    try {
      const app = createApp();
      const { ctx, drain } = createTestCtx();
      await proxyRequest({
        app,
        databaseUrl,
        ctx,
        drain,
        model: usageOnlyModel,
        body: {
          model: usageOnlyModel,
          stream: true,
          messages: [{ role: 'user', content: 'hello' }],
        },
      });

      const logRow = await fetchLatestLogRowByModel(usageOnlyModel);
      expect(Number(logRow?.duration_ms)).toBeGreaterThanOrEqual(1);
      expect(logRow?.ttft_ms).toBeNull();

      const today = await todayIsoDate();
      const usageRows = await fetchUsageRows(databaseUrl, today, today);
      const modelRow = usageRows.find((row) => row.model === usageOnlyModel);

      expect(modelRow).toMatchObject({
        model: usageOnlyModel,
        completionTokens: 8,
        timedCompletionTokens: 8,
        generationCompletionTokens: 0,
        totalGenerationMs: 0,
      });
      expect(computeOverallTps(modelRow!.timedCompletionTokens, modelRow!.totalDurationMs)).not.toBeNull();
      expect(computeGenerationTps(
        modelRow!.generationCompletionTokens,
        modelRow!.totalGenerationMs,
      )).toBeNull();
    } finally {
      usageOnlyMock.stop();
      if (prevBackend) {
        await restoreBackendUrl(prevBackend);
      }
    }
  });

  test('logs streaming timing with measurable generation window', async () => {
    const timingModel = sentinelModel(runId, 'timing-stream');
    const timingMock = startMockBackend({
      model: timingModel,
      streamChatCompletions: true,
      promptTokens: 0,
      completionTokens: 30,
      streamChunkDelayMs: 120,
    });

    const prevBackend = await getBackendUrl();
    await setBackendUrl(timingMock.url);

    try {
      const app = createApp();
      const { ctx, drain } = createTestCtx();
      await proxyRequest({
        app,
        databaseUrl,
        ctx,
        drain,
        model: timingModel,
        body: {
          model: timingModel,
          stream: true,
          messages: [{ role: 'user', content: 'hello' }],
        },
      });

      const logRow = await fetchLatestLogRowByModel(timingModel);
      expect(Number(logRow?.duration_ms)).toBeGreaterThanOrEqual(120);
      expect(Number(logRow?.ttft_ms)).toBeGreaterThan(0);
      expect(Number(logRow?.ttft_ms)).toBeLessThan(Number(logRow?.duration_ms));

      const today = await todayIsoDate();
      const usageRows = await fetchUsageRows(databaseUrl, today, today);
      const modelRow = usageRows.find((row) => row.model === timingModel);

      expect(modelRow).toMatchObject({
        model: timingModel,
        completionTokens: 30,
        generationCompletionTokens: 30,
      });
      expect(computeGenerationTps(
        modelRow!.generationCompletionTokens,
        modelRow!.totalGenerationMs,
      )).toBeGreaterThan(0);
    } finally {
      timingMock.stop();
      if (prevBackend) {
        await restoreBackendUrl(prevBackend);
      }
    }
  });

  test('does not count non-chat paths in usage aggregation', async () => {
    const app = createApp();
    const { ctx, drain } = createTestCtx();

    const response = await app.fetch(
      new Request('http://proxy.test/v1/models', { method: 'GET' }),
      { DATABASE_URL: databaseUrl },
      ctx,
    );

    expect(response.status).toBe(200);
    await drain();

    const modelsLogRow = await fetchLatestLogRowByPath('/v1/models');
    if (modelsLogRow?.id) {
      extraLogIds.push(String(modelsLogRow.id));
    }

    const today = await todayIsoDate();
    const usageRows = await fetchUsageRows(databaseUrl, today, today);
    const modelRow = usageRows.find((row) => row.model === model);
    expect(modelRow?.requestCount ?? 0).toBe(1);
  });

  test('POST /api/backend-health reports healthy mock backend', async () => {
    const app = createApp();
    const response = await app.fetch(
      new Request('http://proxy.test/api/backend-health', { method: 'POST' }),
      { DATABASE_URL: databaseUrl },
    );

    expect(response.status).toBe(200);
    const json = (await response.json()) as {
      ok: boolean;
      modelCount: number;
      checks: { reachable: boolean; httpOk: boolean; openAiModels: boolean };
    };
    expect(json.ok).toBe(true);
    expect(json.modelCount).toBeGreaterThan(0);
    expect(json.checks.reachable).toBe(true);
    expect(json.checks.httpOk).toBe(true);
    expect(json.checks.openAiModels).toBe(true);
  });
});

describe('proxy usage tracking e2e - multi request', () => {
  let originalBackendUrl: string | null;
  let mock: ReturnType<typeof startMockBackend>;
  const multiModel = sentinelModel(runId, 'multi');
  const perRequestPrompt = 11;
  const perRequestCompletion = 7;

  beforeAll(async () => {
    databaseUrl = requireDatabaseUrl();
    originalBackendUrl = await getBackendUrl();
    mock = startMockBackend({
      model: multiModel,
      usageForRequest: () => ({
        promptTokens: perRequestPrompt,
        completionTokens: perRequestCompletion,
      }),
    });
    await setBackendUrl(mock.url);
  });

  afterAll(async () => {
    mock.stop();
    if (originalBackendUrl) {
      await restoreBackendUrl(originalBackendUrl);
    }
    await cleanupTestRows(runId);
  });

  test('accumulates three sequential completions', async () => {
    const app = createApp();

    for (let i = 0; i < 3; i += 1) {
      const { ctx, drain } = createTestCtx();
      await proxyRequest({ app, databaseUrl, ctx, drain, model: multiModel });
    }

    const today = await todayIsoDate();
    const usageRows = await fetchUsageRows(databaseUrl, today, today);
    const modelRow = usageRows.find((row) => row.model === multiModel);

    expect(modelRow).toMatchObject({
      model: multiModel,
      requestCount: 3,
      promptTokens: perRequestPrompt * 3,
      completionTokens: perRequestCompletion * 3,
      timedCompletionTokens: perRequestCompletion * 3,
    });
    expect(modelRow?.totalDurationMs).toBeGreaterThan(0);
  });
});

describe('proxy usage tracking e2e - response edge cases', () => {
  let originalBackendUrl: string | null;
  const extraLogIds: string[] = [];

  beforeAll(async () => {
    databaseUrl = requireDatabaseUrl();
    originalBackendUrl = await getBackendUrl();
  });

  afterAll(async () => {
    if (originalBackendUrl) {
      await restoreBackendUrl(originalBackendUrl);
    }
    await cleanupTestRows(runId, extraLogIds);
  });

  test('logs but excludes 200 responses without usage', async () => {
    const noUsageModel = sentinelModel(runId, 'no-usage');
    const mock = startMockBackend({
      model: noUsageModel,
      routes: [
        {
          pathSuffix: '/chat/completions',
          body: { id: 'x', choices: [], model: noUsageModel },
        },
      ],
    });

    await setBackendUrl(mock.url);
    const app = createApp();
    const { ctx, drain } = createTestCtx();
    await proxyRequest({ app, databaseUrl, ctx, drain, model: noUsageModel });
    mock.stop();

    const logRow = await fetchLatestLogRowByModel(noUsageModel);
    expect(logRow?.response_status_code).toBe(200);
    expect((logRow?.response_body as { usage?: unknown })?.usage).toBeUndefined();

    const today = await todayIsoDate();
    const usageRows = await fetchUsageRows(databaseUrl, today, today);
    expect(usageRows.find((row) => row.model === noUsageModel)).toBeUndefined();
  });

  test('logs but excludes 500 responses even when body contains usage', async () => {
    const errorModel = sentinelModel(runId, 'server-error');
    const mock = startMockBackend({
      model: errorModel,
      routes: [
        {
          pathSuffix: '/chat/completions',
          status: 500,
          body: {
            error: 'server error',
            usage: { prompt_tokens: 99, completion_tokens: 88 },
          },
        },
      ],
    });

    await setBackendUrl(mock.url);
    const app = createApp();
    const { ctx, drain } = createTestCtx();
    const response = await proxyRequest({ app, databaseUrl, ctx, drain, model: errorModel });
    mock.stop();

    expect(response.status).toBe(500);
    const logRow = await fetchLatestLogRowByModel(errorModel);
    expect(logRow?.response_status_code).toBe(500);

    const today = await todayIsoDate();
    const usageRows = await fetchUsageRows(databaseUrl, today, today);
    expect(usageRows.find((row) => row.model === errorModel)).toBeUndefined();
  });

  test('logs null body for text/plain and excludes from aggregation', async () => {
    const plainModel = sentinelModel(runId, 'plain');
    const mock = startMockBackend({
      model: plainModel,
      routes: [
        {
          pathSuffix: '/chat/completions',
          contentType: 'text/plain',
          body: 'plain response',
        },
      ],
    });

    await setBackendUrl(mock.url);
    const app = createApp();
    const { ctx, drain } = createTestCtx();
    await proxyRequest({ app, databaseUrl, ctx, drain, model: plainModel });
    mock.stop();

    const logRow = await fetchLatestLogRowByModel(plainModel);
    expect(logRow?.response_body).toBeNull();

    const today = await todayIsoDate();
    const usageRows = await fetchUsageRows(databaseUrl, today, today);
    expect(usageRows.find((row) => row.model === plainModel)).toBeUndefined();
  });

  test('logs /v1/messages with usage but excludes from aggregation', async () => {
    const messagesModel = sentinelModel(runId, 'messages');
    const mock = startMockBackend({
      model: messagesModel,
      promptTokens: 30,
      completionTokens: 12,
    });

    await setBackendUrl(mock.url);
    const app = createApp();
    const { ctx, drain } = createTestCtx();
    const response = await proxyRequest({
      app,
      databaseUrl,
      ctx,
      drain,
      path: '/v1/messages',
      model: messagesModel,
    });
    mock.stop();

    expect(response.status).toBe(200);
    const logRow = await fetchLatestLogRowByModel(messagesModel);
    expect(logRow?.request_path).toBe('/v1/messages');
    expect(
      (logRow?.response_body as { usage?: { prompt_tokens?: number } })?.usage?.prompt_tokens,
    ).toBe(30);

    const today = await todayIsoDate();
    const usageRows = await fetchUsageRows(databaseUrl, today, today);
    expect(usageRows.find((row) => row.model === messagesModel)).toBeUndefined();
  });

  test('logs backend failure with error message and excludes from aggregation', async () => {
    const failModel = sentinelModel(runId, 'backend-down');
    await setBackendUrl('http://127.0.0.1:1');

    const app = createApp();
    const { ctx, drain } = createTestCtx();
    const response = await proxyRequest({ app, databaseUrl, ctx, drain, model: failModel });

    expect(response.status).toBe(503);

    const logRow = await fetchLatestLogRowByPath('/v1/chat/completions');
    expect(logRow).not.toBeNull();
    if (logRow?.id) {
      extraLogIds.push(String(logRow.id));
    }

    expect(logRow?.response_status_code).toBe(503);
    expect(logRow?.response_error_message).toBeTruthy();
    expect(logRow?.request_body).toBeNull();

    const today = await todayIsoDate();
    const usageRows = await fetchUsageRows(databaseUrl, today, today);
    expect(usageRows.find((row) => row.model === failModel)).toBeUndefined();
  });
});
