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
