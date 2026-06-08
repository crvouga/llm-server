import { describe, expect, test } from 'bun:test';
import { isBackendProxiedPath } from '../src/proxy-paths';

describe('isBackendProxiedPath', () => {
  test('allows OpenAI /v1 paths', () => {
    expect(isBackendProxiedPath('/v1/chat/completions')).toBe(true);
    expect(isBackendProxiedPath('/v1/messages')).toBe(true);
    expect(isBackendProxiedPath('/v1/models')).toBe(true);
    expect(isBackendProxiedPath('/v1/models/foo')).toBe(true);
    expect(isBackendProxiedPath('/v1/embeddings')).toBe(true);
    expect(isBackendProxiedPath('/v1/responses')).toBe(true);
    expect(isBackendProxiedPath('/v1/')).toBe(true);
    expect(isBackendProxiedPath('/v1')).toBe(true);
  });

  test('allows OpenAI-compat root paths when api_base includes /v1', () => {
    expect(isBackendProxiedPath('/chat/completions')).toBe(true);
    expect(isBackendProxiedPath('/models')).toBe(true);
    expect(isBackendProxiedPath('/models/foo')).toBe(true);
    expect(isBackendProxiedPath('/messages')).toBe(true);
    expect(isBackendProxiedPath('/embeddings')).toBe(true);
    expect(isBackendProxiedPath('/completions')).toBe(true);
    expect(isBackendProxiedPath('/responses')).toBe(true);
    expect(isBackendProxiedPath('/audio/transcriptions')).toBe(true);
    expect(isBackendProxiedPath('/images/generations')).toBe(true);
  });

  test('allows LM Studio native API paths', () => {
    expect(isBackendProxiedPath('/api/v0/models')).toBe(true);
    expect(isBackendProxiedPath('/api/v0/chat/completions')).toBe(true);
    expect(isBackendProxiedPath('/api/v1/mcp/tools')).toBe(true);
  });

  test('denies non-LLM paths', () => {
    expect(isBackendProxiedPath('/.well-known/appspecific/com.chrome.devtools.json')).toBe(
      false,
    );
    expect(isBackendProxiedPath('/')).toBe(false);
    expect(isBackendProxiedPath('/dashboard')).toBe(false);
    expect(isBackendProxiedPath('/favicon.ico')).toBe(false);
    expect(isBackendProxiedPath('/robots.txt')).toBe(false);
  });
});
