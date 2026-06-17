import { describe, expect, test } from 'bun:test';
import {
  backendHeadersToEntries,
  parseBackendHeadersFromDb,
  parseBackendHeadersInput,
} from '../src/backend-headers';

describe('parseBackendHeadersInput', () => {
  test('accepts array of name/value pairs', () => {
    expect(
      parseBackendHeadersInput([
        { name: 'Authorization', value: 'Bearer sk-test' },
        { name: 'x-api-key', value: 'abc' },
      ]),
    ).toEqual({
      Authorization: 'Bearer sk-test',
      'x-api-key': 'abc',
    });
  });

  test('skips blank header names', () => {
    expect(
      parseBackendHeadersInput([
        { name: '  ', value: 'ignored' },
        { name: 'Authorization', value: 'Bearer sk-test' },
      ]),
    ).toEqual({ Authorization: 'Bearer sk-test' });
  });

  test('rejects invalid header names', () => {
    expect(() => parseBackendHeadersInput([{ name: 'bad header', value: 'x' }])).toThrow(
      'Invalid header name',
    );
  });

  test('rejects blocked hop-by-hop headers', () => {
    expect(() => parseBackendHeadersInput([{ name: 'Host', value: 'evil' }])).toThrow(
      'Header not allowed',
    );
  });
});

describe('parseBackendHeadersFromDb', () => {
  test('returns empty object for invalid stored values', () => {
    expect(parseBackendHeadersFromDb(null)).toEqual({});
    expect(parseBackendHeadersFromDb([])).toEqual({});
  });

  test('loads string values and drops blocked headers', () => {
    expect(
      parseBackendHeadersFromDb({
        Authorization: 'Bearer sk-test',
        host: 'evil',
        ignored: 1,
      }),
    ).toEqual({ Authorization: 'Bearer sk-test' });
  });
});

describe('backendHeadersToEntries', () => {
  test('sorts entries by name', () => {
    expect(
      backendHeadersToEntries({
        'x-api-key': 'abc',
        Authorization: 'Bearer sk-test',
      }),
    ).toEqual([
      { name: 'Authorization', value: 'Bearer sk-test' },
      { name: 'x-api-key', value: 'abc' },
    ]);
  });
});
