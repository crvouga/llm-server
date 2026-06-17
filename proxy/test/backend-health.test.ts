import { describe, expect, test } from 'bun:test';
import {
  checkOpenAiBackendHealth,
  validateOpenAiModelsBody,
} from '../src/backend-health';

describe('validateOpenAiModelsBody', () => {
  test('accepts valid OpenAI models list', () => {
    const result = validateOpenAiModelsBody({
      object: 'list',
      data: [
        { id: 'gpt-test', object: 'model' },
        { id: 'claude-test', object: 'model' },
      ],
    });
    expect(result.valid).toBe(true);
    expect(result.modelIds).toEqual(['gpt-test', 'claude-test']);
  });

  test('rejects missing data array', () => {
    expect(validateOpenAiModelsBody({ object: 'list' }).valid).toBe(false);
  });

  test('rejects entries without string id', () => {
    expect(validateOpenAiModelsBody({ data: [{ object: 'model' }] }).valid).toBe(false);
    expect(validateOpenAiModelsBody({ data: [{ id: '' }] }).valid).toBe(false);
  });
});

describe('checkOpenAiBackendHealth', () => {
  test('reports invalid URL without fetching', async () => {
    const result = await checkOpenAiBackendHealth('not-a-url');
    expect(result.ok).toBe(false);
    expect(result.checks.configured).toBe(false);
    expect(result.checks.reachable).toBe(false);
    expect(result.error).toBe('Invalid backend URL');
  });

  test('reports reachable healthy backend', async () => {
    const result = await checkOpenAiBackendHealth('https://llm.example', {
      fetchImpl: async () =>
        new Response(
          JSON.stringify({
            object: 'list',
            data: [{ id: 'model-a', object: 'model' }],
          }),
          { status: 200, headers: { 'content-type': 'application/json' } },
        ),
    });

    expect(result.ok).toBe(true);
    expect(result.checks).toEqual({
      configured: true,
      reachable: true,
      httpOk: true,
      openAiModels: true,
    });
    expect(result.modelCount).toBe(1);
    expect(result.sampleModelIds).toEqual(['model-a']);
  });

  test('reports HTTP errors', async () => {
    const result = await checkOpenAiBackendHealth('https://llm.example', {
      fetchImpl: async () => new Response('down', { status: 503 }),
    });

    expect(result.ok).toBe(false);
    expect(result.checks.reachable).toBe(true);
    expect(result.checks.httpOk).toBe(false);
    expect(result.httpStatus).toBe(503);
  });

  test('reports invalid JSON shape', async () => {
    const result = await checkOpenAiBackendHealth('https://llm.example', {
      fetchImpl: async () =>
        new Response(JSON.stringify({ models: [] }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        }),
    });

    expect(result.ok).toBe(false);
    expect(result.checks.httpOk).toBe(true);
    expect(result.checks.openAiModels).toBe(false);
  });

  test('reports network failures', async () => {
    const result = await checkOpenAiBackendHealth('https://llm.example', {
      fetchImpl: async () => {
        throw new Error('connection refused');
      },
    });

    expect(result.ok).toBe(false);
    expect(result.checks.reachable).toBe(false);
    expect(result.error).toContain('connection refused');
  });
});
