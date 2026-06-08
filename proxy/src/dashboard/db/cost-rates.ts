import { neon } from '@neondatabase/serverless';
import { DEFAULT_INPUT_COST_PER_MILLION, DEFAULT_OUTPUT_COST_PER_MILLION } from '../constants';
import type { ModelCostRates } from '../types';

export interface SavedCostRates {
  defaultRates: ModelCostRates;
  modelOverrides: Map<string, ModelCostRates>;
  updatedAt: string | null;
}

function parseModelOverrides(raw: unknown): Map<string, ModelCostRates> {
  const overrides = new Map<string, ModelCostRates>();
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    return overrides;
  }

  for (const [model, value] of Object.entries(raw)) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      continue;
    }
    const input = Number((value as Record<string, unknown>).inputPerMillion);
    const output = Number((value as Record<string, unknown>).outputPerMillion);
    if (!Number.isFinite(input) || !Number.isFinite(output)) {
      continue;
    }
    overrides.set(model, { inputPerMillion: input, outputPerMillion: output });
  }

  return overrides;
}

function modelOverridesToJson(
  defaultRates: ModelCostRates,
  modelCosts: Map<string, ModelCostRates>,
): Record<string, ModelCostRates> {
  const json: Record<string, ModelCostRates> = {};
  for (const [model, rates] of modelCosts) {
    if (
      rates.inputPerMillion !== defaultRates.inputPerMillion ||
      rates.outputPerMillion !== defaultRates.outputPerMillion
    ) {
      json[model] = rates;
    }
  }
  return json;
}

export async function fetchCostRates(databaseUrl: string): Promise<SavedCostRates | null> {
  const sql = neon(databaseUrl);
  const rows = await sql`
    SELECT
      input_per_million,
      output_per_million,
      model_overrides,
      updated_at
    FROM llm_proxy.cost_rates
    WHERE id = 1
    LIMIT 1
  `;

  if (rows.length === 0) {
    return null;
  }

  const row = rows[0];
  return {
    defaultRates: {
      inputPerMillion: Number(row.input_per_million),
      outputPerMillion: Number(row.output_per_million),
    },
    modelOverrides: parseModelOverrides(row.model_overrides),
    updatedAt: row.updated_at ? String(row.updated_at) : null,
  };
}

export function defaultSavedCostRates(): SavedCostRates {
  return {
    defaultRates: {
      inputPerMillion: DEFAULT_INPUT_COST_PER_MILLION,
      outputPerMillion: DEFAULT_OUTPUT_COST_PER_MILLION,
    },
    modelOverrides: new Map(),
    updatedAt: null,
  };
}

export async function upsertCostRates(
  databaseUrl: string,
  defaultRates: ModelCostRates,
  modelCosts: Map<string, ModelCostRates>,
): Promise<SavedCostRates> {
  const sql = neon(databaseUrl);
  const modelOverrides = modelOverridesToJson(defaultRates, modelCosts);

  const rows = await sql`
    INSERT INTO llm_proxy.cost_rates (
      id,
      input_per_million,
      output_per_million,
      model_overrides,
      updated_at
    )
    VALUES (
      1,
      ${defaultRates.inputPerMillion},
      ${defaultRates.outputPerMillion},
      ${JSON.stringify(modelOverrides)}::jsonb,
      NOW()
    )
    ON CONFLICT (id) DO UPDATE
    SET
      input_per_million = EXCLUDED.input_per_million,
      output_per_million = EXCLUDED.output_per_million,
      model_overrides = EXCLUDED.model_overrides,
      updated_at = NOW()
    RETURNING
      input_per_million,
      output_per_million,
      model_overrides,
      updated_at
  `;

  const row = rows[0];
  return {
    defaultRates: {
      inputPerMillion: Number(row.input_per_million),
      outputPerMillion: Number(row.output_per_million),
    },
    modelOverrides: parseModelOverrides(row.model_overrides),
    updatedAt: row.updated_at ? String(row.updated_at) : null,
  };
}
