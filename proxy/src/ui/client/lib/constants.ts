export {
  BACKEND_CONFIG_PATH,
  BACKEND_HEALTH_PATH,
  COST_RATES_PATH,
  DASHBOARD_DATA_API_PATH,
  INVESTMENT_DATA_PATH,
  MODELS_API_PATH,
  TAB_CHAT,
  TAB_DASHBOARD,
  TAB_QUERY_PARAM,
  UI_PATH,
} from '../../../shared/constants';

export const CHAT_COMPLETIONS_PATH = '/v1/chat/completions';

export const DEFAULT_INPUT_COST = 1;
export const DEFAULT_OUTPUT_COST = 2;

export const DATE_BUCKETS = [
  { id: 'today', label: 'Today' },
  { id: 'this_week', label: 'This week' },
  { id: 'this_month', label: 'This month' },
  { id: 'this_year', label: 'This year' },
  { id: 'all_time', label: 'All time' },
] as const;

export const DATE_BUCKET_LABELS: Record<string, string> = {
  today: 'Today',
  this_week: 'This week',
  this_month: 'This month',
  this_year: 'This year',
  all_time: 'All time',
};

export const TABLE_COLUMNS = [
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
] as const;

export const DASHBOARD_FORM_ID = 'dashboard-form';

export const TOP_BAR_ACTION_CLASS =
  'app-top-bar-action inline-flex shrink-0 items-center justify-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50 text-sm font-semibold transition hover:border-blue-500 hover:bg-blue-50 hover:text-blue-600 disabled:cursor-not-allowed disabled:opacity-70 dark:border-slate-700 dark:bg-slate-950 dark:hover:border-blue-400 dark:hover:bg-slate-800 h-8 w-8 p-0 md:h-auto md:w-auto md:min-h-[44px] md:min-w-[88px] md:px-3.5 md:py-2';
