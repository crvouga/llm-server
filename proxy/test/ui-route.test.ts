import { describe, expect, test } from 'bun:test';
import { createApp } from '../src/index';

describe('ui route', () => {
  test('GET /ui serves static client shell', async () => {
    const app = createApp();
    const response = await app.fetch(new Request('http://proxy.test/ui'));

    expect(response.status).toBe(200);
    const html = await response.text();
    expect(html).toContain('LLM Proxy');
    expect(html).toContain('id="ui-root"');
    expect(html).toContain('/ui-client.js');
    expect(html).not.toContain('__UI_DATA__');
    expect(html).not.toContain('ui-dashboard-client');
    expect(html).not.toContain('ui-chat-client');
  });

  test('GET /api/dashboard-data requires database', async () => {
    const app = createApp();
    const response = await app.fetch(new Request('http://proxy.test/api/dashboard-data'));

    expect(response.status).toBe(503);
    const json = (await response.json()) as { error?: string };
    expect(json.error).toContain('DATABASE_URL');
  });

  test('legacy /dashboard redirects to /ui?tab=dashboard', async () => {
    const app = createApp();
    const response = await app.fetch(new Request('http://proxy.test/dashboard'));

    expect(response.status).toBe(301);
    expect(response.headers.get('location')).toBe('/ui?tab=dashboard');
  });

  test('legacy /chat redirects to /ui?tab=chat', async () => {
    const app = createApp();
    const response = await app.fetch(new Request('http://proxy.test/chat'));

    expect(response.status).toBe(301);
    expect(response.headers.get('location')).toBe('/ui?tab=chat');
  });
});
