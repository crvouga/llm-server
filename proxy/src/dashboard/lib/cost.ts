import { TOKENS_PER_MILLION } from '../constants';
import type { DashboardFilters, ModelCostRates } from '../types';

export function perMillionToPerToken(perMillion: number): number {
  return perMillion / TOKENS_PER_MILLION;
}

export function rowRates(filters: DashboardFilters, model: string): ModelCostRates {
  return filters.modelCosts.get(model) ?? filters.defaultRates;
}

export function rowCostUsd(
  promptTokens: number,
  completionTokens: number,
  rates: ModelCostRates,
): number {
  return (
    promptTokens * perMillionToPerToken(rates.inputPerMillion) +
    completionTokens * perMillionToPerToken(rates.outputPerMillion)
  );
}
