import { neon } from '@neondatabase/serverless';

export interface SavedInvestmentConfig {
  investmentUsd: number | null;
  projectedDailySpendUsd: number | null;
  updatedAt: string | null;
}

function parseNullableUsd(value: unknown): number | null {
  if (value == null) {
    return null;
  }
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0) {
    return null;
  }
  return parsed;
}

export function parseInvestmentUsd(value: unknown): number | null {
  if (value == null || value === '') {
    return null;
  }
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 0) {
    return null;
  }
  return parsed;
}

export async function fetchInvestmentConfig(databaseUrl: string): Promise<SavedInvestmentConfig> {
  const sql = neon(databaseUrl);
  const rows = await sql`
    SELECT
      investment_usd,
      projected_daily_spend_usd,
      updated_at
    FROM llm_proxy.config
    WHERE id = 1
    LIMIT 1
  `;

  if (rows.length === 0) {
    return {
      investmentUsd: null,
      projectedDailySpendUsd: null,
      updatedAt: null,
    };
  }

  const row = rows[0];
  return {
    investmentUsd: parseNullableUsd(row.investment_usd),
    projectedDailySpendUsd: parseNullableUsd(row.projected_daily_spend_usd),
    updatedAt: row.updated_at ? String(row.updated_at) : null,
  };
}

export async function upsertInvestmentConfig(
  databaseUrl: string,
  investmentUsd: number | null,
  projectedDailySpendUsd: number | null,
): Promise<SavedInvestmentConfig> {
  const sql = neon(databaseUrl);
  const rows = await sql`
    UPDATE llm_proxy.config
    SET
      investment_usd = ${investmentUsd},
      projected_daily_spend_usd = ${projectedDailySpendUsd},
      updated_at = NOW()
    WHERE id = 1
    RETURNING
      investment_usd,
      projected_daily_spend_usd,
      updated_at
  `;

  if (rows.length === 0) {
    return {
      investmentUsd,
      projectedDailySpendUsd,
      updatedAt: null,
    };
  }

  const row = rows[0];
  return {
    investmentUsd: parseNullableUsd(row.investment_usd),
    projectedDailySpendUsd: parseNullableUsd(row.projected_daily_spend_usd),
    updatedAt: row.updated_at ? String(row.updated_at) : null,
  };
}
