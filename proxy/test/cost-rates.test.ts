import { afterAll, beforeAll, describe, expect, test } from 'bun:test';
import { fetchCostRates, upsertCostRates } from '../src/dashboard/db/cost-rates';
import { requireDatabaseUrl, sqlClient } from './helpers/db';

const SAVED_INPUT = 0.1;
const SAVED_OUTPUT = 0.75;

describe('cost rates persistence', () => {
  let databaseUrl = '';
  let previousRates: Awaited<ReturnType<typeof fetchCostRates>> = null;

  beforeAll(async () => {
    databaseUrl = requireDatabaseUrl();
    previousRates = await fetchCostRates(databaseUrl);

    const sql = sqlClient(databaseUrl);
    await sql`
      CREATE TABLE IF NOT EXISTS llm_proxy.cost_rates (
        id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
        input_per_million NUMERIC NOT NULL DEFAULT 1,
        output_per_million NUMERIC NOT NULL DEFAULT 2,
        model_overrides JSONB NOT NULL DEFAULT '{}',
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
      )
    `;
  });

  afterAll(async () => {
    const sql = sqlClient(databaseUrl);
    if (previousRates?.updatedAt) {
      const modelCosts = new Map(previousRates.modelOverrides);
      await upsertCostRates(databaseUrl, previousRates.defaultRates, modelCosts);
      return;
    }

    await sql`DELETE FROM llm_proxy.cost_rates WHERE id = 1`;
  });

  test('upsert and fetch round-trip default rates', async () => {
    const saved = await upsertCostRates(
      databaseUrl,
      { inputPerMillion: SAVED_INPUT, outputPerMillion: SAVED_OUTPUT },
      new Map(),
    );

    expect(saved.defaultRates).toEqual({
      inputPerMillion: SAVED_INPUT,
      outputPerMillion: SAVED_OUTPUT,
    });
    expect(saved.updatedAt).toBeTruthy();

    const loaded = await fetchCostRates(databaseUrl);
    expect(loaded?.defaultRates).toEqual(saved.defaultRates);
  });

  test('stores only per-model overrides that differ from defaults', async () => {
    const models = ['gpt-test', 'claude-test'];
    const modelCosts = new Map([
      ['gpt-test', { inputPerMillion: 0.5, outputPerMillion: 1.5 }],
      ['claude-test', { inputPerMillion: SAVED_INPUT, outputPerMillion: SAVED_OUTPUT }],
    ]);

    const saved = await upsertCostRates(
      databaseUrl,
      { inputPerMillion: SAVED_INPUT, outputPerMillion: SAVED_OUTPUT },
      modelCosts,
    );

    expect(saved.modelOverrides.size).toBe(1);
    expect(saved.modelOverrides.get('gpt-test')).toEqual({
      inputPerMillion: 0.5,
      outputPerMillion: 1.5,
    });
    expect(saved.modelOverrides.has('claude-test')).toBe(false);
  });
});
