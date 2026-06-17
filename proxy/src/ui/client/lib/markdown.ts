import hljs from 'highlight.js/lib/common';
import { marked } from 'marked';

function escapeHtml(text: string) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

const LANGUAGE_ALIASES: Record<string, string> = {
  js: 'javascript',
  jsx: 'javascript',
  mjs: 'javascript',
  cjs: 'javascript',
  ts: 'typescript',
  tsx: 'typescript',
  py: 'python',
  sh: 'bash',
  shell: 'bash',
  zsh: 'bash',
  yml: 'yaml',
  md: 'markdown',
  'c++': 'cpp',
  'c#': 'csharp',
  cs: 'csharp',
  golang: 'go',
  rs: 'rust',
  html: 'xml',
  svg: 'xml',
  htm: 'xml',
};

function normalizeLanguage(lang: string | undefined) {
  if (!lang || typeof lang !== 'string') return '';
  const normalized = lang.trim().toLowerCase();
  return LANGUAGE_ALIASES[normalized] || normalized;
}

function highlightCode(text: string, lang?: string) {
  const language = normalizeLanguage(lang);
  try {
    if (language && hljs.getLanguage(language)) {
      return {
        html: hljs.highlight(text, { language, ignoreIllegals: true }).value,
        language,
      };
    }
    const auto = hljs.highlightAuto(text, [
      'javascript',
      'typescript',
      'python',
      'bash',
      'json',
      'css',
      'xml',
      'markdown',
      'rust',
      'go',
      'java',
      'csharp',
      'cpp',
      'sql',
      'yaml',
      'php',
      'ruby',
      'kotlin',
      'swift',
    ]);
    return { html: auto.value, language: auto.language || 'plaintext' };
  } catch {
    return { html: escapeHtml(text), language: 'plaintext' };
  }
}

let markedConfigured = false;

function configureMarked() {
  if (markedConfigured) return;
  marked.use({
    breaks: true,
    gfm: true,
    renderer: {
      code({ text, lang }) {
        const { html, language } = highlightCode(text, lang);
        return `<pre><code class="hljs language-${language}">${html}</code></pre>`;
      },
    },
  });
  markedConfigured = true;
}

export function renderMarkdown(content: string) {
  if (!content.trim()) return '';
  configureMarked();
  return marked.parse(content, { async: false }) as string;
}
