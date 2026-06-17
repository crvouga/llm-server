import { useState } from 'react';
import { TABLE_COLUMNS } from '../lib/constants';
import { formatInt, formatPercent, formatTps, formatUsd } from '../lib/format';

type Row = Record<string, string | number | null>;

function cellValue(row: Row, key: string) {
  if (key === 'model') return row.model;
  if (key === 'avgTokensPerRequest') return Math.round(row.avgTokensPerRequest as number);
  if (key === 'avgTokensPerSecond') return row.avgTokensPerSecond ?? -1;
  if (key === 'avgOverallTps') return row.avgOverallTps ?? -1;
  if (key === 'avgGenerationTps') return row.avgGenerationTps ?? -1;
  return row[key];
}

function formatCell(row: Row, key: string) {
  if (key === 'model') return row.model;
  if (key === 'percentOfTotal') return formatPercent(row.percentOfTotal as number);
  if (key === 'estCostUsd') return formatUsd(row.estCostUsd as number);
  if (key === 'avgTokensPerRequest') return formatInt(Math.round(row.avgTokensPerRequest as number));
  if (key === 'avgTokensPerSecond') return formatTps(row.avgTokensPerSecond as number | null);
  if (key === 'avgOverallTps') return formatTps(row.avgOverallTps as number | null);
  if (key === 'avgGenerationTps') return formatTps(row.avgGenerationTps as number | null);
  return formatInt(row[key] as number);
}

interface SortableTableProps {
  rows: Row[];
  totals: Row;
  initialSortKey?: string;
  initialSortDir?: string;
}

export function SortableTable({
  rows,
  totals,
  initialSortKey = 'totalTokens',
  initialSortDir = 'desc',
}: SortableTableProps) {
  const [sortKey, setSortKey] = useState(initialSortKey);
  const [sortDir, setSortDir] = useState(initialSortDir);
  const multiplier = sortDir === 'asc' ? 1 : -1;

  const sortedRows = [...rows].sort((a, b) => {
    const av = cellValue(a, sortKey);
    const bv = cellValue(b, sortKey);
    if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * multiplier;
    return String(av).localeCompare(String(bv)) * multiplier;
  });

  function onHeaderClick(key: string) {
    let nextDir: string;
    if (sortKey === key) nextDir = sortDir === 'asc' ? 'desc' : 'asc';
    else nextDir = 'desc';
    setSortKey(key);
    setSortDir(nextDir);
    const url = new URL(window.location.href);
    if (key === 'totalTokens') url.searchParams.delete('sort');
    else url.searchParams.set('sort', key);
    if (nextDir === 'desc') url.searchParams.delete('dir');
    else url.searchParams.set('dir', nextDir);
    history.replaceState(null, '', url);
  }

  return (
    <div className="min-w-0 w-full max-w-full overflow-x-auto -mx-2 px-2">
      <table className="w-full min-w-[640px] text-xs md:text-sm">
        <thead>
          <tr className="border-b border-separator text-left text-xs font-semibold uppercase tracking-wide text-muted">
            {TABLE_COLUMNS.map((col) => (
              <th
                key={col.key}
                className={`cursor-pointer px-3 py-2 hover:text-foreground ${col.numeric ? 'text-right' : ''}`}
                onClick={() => onHeaderClick(col.key)}
              >
                {col.label}
                {sortKey === col.key ? (sortDir === 'asc' ? ' ↑' : ' ↓') : ''}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sortedRows.map((row) => (
            <tr key={String(row.model)} className="border-b border-separator/60">
              {TABLE_COLUMNS.map((col) => (
                <td key={col.key} className={`px-3 py-2 ${col.numeric ? 'text-right tabular-nums' : ''}`}>
                  {col.key === 'model' ? (
                    <code className="rounded bg-accent-soft px-1.5 py-0.5 text-xs text-accent-soft-foreground">
                      {row.model}
                    </code>
                  ) : (
                    formatCell(row, col.key)
                  )}
                </td>
              ))}
            </tr>
          ))}
          <tr className="border-t-2 border-separator font-semibold">
            <td className="px-3 py-2">Total</td>
            <td className="px-3 py-2 text-right tabular-nums">{formatInt(totals.requestCount as number)}</td>
            <td className="px-3 py-2 text-right tabular-nums">{formatInt(totals.promptTokens as number)}</td>
            <td className="px-3 py-2 text-right tabular-nums">{formatInt(totals.completionTokens as number)}</td>
            <td className="px-3 py-2 text-right tabular-nums">{formatInt(totals.totalTokens as number)}</td>
            <td className="px-3 py-2 text-right">—</td>
            <td className="px-3 py-2 text-right tabular-nums">
              {formatTps(totals.avgTokensPerSecond as number | null)}
            </td>
            <td className="px-3 py-2 text-right tabular-nums">
              {formatTps(totals.avgOverallTps as number | null)}
            </td>
            <td className="px-3 py-2 text-right tabular-nums">
              {formatTps(totals.avgGenerationTps as number | null)}
            </td>
            <td className="px-3 py-2 text-right">100%</td>
            <td className="px-3 py-2 text-right tabular-nums">{formatUsd(totals.estCostUsd as number)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}
