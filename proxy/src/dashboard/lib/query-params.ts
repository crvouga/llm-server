import {
  DASHBOARD_PATH,
  DEFAULT_INPUT_COST_PER_MILLION,
  DEFAULT_OUTPUT_COST_PER_MILLION,
} from '../constants';
import type { SavedCostRates } from '../db/cost-rates';
import {
  SORT_KEYS,
  type DashboardFilters,
  type ModelCostRates,
  type SortDir,
  type SortKey,
} from '../types';
import { isPresetDateBucket, resolveDateRange, type DateBucket } from './date-range';
import { parseCostPerMillion, todayIsoDate } from './format';

export type { SortDir, SortKey } from '../types';
export { SORT_KEYS } from '../types';

const INPUT_COST_BRACKET_RE = /^input_cost\[(.+)\]$/;
const OUTPUT_COST_BRACKET_RE = /^output_cost\[(.+)\]$/;

export interface DashboardUrlOverrides {
  dateBucket?: DateBucket;
  defaultRates?: Partial<ModelCostRates>;
  modelCosts?: Map<string, ModelCostRates>;
  sortKey?: SortKey;
  sortDir?: SortDir;
}

function isSortKey(value: string): value is SortKey {
  return (SORT_KEYS as readonly string[]).includes(value);
}

function isSortDir(value: string): value is SortDir {
  return value === 'asc' || value === 'desc';
}

function baseDefaultRates(savedRates: SavedCostRates | null | undefined): ModelCostRates {
  return savedRates?.defaultRates ?? {
    inputPerMillion: DEFAULT_INPUT_COST_PER_MILLION,
    outputPerMillion: DEFAULT_OUTPUT_COST_PER_MILLION,
  };
}

function baseModelRates(
  model: string,
  defaultRates: ModelCostRates,
  savedRates: SavedCostRates | null | undefined,
): ModelCostRates {
  return savedRates?.modelOverrides.get(model) ?? defaultRates;
}

function parseBracketModelCosts(
  query: Record<string, string>,
  knownModels: string[],
  defaultRates: ModelCostRates,
  savedRates: SavedCostRates | null | undefined,
): Map<string, ModelCostRates> {
  const inputByModel = new Map<string, string>();
  const outputByModel = new Map<string, string>();

  for (const [key, value] of Object.entries(query)) {
    const inputMatch = key.match(INPUT_COST_BRACKET_RE);
    if (inputMatch) {
      inputByModel.set(inputMatch[1], value);
      continue;
    }
    const outputMatch = key.match(OUTPUT_COST_BRACKET_RE);
    if (outputMatch) {
      outputByModel.set(outputMatch[1], value);
    }
  }

  const modelCosts = new Map<string, ModelCostRates>();
  for (const model of knownModels) {
    const baseRates = baseModelRates(model, defaultRates, savedRates);
    const rates: ModelCostRates = {
      inputPerMillion: parseCostPerMillion(
        inputByModel.get(model) ?? null,
        baseRates.inputPerMillion,
      ),
      outputPerMillion: parseCostPerMillion(
        outputByModel.get(model) ?? null,
        baseRates.outputPerMillion,
      ),
    };
    modelCosts.set(model, rates);
  }

  return modelCosts;
}

export function parseFiltersFromQuery(
  query: Record<string, string>,
  earliestDate: string,
  knownModels: string[],
  savedRates?: SavedCostRates | null,
): DashboardFilters {
  const today = todayIsoDate();
  const rangeRaw = query.range ?? 'all_time';
  const dateBucket: DateBucket = isPresetDateBucket(rangeRaw) ? rangeRaw : 'all_time';
  const { startDate, endDate } = resolveDateRange(dateBucket, earliestDate, today);

  const baseDefaults = baseDefaultRates(savedRates);
  const defaultRates: ModelCostRates = {
    inputPerMillion: parseCostPerMillion(query.input_cost ?? null, baseDefaults.inputPerMillion),
    outputPerMillion: parseCostPerMillion(
      query.output_cost ?? null,
      baseDefaults.outputPerMillion,
    ),
  };

  const modelCosts = parseBracketModelCosts(query, knownModels, defaultRates, savedRates);

  const sortKeyRaw = query.sort ?? 'totalTokens';
  const sortKey: SortKey = isSortKey(sortKeyRaw) ? sortKeyRaw : 'totalTokens';
  const sortDirRaw = query.dir ?? 'desc';
  const sortDir: SortDir = isSortDir(sortDirRaw) ? sortDirRaw : 'desc';

  return {
    dateBucket,
    startDate,
    endDate,
    defaultRates,
    modelCosts,
    sortKey,
    sortDir,
  };
}

export function buildDashboardUrl(
  filters: DashboardFilters,
  overrides: DashboardUrlOverrides = {},
): string {
  const dateBucket = overrides.dateBucket ?? filters.dateBucket;
  const sortKey = overrides.sortKey ?? filters.sortKey ?? 'totalTokens';
  const sortDir = overrides.sortDir ?? filters.sortDir ?? 'desc';

  const params = new URLSearchParams();

  if (dateBucket !== 'all_time') {
    params.set('range', dateBucket);
  }

  if (sortKey !== 'totalTokens') {
    params.set('sort', sortKey);
  }

  if (sortDir !== 'desc') {
    params.set('dir', sortDir);
  }

  const qs = params.toString();
  return qs ? `${DASHBOARD_PATH}?${qs}` : DASHBOARD_PATH;
}

export function sortDirToMultiplier(dir: SortDir): -1 | 1 {
  return dir === 'asc' ? 1 : -1;
}
