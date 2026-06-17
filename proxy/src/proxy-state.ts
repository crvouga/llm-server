// Reads proxy configuration from PostgreSQL with a short in-isolate cache.

import { neon, NeonDbError } from '@neondatabase/serverless';

const CACHE_TTL_MS = 30_000;

export interface BackendConfig {
  backendUrl: string | null;
}

let cachedBackendUrl: string | null | undefined;
let cacheExpiresAt = 0;

export function parseBackendUrlInput(raw: string): string | null {
  const trimmed = raw.trim();
  if (!trimmed) {
    return null;
  }

  try {
    const parsed = new URL(trimmed);
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
      console.error(`Invalid proxy backend_url protocol: ${parsed.protocol}`);
      return null;
    }
    if (!parsed.host) {
      console.error('Invalid proxy backend_url: missing host');
      return null;
    }
    return parsed.origin;
  } catch {
    console.error(`Invalid proxy backend_url: ${trimmed}`);
    return null;
  }
}

async function loadBackendUrl(databaseUrl: string): Promise<string | null> {
  try {
    const sql = neon(databaseUrl);
    const rows = await sql`
      SELECT backend_url
      FROM llm_proxy.config
      WHERE id = 1
      LIMIT 1
    `;

    if (rows.length === 0) {
      return null;
    }

    const raw = String(rows[0].backend_url ?? '');
    return parseBackendUrlInput(raw);
  } catch (error) {
    const code = error instanceof NeonDbError ? error.code : 'unknown';
    console.error(`Failed to load proxy state (code: ${code ?? 'unknown'})`);
    return null;
  }
}

export async function getBackendConfig(databaseUrl: string): Promise<BackendConfig> {
  const backendUrl = databaseUrl ? await loadBackendUrl(databaseUrl) : null;
  return { backendUrl };
}

export async function saveBackendUrl(databaseUrl: string, rawUrl: string): Promise<string> {
  const backendUrl = parseBackendUrlInput(rawUrl);
  if (!backendUrl) {
    throw new Error('Invalid backend URL');
  }

  const sql = neon(databaseUrl);
  await sql`
    INSERT INTO llm_proxy.config (id, backend_url, updated_at)
    VALUES (1, ${backendUrl}, NOW())
    ON CONFLICT (id) DO UPDATE SET
      backend_url = EXCLUDED.backend_url,
      updated_at = EXCLUDED.updated_at
  `;

  resetBackendUrlCache();
  return backendUrl;
}

export async function fetchBackendUrl(databaseUrl: string): Promise<string | null> {
  if (!databaseUrl) {
    return null;
  }

  const now = Date.now();
  if (cachedBackendUrl !== undefined && now < cacheExpiresAt) {
    return cachedBackendUrl;
  }

  const backendUrl = await loadBackendUrl(databaseUrl);
  cachedBackendUrl = backendUrl;
  cacheExpiresAt = now + CACHE_TTL_MS;
  return backendUrl;
}

/** Clears the in-isolate backend URL cache (for tests). */
export function resetBackendUrlCache(): void {
  cachedBackendUrl = undefined;
  cacheExpiresAt = 0;
}
