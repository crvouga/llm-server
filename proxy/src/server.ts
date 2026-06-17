import { createApp, type Env } from './index';
import { createServerExecutionContext } from './wait-until';
import { DEFAULT_BACKEND_URL } from './proxy-state';

process.env.LLM_PROXY_BACKEND_URL ??= DEFAULT_BACKEND_URL;

const app = createApp();
const port = Number(process.env.PORT) || 8080;

const env: Env = {
  DATABASE_URL: process.env.DATABASE_URL ?? '',
};

Bun.serve({
  port,
  fetch(request) {
    return app.fetch(request, env, createServerExecutionContext());
  },
});

console.log(`llm-proxy listening on :${port}`);
