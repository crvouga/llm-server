import { createApp, type Env } from './index';
import { createServerExecutionContext } from './wait-until';

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
