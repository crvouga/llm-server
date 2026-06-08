import { describe, expect, test } from 'bun:test';
import {
  computeAvgTokensPerSecond,
  computeGenerationTps,
  computeOverallTps,
  isValidTimingRow,
} from '../src/dashboard/lib/timing';
import type { RawModelUsageRow } from '../src/dashboard/types';

describe('computeOverallTps', () => {
  test('returns weighted tokens per second', () => {
    expect(computeOverallTps(60, 1500)).toBeCloseTo(40, 5);
  });

  test('returns null for zero duration', () => {
    expect(computeOverallTps(10, 0)).toBeNull();
  });

  test('returns null for negative duration', () => {
    expect(computeOverallTps(10, -1)).toBeNull();
  });

  test('returns zero when completion tokens are zero', () => {
    expect(computeOverallTps(0, 1000)).toBe(0);
  });

  test('returns null for NaN inputs', () => {
    expect(computeOverallTps(Number.NaN, 1000)).toBeNull();
    expect(computeOverallTps(10, Number.NaN)).toBeNull();
  });

  test('returns null for Infinity inputs', () => {
    expect(computeOverallTps(Number.POSITIVE_INFINITY, 1000)).toBeNull();
    expect(computeOverallTps(10, Number.POSITIVE_INFINITY)).toBeNull();
  });
});

describe('computeAvgTokensPerSecond', () => {
  test('returns total tokens per second', () => {
    expect(computeAvgTokensPerSecond(150, 1500)).toBeCloseTo(100, 5);
  });

  test('returns null for zero duration', () => {
    expect(computeAvgTokensPerSecond(10, 0)).toBeNull();
  });

  test('returns null for negative duration', () => {
    expect(computeAvgTokensPerSecond(10, -1)).toBeNull();
  });

  test('returns zero when total tokens are zero', () => {
    expect(computeAvgTokensPerSecond(0, 1000)).toBe(0);
  });

  test('returns null for NaN inputs', () => {
    expect(computeAvgTokensPerSecond(Number.NaN, 1000)).toBeNull();
    expect(computeAvgTokensPerSecond(10, Number.NaN)).toBeNull();
  });
});

describe('computeGenerationTps', () => {
  test('returns weighted generation tokens per second', () => {
    expect(computeGenerationTps(30, 600)).toBeCloseTo(50, 5);
  });

  test('returns null for zero generation window', () => {
    expect(computeGenerationTps(10, 0)).toBeNull();
  });

  test('returns null for negative generation window', () => {
    expect(computeGenerationTps(10, -1)).toBeNull();
  });

  test('returns null for NaN inputs', () => {
    expect(computeGenerationTps(Number.NaN, 600)).toBeNull();
    expect(computeGenerationTps(10, Number.NaN)).toBeNull();
  });

  test('returns null for Infinity inputs', () => {
    expect(computeGenerationTps(Number.POSITIVE_INFINITY, 600)).toBeNull();
    expect(computeGenerationTps(10, Number.POSITIVE_INFINITY)).toBeNull();
  });
});

describe('isValidTimingRow', () => {
  test('returns true for consistent timing aggregates', () => {
    const row: RawModelUsageRow = {
      model: 'alpha',
      requestCount: 2,
      promptTokens: 10,
      completionTokens: 60,
      timedCompletionTokens: 50,
      totalDurationMs: 1500,
      generationCompletionTokens: 40,
      totalGenerationMs: 900,
    };
    expect(isValidTimingRow(row)).toBe(true);
  });

  test('returns false when timed tokens exceed completion tokens', () => {
    const row: RawModelUsageRow = {
      model: 'alpha',
      requestCount: 1,
      promptTokens: 0,
      completionTokens: 10,
      timedCompletionTokens: 20,
      totalDurationMs: 1000,
      generationCompletionTokens: 0,
      totalGenerationMs: 0,
    };
    expect(isValidTimingRow(row)).toBe(false);
  });

  test('returns false when generation tokens exceed timed tokens', () => {
    const row: RawModelUsageRow = {
      model: 'alpha',
      requestCount: 1,
      promptTokens: 0,
      completionTokens: 50,
      timedCompletionTokens: 50,
      totalDurationMs: 1000,
      generationCompletionTokens: 60,
      totalGenerationMs: 500,
    };
    expect(isValidTimingRow(row)).toBe(false);
  });

  test('returns false when generation ms exceeds total duration ms', () => {
    const row: RawModelUsageRow = {
      model: 'alpha',
      requestCount: 1,
      promptTokens: 0,
      completionTokens: 50,
      timedCompletionTokens: 50,
      totalDurationMs: 500,
      generationCompletionTokens: 50,
      totalGenerationMs: 600,
    };
    expect(isValidTimingRow(row)).toBe(false);
  });
});
