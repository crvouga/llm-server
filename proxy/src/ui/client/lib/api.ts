import {
  BACKEND_CONFIG_PATH,
  BACKEND_HEALTH_PATH,
  COST_RATES_PATH,
  DASHBOARD_DATA_API_PATH,
  INVESTMENT_DATA_PATH,
  MODELS_API_PATH,
} from './constants';
import type {
  BackendConfig,
  BackendConfigSaveBody,
  BackendHealthResult,
} from './types';

async function readApiError(response: Response): Promise<string> {
  const text = await response.text();
  if (!text.trim()) {
    return `Request failed (${response.status})`;
  }
  try {
    const json = JSON.parse(text) as { error?: string };
    if (json.error) return json.error;
  } catch {
    /* not json */
  }
  return text;
}

async function readJsonResponse<T>(response: Response): Promise<T> {
  const text = await response.text();
  return JSON.parse(text) as T;
}

export async function fetchDashboardData(search: string) {
  const query = search.startsWith('?') ? search : search ? `?${search}` : '';
  const response = await fetch(`${DASHBOARD_DATA_API_PATH}${query}`);
  if (!response.ok) {
    throw new Error(await readApiError(response));
  }
  return readJsonResponse(response);
}

export async function saveCostRates(body: unknown) {
  const response = await fetch(COST_RATES_PATH, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error('Failed to save cost rates');
  return readJsonResponse(response);
}

export async function fetchInvestmentData() {
  const response = await fetch(INVESTMENT_DATA_PATH);
  if (!response.ok) {
    throw new Error(await readApiError(response));
  }
  return readJsonResponse(response);
}

export async function saveInvestmentData(body: unknown) {
  const response = await fetch(INVESTMENT_DATA_PATH, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error('Failed to save investment settings');
  return readJsonResponse(response);
}

export async function fetchAvailableModels() {
  try {
    const response = await fetch(MODELS_API_PATH);
    if (!response.ok) return [];
    const json = await readJsonResponse<{ data?: Array<{ id?: string }> }>(response);
    return (json.data || [])
      .map((entry) => entry.id)
      .filter((id): id is string => typeof id === 'string' && id.length > 0);
  } catch {
    return [];
  }
}

export async function fetchBackendConfig() {
  const response = await fetch(BACKEND_CONFIG_PATH);
  if (!response.ok) {
    throw new Error(await readApiError(response));
  }
  return readJsonResponse<BackendConfig>(response);
}

export async function saveBackendConfig(body: BackendConfigSaveBody) {
  const response = await fetch(BACKEND_CONFIG_PATH, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(await readApiError(response));
  }
  return readJsonResponse<BackendConfig & { ok: true }>(response);
}

export async function checkBackendHealth() {
  const response = await fetch(BACKEND_HEALTH_PATH, { method: 'POST' });
  const json = await readJsonResponse<BackendHealthResult & { error?: string }>(response);
  if (!response.ok && !json.checks) {
    throw new Error(json.error ?? `Health check failed (${response.status})`);
  }
  return json;
}
