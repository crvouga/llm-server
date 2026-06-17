import { Card, Chip } from '@heroui/react';
import { formatDateRangeLabel, formatInt, formatUsd } from '../lib/format';
import type { DashboardFilters, DashboardSummary } from '../lib/types';

interface SummaryCardsProps {
  summary: DashboardSummary;
  filters: Pick<DashboardFilters, 'dateBucket' | 'startDate' | 'endDate'>;
}

export function SummaryCards({ summary, filters }: SummaryCardsProps) {
  return (
    <>
      <div className="mb-3 grid min-w-0 w-full grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Card className="min-w-0 w-full border-blue-200 bg-linear-to-br from-blue-50 to-white dark:border-blue-900 dark:from-blue-950 dark:to-slate-900 md:col-span-2 xl:col-span-4">
          <Card.Content className="p-5">
            <div className="text-xs font-semibold uppercase tracking-wide text-blue-600 dark:text-blue-400">
              Est. cloud cost
            </div>
            <div className="mt-1 text-4xl font-extrabold text-blue-600 dark:text-blue-400">
              {formatUsd(summary.totals.estCostUsd)}
            </div>
            <div className="mt-2 text-sm text-slate-500 dark:text-slate-400">
              What this proxy would have cost on cloud — local inference assumed free
            </div>
          </Card.Content>
        </Card>
        <Card className="min-w-0 w-full">
          <Card.Content className="p-5">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Total requests</div>
            <div className="mt-1 text-2xl font-bold tabular-nums">{formatInt(summary.totals.requestCount)}</div>
          </Card.Content>
        </Card>
        <Card className="min-w-0 w-full">
          <Card.Content className="p-5">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Total tokens</div>
            <div className="mt-1 text-2xl font-bold tabular-nums">{formatInt(summary.totals.totalTokens)}</div>
            <div className="mt-1 text-sm text-slate-500">
              {formatInt(summary.totals.promptTokens)} prompt · {formatInt(summary.totals.completionTokens)} completion
            </div>
          </Card.Content>
        </Card>
        <Card className="min-w-0 w-full">
          <Card.Content className="p-5">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Models queried</div>
            <div className="mt-1 text-2xl font-bold tabular-nums">{formatInt(summary.totals.modelCount)}</div>
          </Card.Content>
        </Card>
      </div>
      <div className="mb-6">
        <Chip size="md" variant="soft" color="accent">
          <Chip.Label>{formatDateRangeLabel(filters)}</Chip.Label>
        </Chip>
      </div>
    </>
  );
}
