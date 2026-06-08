import { describe, expect, test } from 'bun:test';
import { resolveDateRange } from '../src/dashboard/lib/date-range';
import { parseFiltersFromQuery } from '../src/dashboard/lib/query-params';

describe('resolveDateRange', () => {
  const earliest = '2024-06-15';
  const today = '2025-03-10';

  test('all_time spans earliest through today', () => {
    expect(resolveDateRange('all_time', earliest, today)).toEqual({
      startDate: earliest,
      endDate: today,
    });
  });

  test('today is a single day', () => {
    expect(resolveDateRange('today', earliest, today)).toEqual({
      startDate: today,
      endDate: today,
    });
  });

  test('this_week starts on Monday', () => {
    expect(resolveDateRange('this_week', earliest, today)).toEqual({
      startDate: '2025-03-10',
      endDate: today,
    });
  });

  test('this_month starts on first of month', () => {
    expect(resolveDateRange('this_month', earliest, today)).toEqual({
      startDate: '2025-03-01',
      endDate: today,
    });
  });

  test('this_year starts on Jan 1', () => {
    expect(resolveDateRange('this_year', earliest, today)).toEqual({
      startDate: '2025-01-01',
      endDate: today,
    });
  });
});

describe('parseFiltersFromQuery', () => {
  const earliest = '2024-01-01';
  const models = ['gpt-test', 'claude-test'];

  test('defaults to all_time with default cost rates', () => {
    const filters = parseFiltersFromQuery({}, earliest, models);

    expect(filters.dateBucket).toBe('all_time');
    expect(filters.startDate).toBe(earliest);
    expect(filters.sortKey).toBe('totalTokens');
    expect(filters.sortDir).toBe('desc');
    expect(filters.defaultRates).toEqual({ inputPerMillion: 1, outputPerMillion: 2 });
  });

  test('parses per-model cost brackets', () => {
    const filters = parseFiltersFromQuery(
      {
        'input_cost[gpt-test]': '0.5',
        'output_cost[gpt-test]': '1.5',
      },
      earliest,
      models,
    );

    expect(filters.modelCosts.get('gpt-test')).toEqual({
      inputPerMillion: 0.5,
      outputPerMillion: 1.5,
    });
    expect(filters.modelCosts.get('claude-test')).toEqual({
      inputPerMillion: 1,
      outputPerMillion: 2,
    });
  });

  test('falls back for invalid sort key and direction', () => {
    const filters = parseFiltersFromQuery(
      { sort: 'not-a-key', dir: 'sideways' },
      earliest,
      models,
    );

    expect(filters.sortKey).toBe('totalTokens');
    expect(filters.sortDir).toBe('desc');
  });

  test('parses global cost overrides', () => {
    const filters = parseFiltersFromQuery(
      { input_cost: '3', output_cost: '4' },
      earliest,
      models,
    );

    expect(filters.defaultRates).toEqual({ inputPerMillion: 3, outputPerMillion: 4 });
  });
});
