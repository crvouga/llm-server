/** @jsxImportSource hono/jsx */
import type { FC } from 'hono/jsx';

const REFRESH_ICON = (
  <svg
    class="btn-refresh-icon"
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path d="M21 12a9 9 0 1 1-2.64-6.36" />
    <path d="M21 3v6h-6" />
  </svg>
);

export const AppTopBar: FC<{ formId: string }> = ({ formId }) => (
  <header class="top-bar">
    <div class="top-bar-inner">
      <h1 class="top-bar-title">LLM Proxy Dashboard</h1>
      <button type="submit" form={formId} class="btn-refresh">
        {REFRESH_ICON}
        Refresh
      </button>
    </div>
  </header>
);
