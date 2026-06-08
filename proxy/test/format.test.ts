import { describe, expect, test } from 'bun:test';
import { formatTps } from '../src/dashboard/lib/format';

describe('formatTps', () => {
  test('returns em dash for null', () => {
    expect(formatTps(null)).toBe('—');
  });

  test('returns em dash for NaN and Infinity', () => {
    expect(formatTps(Number.NaN)).toBe('—');
    expect(formatTps(Number.POSITIVE_INFINITY)).toBe('—');
    expect(formatTps(Number.NEGATIVE_INFINITY)).toBe('—');
  });

  test('formats zero as 0.0', () => {
    expect(formatTps(0)).toBe('0.0');
  });

  test('formats values with one decimal place', () => {
    expect(formatTps(42.567)).toBe('42.6');
    expect(formatTps(40)).toBe('40.0');
  });
});
