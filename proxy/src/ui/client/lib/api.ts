import {
  COST_RATES_PATH,
  DASHBOARD_DATA_API_PATH,
  INVESTMENT_DATA_PATH,
  MODELS_API_PATH,
} from './constants';

export async function fetchDashboardData(search: string) {
  const query = search.startsWith('?') ? search : search ? `?${search}` : '';
  const response = await fetch(`${DASHBOARD_DATA_API_PATH}${query}`);
  if (!response.ok) {
    let details = `Request failed (${response.status})`;
    try {
      const json = (await response.json()) as { error?: string };
      if (json.error) details = json.error;
    } catch {
      const text = await response.text();
      if (text) details = text;
    }
    throw new Error(details);
  }
  return response.json();
}

export async function saveCostRates(body: unknown) {
  const response = await fetch(COST_RATES_PATH, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error('Failed to save cost rates');
  return response.json();
}

export async function fetchInvestmentData() {
  const response = await fetch(INVESTMENT_DATA_PATH);
  if (!response.ok) {
    let details = `Request failed (${response.status})`;
    try {
      const json = (await response.json()) as { error?: string };
      if (json.error) details = json.error;
    } catch {
      const text = await response.text();
      if (text) details = text;
    }
    throw new Error(details);
  }
  return response.json();
}

export async function saveInvestmentData(body: unknown) {
  const response = await fetch(INVESTMENT_DATA_PATH, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error('Failed to save investment settings');
  return response.json();
}

export async function fetchAvailableModels() {
  try {
    const response = await fetch(MODELS_API_PATH);
    if (!response.ok) return [];
    const json = (await response.json()) as { data?: Array<{ id?: string }> };
    return (json.data || [])
      .map((entry) => entry.id)
      .filter((id): id is string => typeof id === 'string' && id.length > 0);
  } catch {
    return [];
  }
}
