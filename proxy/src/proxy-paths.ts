/** Paths forwarded to the LLM backend (OpenAI, Anthropic, LM Studio). */

const OPENAI_COMPAT_SEGMENTS = [
  'models',
  'chat/completions',
  'completions',
  'embeddings',
  'responses',
  'messages',
  'audio',
  'images',
  'moderations',
  'files',
  'batches',
] as const;

function normalizePath(path: string): string {
  return path.replace(/\/+$/, '') || '/';
}

function matchesOpenAiCompatRootPath(normalized: string): boolean {
  for (const segment of OPENAI_COMPAT_SEGMENTS) {
    if (normalized === `/${segment}` || normalized.startsWith(`/${segment}/`)) {
      return true;
    }
  }
  return false;
}

export function isBackendProxiedPath(path: string): boolean {
  const normalized = normalizePath(path);

  if (normalized.startsWith('/api/v0/') || normalized.startsWith('/api/v1/')) {
    return true;
  }

  if (normalized === '/v1' || normalized.startsWith('/v1/')) {
    return true;
  }

  return matchesOpenAiCompatRootPath(normalized);
}
