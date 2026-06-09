import bundledHtml from './single-page-app.html';

export function getUiAppHtml(): string {
  return bundledHtml as unknown as string;
}
