import { useEffect, useState } from 'react';
import { Alert, Button, Card, Chip, Input, Spinner } from '@heroui/react';
import {
  useBackendConfigQuery,
  useCheckBackendHealthMutation,
  useSaveBackendConfigMutation,
} from '../hooks/queries';
import type { BackendHealthResult } from '../lib/types';

function formatCheckedAt(value: string | null): string {
  if (!value) return 'Not checked yet';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Not checked yet';
  return date.toLocaleString();
}

function CheckRow({ label, passed }: { label: string; passed: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3 text-sm">
      <span>{label}</span>
      <Chip size="sm" color={passed ? 'success' : 'danger'} variant="soft">
        {passed ? 'Pass' : 'Fail'}
      </Chip>
    </div>
  );
}

export function BackendHealthCard() {
  const { data: config, error: configError, isPending: configLoading } = useBackendConfigQuery();
  const saveBackend = useSaveBackendConfigMutation();
  const checkBackend = useCheckBackendHealthMutation();

  const [urlInput, setUrlInput] = useState('');
  const [status, setStatus] = useState('');
  const [statusError, setStatusError] = useState(false);
  const [healthResult, setHealthResult] = useState<BackendHealthResult | null>(null);

  useEffect(() => {
    setUrlInput(config?.backendUrl ?? '');
  }, [config]);

  const trimmedInput = urlInput.trim();
  const inputChanged = trimmedInput !== (config?.backendUrl ?? '');
  const canSave = inputChanged && trimmedInput.length > 0 && !saveBackend.isPending;

  function onSave() {
    setStatus('');
    setStatusError(false);
    saveBackend.mutate(
      { backendUrl: trimmedInput },
      {
        onSuccess: () => {
          setStatus('Backend URL saved.');
          checkBackend.mutate(undefined, {
            onSuccess: (result) => {
              setHealthResult(result);
            },
          });
        },
        onError: (error) => {
          setStatus(error instanceof Error ? error.message : 'Failed to save backend URL.');
          setStatusError(true);
        },
      },
    );
  }

  function onCheck() {
    setStatus('');
    setStatusError(false);
    checkBackend.mutate(undefined, {
      onSuccess: (result) => {
        setHealthResult(result);
      },
      onError: (error) => {
        setHealthResult(null);
        setStatus(error instanceof Error ? error.message : 'Health check failed.');
        setStatusError(true);
      },
    });
  }

  const checking = checkBackend.isPending;
  const saving = saveBackend.isPending;

  return (
    <Card className="mb-6 min-w-0 w-full max-w-full border-violet-200 bg-linear-to-br from-violet-50 to-background dark:border-violet-900 dark:from-violet-950">
      <Card.Header>
        <Card.Title>Backend</Card.Title>
        <Card.Description>
          Configure the upstream OpenAI-compatible API and verify it responds to{' '}
          <code className="rounded bg-default px-1 py-0.5 font-mono text-xs">/v1/models</code>.
        </Card.Description>
      </Card.Header>
      <Card.Content>
        {configLoading ? (
          <div className="flex min-h-24 items-center justify-center">
            <Spinner size="lg" />
          </div>
        ) : null}

        {configError ? (
          <Alert status="danger" className="mb-4">
            <Alert.Indicator />
            <Alert.Content>
              <Alert.Description>
                {configError instanceof Error ? configError.message : 'Failed to load backend config'}
              </Alert.Description>
            </Alert.Content>
          </Alert>
        ) : null}

        {!configLoading && config ? (
          <>
            <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
              <Chip size="sm" variant="soft">
                Source: database
              </Chip>
              {config.backendUrl ? (
                <span className="text-muted">
                  Configured URL: <code className="font-mono text-xs">{config.backendUrl}</code>
                </span>
              ) : (
                <span className="text-muted">No backend URL configured in database</span>
              )}
            </div>

            <label className="mb-4 block text-sm">
              <span className="mb-1 block font-semibold text-muted">Backend URL</span>
              <Input
                type="url"
                value={urlInput}
                placeholder="https://llm.example.com"
                onChange={(event) => setUrlInput(event.currentTarget.value)}
                fullWidth
              />
            </label>

            <div className="flex flex-wrap items-center gap-3">
              <Button variant="primary" isDisabled={!canSave} onPress={() => onSave()}>
                {saving ? <Spinner size="sm" color="current" /> : null}
                {saving ? 'Saving…' : 'Save URL'}
              </Button>
              <Button variant="secondary" isDisabled={checking || saving} onPress={() => onCheck()}>
                {checking ? <Spinner size="sm" color="current" /> : null}
                {checking ? 'Checking…' : 'Check backend'}
              </Button>
              <span className="text-sm text-muted">
                Last checked: {formatCheckedAt(healthResult?.checkedAt ?? null)}
              </span>
            </div>

            {status ? (
              <Alert status={statusError ? 'danger' : 'default'} className="mt-4">
                <Alert.Content>
                  <Alert.Description>{status}</Alert.Description>
                </Alert.Content>
              </Alert>
            ) : null}

            {healthResult ? (
              <div className="mt-5 space-y-4 rounded-xl border border-separator bg-surface p-4">
                <Alert status={healthResult.ok ? 'success' : 'danger'}>
                  <Alert.Indicator />
                  <Alert.Content>
                    <Alert.Title>
                      {healthResult.ok ? 'Backend is healthy' : 'Backend check failed'}
                    </Alert.Title>
                    {healthResult.error ? (
                      <Alert.Description>{healthResult.error}</Alert.Description>
                    ) : null}
                  </Alert.Content>
                </Alert>

                <div className="grid gap-2">
                  <CheckRow label="Reachable" passed={healthResult.checks.reachable} />
                  <CheckRow label="HTTP OK" passed={healthResult.checks.httpOk} />
                  <CheckRow
                    label="OpenAI /v1/models response"
                    passed={healthResult.checks.openAiModels}
                  />
                </div>

                <div className="grid gap-2 text-sm text-muted md:grid-cols-3">
                  <div>
                    <div className="font-semibold text-foreground">Latency</div>
                    <div>{healthResult.latencyMs} ms</div>
                  </div>
                  <div>
                    <div className="font-semibold text-foreground">Models</div>
                    <div>{healthResult.modelCount}</div>
                  </div>
                  <div>
                    <div className="font-semibold text-foreground">HTTP status</div>
                    <div>{healthResult.httpStatus ?? '—'}</div>
                  </div>
                </div>

                {healthResult.sampleModelIds.length > 0 ? (
                  <div className="text-sm text-muted">
                    Sample models:{' '}
                    {healthResult.sampleModelIds.map((id) => (
                      <code key={id} className="mr-2 rounded bg-default px-1 py-0.5 font-mono text-xs">
                        {id}
                      </code>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}
          </>
        ) : null}
      </Card.Content>
    </Card>
  );
}
