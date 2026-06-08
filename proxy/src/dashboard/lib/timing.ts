import type { RawModelUsageRow } from '../types';

export function computeOverallTps(
  timedCompletionTokens: number,
  totalDurationMs: number,
): number | null {
  if (
    !Number.isFinite(timedCompletionTokens) ||
    !Number.isFinite(totalDurationMs) ||
    timedCompletionTokens < 0 ||
    totalDurationMs <= 0
  ) {
    return null;
  }
  return timedCompletionTokens / (totalDurationMs / 1000);
}

export function computeAvgTokensPerSecond(
  totalTokens: number,
  totalDurationMs: number,
): number | null {
  if (
    !Number.isFinite(totalTokens) ||
    !Number.isFinite(totalDurationMs) ||
    totalTokens < 0 ||
    totalDurationMs <= 0
  ) {
    return null;
  }
  return totalTokens / (totalDurationMs / 1000);
}

export function computeGenerationTps(
  timedCompletionTokens: number,
  totalGenerationMs: number,
): number | null {
  if (
    !Number.isFinite(timedCompletionTokens) ||
    !Number.isFinite(totalGenerationMs) ||
    timedCompletionTokens < 0 ||
    totalGenerationMs <= 0
  ) {
    return null;
  }
  return timedCompletionTokens / (totalGenerationMs / 1000);
}

export function isValidTimingRow(row: RawModelUsageRow): boolean {
  return (
    row.timedCompletionTokens <= row.completionTokens &&
    row.generationCompletionTokens <= row.timedCompletionTokens &&
    row.totalGenerationMs <= row.totalDurationMs
  );
}
