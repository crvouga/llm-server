import type { BackendHeaders } from './backend-headers';
import { parseBackendUrlInput } from './proxy-state';

export interface BackendHealthChecks {
  configured: boolean;
  reachable: boolean;
  httpOk: boolean;
  openAiModels: boolean;
}

export interface BackendHealthResult {
  ok: boolean;
  backendUrl: string;
  latencyMs: number;
  httpStatus: number | null;
  modelCount: number;
  sampleModelIds: string[];
  checks: BackendHealthChecks;
  error: string | null;
  checkedAt: string;
}

export interface CheckOpenAiBackendHealthOptions {
  timeoutMs?: number;
  fetchImpl?: typeof fetch;
  headers?: BackendHeaders;
}

const DEFAULT_TIMEOUT_MS = 10_000;

export function validateOpenAiModelsBody(body: unknown): { valid: boolean; modelIds: string[] } {
  if (!body || typeof body !== 'object') {
    return { valid: false, modelIds: [] };
  }

  const data = (body as { data?: unknown }).data;
  if (!Array.isArray(data)) {
    return { valid: false, modelIds: [] };
  }

  const modelIds: string[] = [];
  for (const entry of data) {
    if (!entry || typeof entry !== 'object') {
      return { valid: false, modelIds: [] };
    }
    const id = (entry as { id?: unknown }).id;
    if (typeof id !== 'string' || id.length === 0) {
      return { valid: false, modelIds: [] };
    }
    modelIds.push(id);
  }

  return { valid: true, modelIds };
}

export async function checkOpenAiBackendHealth(
  backendUrlInput: string,
  options: CheckOpenAiBackendHealthOptions = {},
): Promise<BackendHealthResult> {
  const checkedAt = new Date().toISOString();
  const fetchImpl = options.fetchImpl ?? fetch;
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;

  const normalized = parseBackendUrlInput(backendUrlInput);
  const checks: BackendHealthChecks = {
    configured: normalized !== null,
    reachable: false,
    httpOk: false,
    openAiModels: false,
  };

  if (!normalized) {
    return {
      ok: false,
      backendUrl: backendUrlInput.trim(),
      latencyMs: 0,
      httpStatus: null,
      modelCount: 0,
      sampleModelIds: [],
      checks,
      error: 'Invalid backend URL',
      checkedAt,
    };
  }

  const startedAt = Date.now();
  let httpStatus: number | null = null;

  try {
    const response = await fetchImpl(`${normalized}/v1/models`, {
      method: 'GET',
      headers: options.headers,
      signal: AbortSignal.timeout(timeoutMs),
    });
    httpStatus = response.status;
    checks.reachable = true;
    checks.httpOk = response.ok;

    if (!response.ok) {
      let detail = `HTTP ${response.status}`;
      try {
        const text = await response.text();
        if (text.trim()) {
          detail = text.slice(0, 200);
        }
      } catch {
        /* ignore */
      }

      return {
        ok: false,
        backendUrl: normalized,
        latencyMs: Date.now() - startedAt,
        httpStatus,
        modelCount: 0,
        sampleModelIds: [],
        checks,
        error: detail,
        checkedAt,
      };
    }

    const body = await response.json();
    const { valid, modelIds } = validateOpenAiModelsBody(body);
    checks.openAiModels = valid;

    if (!valid) {
      return {
        ok: false,
        backendUrl: normalized,
        latencyMs: Date.now() - startedAt,
        httpStatus,
        modelCount: 0,
        sampleModelIds: [],
        checks,
        error: 'Response is not a valid OpenAI /v1/models payload',
        checkedAt,
      };
    }

    return {
      ok: true,
      backendUrl: normalized,
      latencyMs: Date.now() - startedAt,
      httpStatus,
      modelCount: modelIds.length,
      sampleModelIds: modelIds.slice(0, 3),
      checks,
      error: null,
      checkedAt,
    };
  } catch (error) {
    return {
      ok: false,
      backendUrl: normalized,
      latencyMs: Date.now() - startedAt,
      httpStatus,
      modelCount: 0,
      sampleModelIds: [],
      checks,
      error: error instanceof Error ? error.message : String(error),
      checkedAt,
    };
  }
}
