/** @jsxImportSource hono/jsx/dom */
import type { DashboardPayload } from '../types';
import { Charts } from './Charts';
import { SortableTable } from './SortableTable';

export function DashboardClient({ data }: { data: DashboardPayload }) {
  return (
    <>
      <Charts data={data} />
      <div class="card">
        <h2>Per-model breakdown</h2>
        <p class="card-subtitle">
          Click column headers to sort. Default order: total tokens descending.
        </p>
        <SortableTable
          rows={data.rows}
          totals={data.totals}
          initialSortKey={data.sortKey}
          initialSortDir={data.sortDir}
        />
      </div>
    </>
  );
}
