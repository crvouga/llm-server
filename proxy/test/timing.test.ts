import { describe, expect, test } from 'bun:test';
import { computeGenerationTps, computeOverallTps } from '../src/dashboard/lib/timing';

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
});
