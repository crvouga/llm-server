/** @jsxImportSource hono/jsx/dom */
import { render } from 'hono/jsx/dom';
import { Router } from './Router';

const root = document.getElementById('ui-root');

if (root) {
  render(<Router />, root);
}
