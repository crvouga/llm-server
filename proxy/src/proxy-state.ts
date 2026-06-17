// Reads proxy configuration from PostgreSQL with a short in-isolate cache.

import { neon, NeonDbError } from '@neondatabase/serverless';
import {
  type BackendHeaderEntry,
  type BackendHeaders,
  backendHeadersToEntries,
  parseBackendHeadersFromDb,
  parseBackendHeadersInput,
} from './backend-headers';

const CACHE_TTL_MS = 30_000;

export interface BackendConfig {
  backendUrl: string | null;
  backendHeaders: BackendHeaders;
}

const EMPTY_BACKEND_CONFIG: BackendConfig = {
  backendUrl: null,
  backendHeaders: {},
};

let cachedBackendConfig: BackendConfig | undefined;
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

async function loadBackendConfig(databaseUrl: string): Promise<BackendConfig> {
  try {
    const sql = neon(databaseUrl);
    const rows = await sql`
      SELECT backend_url, backend_headers
      FROM llm_proxy.config
      WHERE id = 1
      LIMIT 1
    `;

    if (rows.length === 0) {
      return EMPTY_BACKEND_CONFIG;
    }

    const raw = String(rows[0].backend_url ?? '');
    return {
      backendUrl: parseBackendUrlInput(raw),
      backendHeaders: parseBackendHeadersFromDb(rows[0].backend_headers),
    };
  } catch (error) {
    const code = error instanceof NeonDbError ? error.code : 'unknown';
    console.error(`Failed to load proxy state (code: ${code ?? 'unknown'})`);
    return EMPTY_BACKEND_CONFIG;
  }
}

export async function getBackendConfig(databaseUrl: string): Promise<BackendConfig> {
  if (!databaseUrl) {
    return EMPTY_BACKEND_CONFIG;
  }
  return loadBackendConfig(databaseUrl);
}

export interface SaveBackendConfigInput {
  backendUrl: string;
  backendHeaders?: unknown;
}

export async function saveBackendConfig(
  databaseUrl: string,
  input: SaveBackendConfigInput,
): Promise<BackendConfig> {
  const backendUrl = parseBackendUrlInput(input.backendUrl);
  if (!backendUrl) {
    throw new Error('Invalid backend URL');
  }

  let backendHeaders: BackendHeaders;
  try {
    backendHeaders = parseBackendHeadersInput(input.backendHeaders ?? {});
  } catch (error) {
    throw error instanceof Error ? error : new Error('Invalid backend headers');
  }

  const sql = neon(databaseUrl);
  await sql`
    INSERT INTO llm_proxy.config (id, backend_url, backend_headers, updated_at)
    VALUES (1, ${backendUrl}, ${JSON.stringify(backendHeaders)}::jsonb, NOW())
    ON CONFLICT (id) DO UPDATE SET
      backend_url = EXCLUDED.backend_url,
      backend_headers = EXCLUDED.backend_headers,
      updated_at = EXCLUDED.updated_at
  `;

  resetBackendConfigCache();
  return { backendUrl, backendHeaders };
}

/** @deprecated Use saveBackendConfig */
export async function saveBackendUrl(databaseUrl: string, rawUrl: string): Promise<string> {
  const config = await saveBackendConfig(databaseUrl, { backendUrl: rawUrl });
  return config.backendUrl!;
}

export async function fetchBackendConfig(databaseUrl: string): Promise<BackendConfig> {
  if (!databaseUrl) {
    return EMPTY_BACKEND_CONFIG;
  }

  const now = Date.now();
  if (cachedBackendConfig !== undefined && now < cacheExpiresAt) {
    return cachedBackendConfig;
  }

  const config = await loadBackendConfig(databaseUrl);
  cachedBackendConfig = config;
  cacheExpiresAt = now + CACHE_TTL_MS;
  return config;
}

export async function fetchBackendUrl(databaseUrl: string): Promise<string | null> {
  const config = await fetchBackendConfig(databaseUrl);
  return config.backendUrl;
}

export function backendConfigHeaderEntries(config: BackendConfig): BackendHeaderEntry[] {
  return backendHeadersToEntries(config.backendHeaders);
}

/** Clears the in-isolate backend config cache (for tests). */
export function resetBackendConfigCache(): void {
  cachedBackendConfig = undefined;
  cacheExpiresAt = 0;
}

/** @deprecated Use resetBackendConfigCache */
export function resetBackendUrlCache(): void {
  resetBackendConfigCache();
}
