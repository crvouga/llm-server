export type BackendHeaders = Record<string, string>;

export interface BackendHeaderEntry {
  name: string;
  value: string;
}

const BLOCKED_HEADER_NAMES = new Set(['host', 'connection', 'content-length', 'transfer-encoding']);

function isValidHeaderName(name: string): boolean {
  return name.length > 0 && /^[\w!#$%&'*+.^`|~-]+$/i.test(name);
}

/** Normalizes UI/API header input into a header map for upstream requests. */
export function parseBackendHeadersInput(raw: unknown): BackendHeaders {
  const entries: BackendHeaderEntry[] = [];

  if (Array.isArray(raw)) {
    for (const item of raw) {
      if (!item || typeof item !== 'object') continue;
      const name = String((item as BackendHeaderEntry).name ?? '').trim();
      const value = String((item as BackendHeaderEntry).value ?? '');
      if (!name) continue;
      entries.push({ name, value });
    }
  } else if (raw && typeof raw === 'object') {
    for (const [name, value] of Object.entries(raw as Record<string, unknown>)) {
      const trimmedName = name.trim();
      if (!trimmedName) continue;
      entries.push({ name: trimmedName, value: String(value ?? '') });
    }
  }

  const headers: BackendHeaders = {};
  for (const { name, value } of entries) {
    if (!isValidHeaderName(name)) {
      throw new Error(`Invalid header name: ${name}`);
    }
    if (BLOCKED_HEADER_NAMES.has(name.toLowerCase())) {
      throw new Error(`Header not allowed: ${name}`);
    }
    headers[name] = value;
  }

  return headers;
}

export function backendHeadersToEntries(headers: BackendHeaders): BackendHeaderEntry[] {
  return Object.entries(headers)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([name, value]) => ({ name, value }));
}

export function parseBackendHeadersFromDb(raw: unknown): BackendHeaders {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    return {};
  }

  const headers: BackendHeaders = {};
  for (const [name, value] of Object.entries(raw as Record<string, unknown>)) {
    if (typeof name !== 'string' || !name.trim()) continue;
    if (typeof value !== 'string') continue;
    if (BLOCKED_HEADER_NAMES.has(name.toLowerCase())) continue;
    headers[name] = value;
  }
  return headers;
}
