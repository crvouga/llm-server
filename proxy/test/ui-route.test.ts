import { beforeAll, describe, expect, test } from 'bun:test';

describe('ui route', () => {
  let createApp: typeof import('../src/index').createApp;

  beforeAll(async () => {
    ({ createApp } = await import('../src/index'));
  });

  test('GET /ui serves static client shell', async () => {
    const app = createApp();
    const response = await app.fetch(new Request('http://proxy.test/ui'));

    expect(response.status).toBe(200);
    const html = await response.text();
    expect(html).toContain('LLM Proxy');
    expect(html).toContain('id="root"');
    expect(html).toContain('/assets/ui.js');
    expect(html).toContain('/assets/ui.css');
    expect(html).not.toContain('cdn.tailwindcss.com');
    expect(html).not.toContain('react.production.min.js');
    expect(html).not.toContain('__UI_DATA__');
  });

  test('GET /assets/ui.js serves built bundle', async () => {
    const app = createApp();
    const response = await app.fetch(new Request('http://proxy.test/assets/ui.js'));

    expect(response.status).toBe(200);
    const body = await response.text();
    expect(body.length).toBeGreaterThan(1000);
  });

  test('GET /api/dashboard-data requires database', async () => {
    const app = createApp();
    const response = await app.fetch(new Request('http://proxy.test/api/dashboard-data'));

    expect(response.status).toBe(503);
    const json = (await response.json()) as { error?: string };
    expect(json.error).toContain('DATABASE_URL');
  });

  test('GET /ui/investment-data requires database', async () => {
    const app = createApp();
    const response = await app.fetch(new Request('http://proxy.test/ui/investment-data'));

    expect(response.status).toBe(503);
    const text = await response.text();
    expect(text).toContain('DATABASE_URL');
  });

  test('GET /favicon.ico serves local icon', async () => {
    const app = createApp();
    const response = await app.fetch(new Request('http://proxy.test/favicon.ico'));

    expect(response.status).toBe(200);
    expect(response.headers.get('content-type')).toMatch(/image/);
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
