/** @jsxImportSource hono/jsx/dom */
import { render } from 'hono/jsx/dom';
import { DashboardClient } from './DashboardClient';

const data = window.__DASHBOARD_DATA__;
const root = document.getElementById('dashboard-client');

if (data && root) {
  render(<DashboardClient data={data} />, root);
}
