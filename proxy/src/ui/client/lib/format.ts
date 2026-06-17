import { DATE_BUCKET_LABELS } from './constants';

export function formatUsd(amount: number) {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  }).format(amount);
}

export function formatInt(value: number) {
  return new Intl.NumberFormat('en-US').format(value);
}

export function formatTps(value: number | null | undefined) {
  if (value === null || !Number.isFinite(value)) return '—';
  return new Intl.NumberFormat('en-US', {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }).format(value as number);
}

export function formatDurationMs(durationMs: number) {
  if (!Number.isFinite(durationMs) || durationMs < 0) return '—';
  if (durationMs < 1000) return `${Math.round(durationMs)}ms`;
  return `${(durationMs / 1000).toFixed(1)}s`;
}

export function computeTokensPerSecond(totalTokens: number, durationMs: number) {
  if (
    !Number.isFinite(totalTokens) ||
    !Number.isFinite(durationMs) ||
    totalTokens < 0 ||
    durationMs <= 0
  ) {
    return null;
  }
  return totalTokens / (durationMs / 1000);
}

export function formatPercent(value: number) {
  return new Intl.NumberFormat('en-US', {
    style: 'percent',
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }).format(value / 100);
}

export function formatDateRangeLabel(filters: {
  dateBucket: string;
  startDate: string;
  endDate: string;
}) {
  const bucketLabel = DATE_BUCKET_LABELS[filters.dateBucket] || filters.dateBucket;
  if (filters.startDate === filters.endDate) {
    return `${bucketLabel} · ${filters.startDate}`;
  }
  return `${bucketLabel} · ${filters.startDate} → ${filters.endDate}`;
}

export function formatIsoDateLabel(isoDate: string | null | undefined) {
  if (!isoDate) return '—';
  const [year, month, day] = isoDate.split('-').map(Number);
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC',
  });
}

export function rowRates(
  filters: {
    modelCosts: Record<string, { inputPerMillion: number; outputPerMillion: number }>;
    defaultRates: { inputPerMillion: number; outputPerMillion: number };
  },
  model: string,
) {
  return filters.modelCosts[model] || filters.defaultRates;
}
