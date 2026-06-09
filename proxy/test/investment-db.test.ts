import { afterAll, beforeAll, describe, expect, test } from 'bun:test';
import {
  fetchInvestmentConfig,
  upsertInvestmentConfig,
} from '../src/dashboard/db/investment';
import { requireDatabaseUrl, sqlClient } from './helpers/db';

const TEST_INVESTMENT = 12_500.5;
const TEST_DAILY = 4.25;

describe('investment config persistence', () => {
  let databaseUrl = '';
  let previousConfig: Awaited<ReturnType<typeof fetchInvestmentConfig>> | null = null;

  beforeAll(async () => {
    databaseUrl = requireDatabaseUrl();
    previousConfig = await fetchInvestmentConfig(databaseUrl);

    const sql = sqlClient(databaseUrl);
    await sql`
      ALTER TABLE llm_proxy.config
      ADD COLUMN IF NOT EXISTS investment_usd NUMERIC
    `;
    await sql`
      ALTER TABLE llm_proxy.config
      ADD COLUMN IF NOT EXISTS projected_daily_spend_usd NUMERIC
    `;
  });

  afterAll(async () => {
    if (!databaseUrl) return;
    await upsertInvestmentConfig(
      databaseUrl,
      previousConfig?.investmentUsd ?? null,
      previousConfig?.projectedDailySpendUsd ?? null,
    );
  });

  test('upsert and fetch round-trip investment settings', async () => {
    const saved = await upsertInvestmentConfig(databaseUrl, TEST_INVESTMENT, TEST_DAILY);

    expect(saved.investmentUsd).toBe(TEST_INVESTMENT);
    expect(saved.projectedDailySpendUsd).toBe(TEST_DAILY);
    expect(saved.updatedAt).toBeTruthy();

    const loaded = await fetchInvestmentConfig(databaseUrl);
    expect(loaded.investmentUsd).toBe(TEST_INVESTMENT);
    expect(loaded.projectedDailySpendUsd).toBe(TEST_DAILY);
  });

  test('allows clearing projected daily spend', async () => {
    const saved = await upsertInvestmentConfig(databaseUrl, TEST_INVESTMENT, null);
    expect(saved.projectedDailySpendUsd).toBeNull();

    const loaded = await fetchInvestmentConfig(databaseUrl);
    expect(loaded.projectedDailySpendUsd).toBeNull();
  });
});
