import { useEffect, useMemo, useState } from 'react';
import { Alert, Button, Card, Input, Spinner } from '@heroui/react';
import { formatIsoDateLabel, formatUsd } from '../lib/format';
import { computeBreakEvenPreview } from '../lib/investment';
import { useSaveInvestmentMutation } from '../hooks/queries';
import type { InvestmentData } from '../lib/types';

interface InvestmentSectionProps {
  investmentState: InvestmentData | null;
}

export function InvestmentSection({ investmentState }: InvestmentSectionProps) {
  const [investmentInput, setInvestmentInput] = useState('');
  const [projectedDailyInput, setProjectedDailyInput] = useState('');
  const [status, setStatus] = useState('');
  const [statusError, setStatusError] = useState(false);
  const saveInvestment = useSaveInvestmentMutation();

  useEffect(() => {
    const config = investmentState?.config;
    if (!config) return;
    setInvestmentInput(config.investmentUsd == null ? '' : String(config.investmentUsd));
    setProjectedDailyInput(
      config.projectedDailySpendUsd == null ? '' : String(config.projectedDailySpendUsd),
    );
  }, [investmentState]);

  const preview = useMemo(
    () =>
      computeBreakEvenPreview(investmentInput, projectedDailyInput, investmentState?.metrics ?? null),
    [investmentInput, projectedDailyInput, investmentState],
  );

  function applySavedResult(result: InvestmentData) {
    const config = result?.config;
    if (!config) return;
    setInvestmentInput(config.investmentUsd == null ? '' : String(config.investmentUsd));
    setProjectedDailyInput(
      config.projectedDailySpendUsd == null ? '' : String(config.projectedDailySpendUsd),
    );
  }

  function onSave() {
    setStatus('');
    setStatusError(false);
    saveInvestment.mutate(
      {
        investmentUsd: investmentInput === '' ? null : Number(investmentInput),
        projectedDailySpendUsd: projectedDailyInput === '' ? null : Number(projectedDailyInput),
      },
      {
        onSuccess: (result) => {
          applySavedResult(result);
          setStatus('Investment settings saved.');
        },
        onError: () => {
          setStatus('Failed to save investment settings. Check database connectivity.');
          setStatusError(true);
        },
      },
    );
  }

  function onCalculateFromHistory() {
    setStatus('');
    setStatusError(false);
    saveInvestment.mutate(
      {
        investmentUsd: investmentInput === '' ? null : Number(investmentInput),
        calculateFromHistory: true,
      },
      {
        onSuccess: (result) => {
          applySavedResult(result);
          const avg = result.metrics?.historicalAverageDailySpendUsd;
          setStatus(
            avg == null
              ? 'No usage history yet to calculate a daily average.'
              : `Projected daily spend set to ${formatUsd(avg)} from historical usage.`,
          );
          setStatusError(avg == null);
        },
        onError: () => {
          setStatus('Failed to calculate projected daily spend from history.');
          setStatusError(true);
        },
      },
    );
  }

  const metrics = investmentState?.metrics;
  const breakEvenLabel = preview?.hasBrokenEven
    ? preview.actualBreakEvenDate
      ? formatIsoDateLabel(preview.actualBreakEvenDate)
      : 'Already reached'
    : preview?.projectedBreakEvenDate
      ? formatIsoDateLabel(preview.projectedBreakEvenDate)
      : '—';

  const saving = saveInvestment.isPending;
  const calculating =
    saveInvestment.isPending && saveInvestment.variables?.calculateFromHistory === true;
  const savingOnly = saveInvestment.isPending && !calculating;

  return (
    <Card className="mb-6 min-w-0 w-full max-w-full border-emerald-200 bg-linear-to-br from-emerald-50 to-background dark:border-emerald-900 dark:from-emerald-950">
      <Card.Header>
        <Card.Title>Investment &amp; break-even</Card.Title>
        <Card.Description>
          Track upfront hardware or setup cost against estimated cloud savings. All amounts are USD.
        </Card.Description>
      </Card.Header>
      <Card.Content>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <Card variant="secondary" className="border-emerald-100 dark:border-emerald-900">
            <Card.Content className="p-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-emerald-700 dark:text-emerald-400">
                Total savings to date
              </div>
              <div className="mt-1 text-2xl font-bold tabular-nums text-emerald-700 dark:text-emerald-400">
                {metrics ? formatUsd(metrics.totalSavingsToDateUsd ?? 0) : '—'}
              </div>
              <div className="mt-1 text-sm text-muted">Estimated cloud cost avoided so far</div>
            </Card.Content>
          </Card>
          <Card variant="secondary">
            <Card.Content className="p-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-muted">
                Remaining to break even
              </div>
              <div className="mt-1 text-2xl font-bold tabular-nums">
                {preview ? formatUsd(preview.remainingInvestmentUsd) : '—'}
              </div>
            </Card.Content>
          </Card>
          <Card variant="secondary" className="md:col-span-2">
            <Card.Content className="p-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-muted">
                {preview?.hasBrokenEven ? 'Break-even reached' : 'Projected break-even date'}
              </div>
              <div className="mt-1 text-2xl font-bold tabular-nums">{breakEvenLabel}</div>
              <div className="mt-1 text-sm text-muted">
                {preview?.hasBrokenEven
                  ? 'Cumulative estimated cloud savings have covered the investment.'
                  : preview?.effectiveDailySpendUsd
                    ? `Based on ${formatUsd(preview.effectiveDailySpendUsd)} estimated savings per day`
                    : 'Set investment and projected daily spend to estimate break-even'}
              </div>
            </Card.Content>
          </Card>
        </div>

        <div className="mt-5 grid gap-4 md:grid-cols-2">
          <label className="block text-sm">
            <span className="mb-1 block font-semibold text-muted">Investment (USD)</span>
            <div className="flex items-center gap-1">
              <span className="text-sm font-semibold text-muted">$</span>
              <Input
                type="number"
                value={investmentInput}
                min={0}
                step={0.01}
                placeholder="0.00"
                onChange={(event) => setInvestmentInput(event.currentTarget.value)}
                fullWidth
              />
            </div>
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-semibold text-muted">Projected daily spend (USD)</span>
            <Input
              type="number"
              value={projectedDailyInput}
              min={0}
              step={0.0001}
              placeholder={
                metrics?.historicalAverageDailySpendUsd == null
                  ? 'No history yet'
                  : `Historical avg ${formatUsd(metrics.historicalAverageDailySpendUsd)}`
              }
              onChange={(event) => setProjectedDailyInput(event.currentTarget.value)}
              fullWidth
            />
            <p className="mt-1 text-xs text-muted">
              Leave blank to use the historical average (
              {metrics?.historicalAverageDailySpendUsd == null
                ? '—'
                : formatUsd(metrics.historicalAverageDailySpendUsd)}
              ) across {metrics?.calendarDays ?? '—'} days.
            </p>
          </label>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button variant="primary" isDisabled={saving} onPress={() => onSave()}>
            {savingOnly ? <Spinner size="sm" color="current" /> : null}
            {savingOnly ? 'Saving…' : 'Save investment'}
          </Button>
          <Button variant="secondary" isDisabled={saving} onPress={() => onCalculateFromHistory()}>
            {calculating ? <Spinner size="sm" color="current" /> : null}
            {calculating ? 'Calculating…' : 'Calculate from history'}
          </Button>
          {status ? (
            <Alert status={statusError ? 'danger' : 'default'} className="w-full">
              <Alert.Content>
                <Alert.Description>{status}</Alert.Description>
              </Alert.Content>
            </Alert>
          ) : null}
        </div>
      </Card.Content>
    </Card>
  );
}
