/** @jsxImportSource hono/jsx/dom */

export function Spinner({ size = 'md' }: { size?: 'sm' | 'md' | 'lg' }) {
  return <span class={`spinner spinner-${size}`} aria-hidden="true" />;
}
