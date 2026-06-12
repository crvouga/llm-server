import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const uiAppHtml = readFileSync(join(import.meta.dir, 'single-page-app.html'), 'utf-8');

export function getUiAppHtml(): string {
  return uiAppHtml;
}
