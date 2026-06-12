import { describe, expect, test } from 'bun:test';
import { getUiAppHtml } from '../src/ui/ui-html';

describe('getUiAppHtml', () => {
  test('returns bundled HTML string, not HTMLBundle object', () => {
    const html = getUiAppHtml();

    expect(typeof html).toBe('string');
    expect(html).toContain('<!DOCTYPE html>');
    expect(html).toContain('LLM Proxy');
    expect(html).not.toBe('[object HTMLBundle]');
  });
});
