export interface DashboardFilters {
  dateBucket: string;
  startDate: string;
  endDate: string;
  sortKey?: string;
  sortDir?: string;
  defaultRates: { inputPerMillion: number; outputPerMillion: number };
  modelCosts: Record<string, { inputPerMillion: number; outputPerMillion: number }>;
}

export interface DashboardSummary {
  rows: unknown[];
  totals: {
    estCostUsd: number;
    requestCount: number;
    totalTokens: number;
    promptTokens: number;
    completionTokens: number;
    modelCount: number;
  };
}

export interface SavedCostRates {
  updatedAt?: string;
  defaultRates: { inputPerMillion: number; outputPerMillion: number };
}

export interface DashboardPayload {
  rows: Record<string, string | number | null>[];
  totals: Record<string, string | number | null>;
  sortKey?: string;
  sortDir?: string;
}

export interface DashboardData {
  summary: DashboardSummary | null;
  filters: DashboardFilters;
  models: string[];
  savedCostRates: SavedCostRates | null;
  payload: DashboardPayload | null;
  error?: string;
}

export interface InvestmentConfig {
  investmentUsd?: number | null;
  projectedDailySpendUsd?: number | null;
}

export interface InvestmentMetrics {
  totalSavingsToDateUsd?: number;
  historicalAverageDailySpendUsd?: number | null;
  today?: string;
  actualBreakEvenDate?: string | null;
  calendarDays?: number;
}

export interface InvestmentData {
  config?: InvestmentConfig;
  metrics?: InvestmentMetrics;
}

export interface CostRatesBody {
  defaultRates: { inputPerMillion: number; outputPerMillion: number };
  modelCosts: Record<string, { inputPerMillion?: number; outputPerMillion?: number }>;
}

export interface InvestmentSaveBody {
  investmentUsd: number | null;
  projectedDailySpendUsd?: number | null;
  calculateFromHistory?: boolean;
}

export interface BackendConfig {
  backendUrl: string | null;
}

export interface BackendHealthChecks {
  configured: boolean;
  reachable: boolean;
  httpOk: boolean;
  openAiModels: boolean;
}

export interface BackendHealthResult {
  ok: boolean;
  backendUrl: string;
  latencyMs: number;
  httpStatus: number | null;
  modelCount: number;
  sampleModelIds: string[];
  checks: BackendHealthChecks;
  error: string | null;
  checkedAt: string;
}

export interface BackendConfigSaveBody {
  backendUrl: string;
}
