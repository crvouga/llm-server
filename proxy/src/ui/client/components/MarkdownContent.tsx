import { useMemo } from 'react';
import { renderMarkdown } from '../lib/markdown';

export function MarkdownContent({ content }: { content: string }) {
  const html = useMemo(() => renderMarkdown(content), [content]);
  if (!html) return null;
  return <div className="markdown-body text-[0.95rem] leading-7" dangerouslySetInnerHTML={{ __html: html }} />;
}
