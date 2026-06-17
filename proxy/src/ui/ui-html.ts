import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const uiAppHtml = readFileSync(join(import.meta.dir, '../../public/assets/index.html'), 'utf-8');

export function getUiAppHtml(): string {
  return uiAppHtml;
}
