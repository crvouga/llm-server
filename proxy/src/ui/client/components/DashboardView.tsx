import { useDashboardQuery, useInvestmentQuery } from '../hooks/queries';
import { PAGE_CONTENT_CLASS, PAGE_PADDING_CLASS } from '../lib/layout';
import { Alert, Card, Spinner } from '@heroui/react';
import { Charts } from './Charts';
import { FilterForm } from './FilterForm';
import { InvestmentSection } from './InvestmentSection';
import { SortableTable } from './SortableTable';
import { SummaryCards } from './SummaryCards';

interface DashboardViewProps {
  search: string;
}

export function DashboardView({ search }: DashboardViewProps) {
  const {
    data,
    error: queryError,
    isPending,
    isFetching,
  } = useDashboardQuery(search);
  const {
    data: investmentState,
    error: investmentQueryError,
  } = useInvestmentQuery();

  const error = queryError instanceof Error ? queryError.message : data?.error ?? null;
  const investmentError =
    investmentQueryError instanceof Error ? investmentQueryError.message : null;

  const flashMessage =
    new URL(window.location.href).searchParams.get('saved') === '1'
      ? 'Cost rates saved and shared across clients.'
      : null;
  const hasData = data?.summary !== null && (data?.summary?.rows.length ?? 0) > 0;
  const isInitialLoad = isPending && data === undefined;

  return (
    <div className={`dashboard-shell ${PAGE_CONTENT_CLASS} ${PAGE_PADDING_CLASS} flex-1 overflow-y-auto py-6`}>
      {isInitialLoad ? (
        <div className="flex min-h-64 items-center justify-center py-12" aria-busy="true">
          <Spinner size="lg" />
        </div>
      ) : null}

      {error ? (
        <Alert status="danger" className="mb-4">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Description>{error}</Alert.Description>
          </Alert.Content>
        </Alert>
      ) : null}

      {flashMessage ? (
        <Alert status="success" className="mb-4">
          <Alert.Indicator />
          <Alert.Content>
            <Alert.Description>{flashMessage}</Alert.Description>
          </Alert.Content>
        </Alert>
      ) : null}

      {!isInitialLoad && data?.summary ? (
        <>
          <SummaryCards summary={data.summary} filters={data.filters} />
          {investmentError ? (
            <Alert status="danger" className="mb-4">
              <Alert.Indicator />
              <Alert.Content>
                <Alert.Description>{investmentError}</Alert.Description>
              </Alert.Content>
            </Alert>
          ) : (
            <InvestmentSection investmentState={investmentState ?? null} />
          )}
          {hasData && data.payload ? (
            <>
              <Charts data={data.payload as unknown as Parameters<typeof Charts>[0]['data']} />
              <Card className="mb-6 min-w-0 max-w-full">
                <Card.Header>
                  <Card.Title>Per-model breakdown</Card.Title>
                  <Card.Description>
                    Click column headers to sort. Default order: total tokens descending.
                  </Card.Description>
                </Card.Header>
                <Card.Content>
                  <SortableTable
                    rows={data.payload.rows}
                    totals={data.payload.totals}
                    initialSortKey={data.payload.sortKey}
                    initialSortDir={data.payload.sortDir}
                  />
                </Card.Content>
              </Card>
            </>
          ) : (
            <p className="text-sm text-muted">No chat completion usage found for this date range.</p>
          )}
        </>
      ) : null}

      {!isInitialLoad && data ? (
        <FilterForm filters={data.filters} models={data.models} savedCostRates={data.savedCostRates} />
      ) : null}

      {isFetching && !isInitialLoad ? (
        <p className="sr-only" aria-live="polite">
          Refreshing dashboard
        </p>
      ) : null}
    </div>
  );
}
