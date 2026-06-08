export interface ModelUsageRow {
  model: string;
  requestCount: number;
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  avgTokensPerRequest: number;
  percentOfTotal: number;
  estCostUsd: number;
}

export type RawModelUsageRow = Omit<
  ModelUsageRow,
  'totalTokens' | 'avgTokensPerRequest' | 'percentOfTotal' | 'estCostUsd'
>;

export interface DailyUsageRow {
  day: string;
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
}

import type { DateBucket } from './lib/date-range';

export const SORT_KEYS = [
  'model',
  'requestCount',
  'promptTokens',
  'completionTokens',
  'totalTokens',
  'avgTokensPerRequest',
  'percentOfTotal',
  'estCostUsd',
] as const;

export type SortKey = (typeof SORT_KEYS)[number];
export type SortDir = 'asc' | 'desc';

export interface ModelCostRates {
  inputPerMillion: number;
  outputPerMillion: number;
}

export interface DashboardFilters {
  dateBucket: DateBucket;
  startDate: string;
  endDate: string;
  defaultRates: ModelCostRates;
  modelCosts: Map<string, ModelCostRates>;
  sortKey: SortKey;
  sortDir: SortDir;
}

export interface UsageSummary {
  rows: ModelUsageRow[];
  totals: {
    requestCount: number;
    promptTokens: number;
    completionTokens: number;
    totalTokens: number;
    estCostUsd: number;
    modelCount: number;
  };
}

export interface DashboardPayload {
  models: string[];
  labels: string[];
  totalTokens: number[];
  promptTokens: number[];
  completionTokens: number[];
  estCostUsd: number[];
  dailyLabels: string[];
  dailyPrompt: number[];
  dailyCompletion: number[];
  dailyTotal: number[];
  colors: string[];
  rows: ModelUsageRow[];
  totals: UsageSummary['totals'];
  sortKey: SortKey;
  sortDir: SortDir;
}

export type DashboardEnv = {
  Bindings: {
    DATABASE_URL: string;
  };
};

declare global {
  interface Window {
    __DASHBOARD_DATA__?: DashboardPayload;
  }
}
