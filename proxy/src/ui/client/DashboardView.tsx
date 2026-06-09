/** @jsxImportSource hono/jsx/dom */
import { useCallback, useEffect, useState } from 'hono/jsx';
import { DashboardClient } from '../../dashboard/client/DashboardClient';
import { TAB_DASHBOARD } from '../../shared/constants';
import { fetchDashboardData, type DashboardDataResponse } from './api';
import { applyDashboardFormToUrl, FilterForm } from './FilterForm';
import { getTabFromUrl, subscribeToRouteChanges } from './routing';
import { Spinner } from './Spinner';
import { SummaryCards } from './SummaryCards';

export function DashboardView({
  onReady,
  onLoadingChange,
}: {
  onReady?: (api: { refresh: () => void }) => void;
  onLoadingChange?: (loading: boolean) => void;
}) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<DashboardDataResponse | null>(null);

  const load = useCallback(async (search = window.location.search) => {
    setLoading(true);
    setError(null);

    try {
      const result = await fetchDashboardData(search);
      setData(result);
      if (result.error) {
        setError(result.error);
      }
    } catch (loadError) {
      setData(null);
      setError(loadError instanceof Error ? loadError.message : String(loadError));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();

    return subscribeToRouteChanges(() => {
      if (getTabFromUrl() === TAB_DASHBOARD) {
        void load();
      }
    });
  }, [load]);

  const onRefresh = useCallback(() => {
    const search = applyDashboardFormToUrl();
    void load(search);
  }, [load]);

  useEffect(() => {
    onReady?.({ refresh: onRefresh });
  }, [onReady, onRefresh]);

  useEffect(() => {
    onLoadingChange?.(loading);
  }, [loading, onLoadingChange]);

  function onApply(search: string) {
    void load(search);
  }

  const flashMessage = new URL(window.location.href).searchParams.get('saved') === '1'
    ? 'Cost rates saved and shared across clients.'
    : null;

  const hasData = data?.summary !== null && (data?.summary?.rows.length ?? 0) > 0;
  const isInitialLoad = loading && data === null;

  return (
    <div class="page">
      {isInitialLoad ? (
        <div class="loading-panel" aria-busy="true" aria-label="Loading dashboard">
          <Spinner size="lg" />
        </div>
      ) : null}
      {error ? <p class="error">{error}</p> : null}
      {flashMessage ? <p class="success">{flashMessage}</p> : null}

      {!isInitialLoad && data?.summary ? (
        <>
          <SummaryCards summary={data.summary} filters={data.filters} />
          {hasData && data.payload ? (
            <DashboardClient data={data.payload} />
          ) : (
            <p class="muted">No chat completion usage found for this date range.</p>
          )}
        </>
      ) : null}

      {!isInitialLoad && data ? (
        <FilterForm
          filters={data.filters}
          models={data.models}
          savedCostRates={data.savedCostRates}
          onApply={onApply}
        />
      ) : null}
    </div>
  );
}
