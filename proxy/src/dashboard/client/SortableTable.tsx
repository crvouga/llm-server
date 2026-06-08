/** @jsxImportSource hono/jsx/dom */
import { useState } from 'hono/jsx';
import { formatInt, formatPercent, formatTps, formatUsd } from '../lib/format';
import { sortDirToMultiplier } from '../lib/query-params';
import type { ModelUsageRow, SortDir, SortKey, UsageSummary } from '../types';

const COLUMNS = [
  { key: 'model', label: 'Model', numeric: false },
  { key: 'requestCount', label: 'Requests', numeric: true },
  { key: 'promptTokens', label: 'Prompt', numeric: true },
  { key: 'completionTokens', label: 'Completion', numeric: true },
  { key: 'totalTokens', label: 'Total', numeric: true },
  { key: 'avgTokensPerRequest', label: 'Avg / req', numeric: true },
  { key: 'avgTokensPerSecond', label: 'Avg tok/s', numeric: true },
  { key: 'avgOverallTps', label: 'Overall tok/s', numeric: true },
  { key: 'avgGenerationTps', label: 'Gen tok/s', numeric: true },
  { key: 'percentOfTotal', label: '% of total', numeric: true },
  { key: 'estCostUsd', label: 'Est. cost', numeric: true },
] as const satisfies ReadonlyArray<{ key: SortKey; label: string; numeric: boolean }>;

function cellValue(row: ModelUsageRow, key: SortKey): string | number {
  if (key === 'model') return row.model;
  if (key === 'avgTokensPerRequest') return Math.round(row.avgTokensPerRequest);
  if (key === 'avgTokensPerSecond') return row.avgTokensPerSecond ?? -1;
  if (key === 'avgOverallTps') return row.avgOverallTps ?? -1;
  if (key === 'avgGenerationTps') return row.avgGenerationTps ?? -1;
  return row[key];
}

function formatCell(row: ModelUsageRow, key: SortKey): string {
  if (key === 'model') return row.model;
  if (key === 'percentOfTotal') return formatPercent(row.percentOfTotal);
  if (key === 'estCostUsd') return formatUsd(row.estCostUsd);
  if (key === 'avgTokensPerRequest') return formatInt(Math.round(row.avgTokensPerRequest));
  if (key === 'avgTokensPerSecond') return formatTps(row.avgTokensPerSecond);
  if (key === 'avgOverallTps') return formatTps(row.avgOverallTps);
  if (key === 'avgGenerationTps') return formatTps(row.avgGenerationTps);
  return formatInt(row[key]);
}

function updateSortInUrl(sortKey: SortKey, sortDir: SortDir) {
  const url = new URL(window.location.href);
  if (sortKey === 'totalTokens') {
    url.searchParams.delete('sort');
  } else {
    url.searchParams.set('sort', sortKey);
  }
  if (sortDir === 'desc') {
    url.searchParams.delete('dir');
  } else {
    url.searchParams.set('dir', sortDir);
  }
  history.replaceState(null, '', url);
}

export function SortableTable({
  rows,
  totals,
  initialSortKey = 'totalTokens',
  initialSortDir = 'desc',
}: {
  rows: ModelUsageRow[];
  totals: UsageSummary['totals'];
  initialSortKey?: SortKey;
  initialSortDir?: SortDir;
}) {
  const [sortKey, setSortKey] = useState<SortKey>(initialSortKey);
  const [sortDir, setSortDir] = useState<SortDir>(initialSortDir);
  const sortMultiplier = sortDirToMultiplier(sortDir);

  const sortedRows = [...rows].sort((a, b) => {
    const av = cellValue(a, sortKey);
    const bv = cellValue(b, sortKey);
    if (typeof av === 'number' && typeof bv === 'number') {
      return (av - bv) * sortMultiplier;
    }
    return String(av).localeCompare(String(bv)) * sortMultiplier;
  });

  function onHeaderClick(key: SortKey) {
    let nextDir: SortDir;
    if (sortKey === key) {
      nextDir = sortDir === 'asc' ? 'desc' : 'asc';
    } else {
      nextDir = 'desc';
    }
    setSortKey(key);
    setSortDir(nextDir);
    updateSortInUrl(key, nextDir);
  }

  return (
    <div class="table-scroll">
      <table id="usage-table">
        <thead>
          <tr>
            {COLUMNS.map((col, i) => (
              <th
                class={`sortable${col.numeric ? ' num' : ''}${sortKey === col.key ? (sortDir === 'asc' ? ' sort-asc' : ' sort-desc') : ''}`}
                data-col={String(i)}
                onClick={() => onHeaderClick(col.key)}
              >
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sortedRows.map((row) => (
            <tr>
              {COLUMNS.map((col) => (
                <td class={col.numeric ? 'num' : undefined}>
                  {col.key === 'model' ? <code>{row.model}</code> : formatCell(row, col.key)}
                </td>
              ))}
            </tr>
          ))}
          <tr class="total-row">
            <td>
              <strong>Total</strong>
            </td>
            <td class="num">
              <strong>{formatInt(totals.requestCount)}</strong>
            </td>
            <td class="num">
              <strong>{formatInt(totals.promptTokens)}</strong>
            </td>
            <td class="num">
              <strong>{formatInt(totals.completionTokens)}</strong>
            </td>
            <td class="num">
              <strong>{formatInt(totals.totalTokens)}</strong>
            </td>
            <td class="num">—</td>
            <td class="num">
              <strong>{formatTps(totals.avgTokensPerSecond)}</strong>
            </td>
            <td class="num">
              <strong>{formatTps(totals.avgOverallTps)}</strong>
            </td>
            <td class="num">
              <strong>{formatTps(totals.avgGenerationTps)}</strong>
            </td>
            <td class="num">
              <strong>100%</strong>
            </td>
            <td class="num">
              <strong>{formatUsd(totals.estCostUsd)}</strong>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}
