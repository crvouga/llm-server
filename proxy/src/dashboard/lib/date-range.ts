import { todayIsoDate } from './format';

export const DATE_BUCKETS = [
  { id: 'today', label: 'Today' },
  { id: 'this_week', label: 'This week' },
  { id: 'this_month', label: 'This month' },
  { id: 'this_year', label: 'This year' },
  { id: 'all_time', label: 'All time' },
] as const;

export type DateBucket = (typeof DATE_BUCKETS)[number]['id'];

export const DATE_BUCKET_LABELS: Record<DateBucket, string> = {
  today: 'Today',
  this_week: 'This week',
  this_month: 'This month',
  this_year: 'This year',
  all_time: 'All time',
};

export function isPresetDateBucket(value: string): value is DateBucket {
  return DATE_BUCKETS.some((bucket) => bucket.id === value);
}

function isoFromUtcDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

export function resolveDateRange(
  bucket: DateBucket,
  earliestDate: string,
  today: string = todayIsoDate(),
): { startDate: string; endDate: string } {
  const endDate = today;

  if (bucket === 'all_time') {
    return { startDate: earliestDate, endDate };
  }

  if (bucket === 'today') {
    return { startDate: today, endDate: today };
  }

  const [year, month, day] = today.split('-').map(Number);
  const todayUtc = new Date(Date.UTC(year, month - 1, day));

  if (bucket === 'this_week') {
    const weekday = todayUtc.getUTCDay();
    const daysSinceMonday = (weekday + 6) % 7;
    const monday = new Date(todayUtc);
    monday.setUTCDate(todayUtc.getUTCDate() - daysSinceMonday);
    return { startDate: isoFromUtcDate(monday), endDate };
  }

  if (bucket === 'this_month') {
    return { startDate: isoFromUtcDate(new Date(Date.UTC(year, month - 1, 1))), endDate };
  }

  return { startDate: isoFromUtcDate(new Date(Date.UTC(year, 0, 1))), endDate };
}

export function formatDateRangeLabel(filters: {
  dateBucket: DateBucket;
  startDate: string;
  endDate: string;
}): string {
  const bucketLabel = DATE_BUCKET_LABELS[filters.dateBucket];
  if (filters.startDate === filters.endDate) {
    return `${bucketLabel} · ${filters.startDate}`;
  }
  return `${bucketLabel} · ${filters.startDate} → ${filters.endDate}`;
}
