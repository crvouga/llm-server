import { useEffect, useState } from 'react';
import { Alert, Button, Card, Chip, Input, Spinner } from '@heroui/react';
import {
  useBackendConfigQuery,
  useCheckBackendHealthMutation,
  useSaveBackendConfigMutation,
} from '../hooks/queries';
import type { BackendHeaderEntry, BackendHealthResult } from '../lib/types';

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

interface HeaderRow extends BackendHeaderEntry {
  id: string;
}

const HEADER_PRESETS: Array<{ label: string; name: string }> = [
  { label: 'Authorization', name: 'Authorization' },
  { label: 'x-api-key', name: 'x-api-key' },
  { label: 'api-key', name: 'api-key' },
];

function createHeaderRow(name = '', value = ''): HeaderRow {
  return {
    id: crypto.randomUUID(),
    name,
    value,
  };
}

function entriesFromHeaders(headers: Record<string, string> | undefined): HeaderRow[] {
  const entries = Object.entries(headers ?? {});
  if (entries.length === 0) {
    return [];
  }
  return entries.map(([name, value]) => createHeaderRow(name, value));
}

function serializeHeaders(rows: HeaderRow[]): BackendHeaderEntry[] {
  return rows
    .map((row) => ({ name: row.name.trim(), value: row.value }))
    .filter((row) => row.name.length > 0);
}

function normalizeHeaderSnapshot(headers: Record<string, string> | BackendHeaderEntry[]): string {
  const entries = Array.isArray(headers)
    ? headers
        .map((entry) => ({ name: entry.name.trim(), value: entry.value }))
        .filter((entry) => entry.name.length > 0)
    : Object.entries(headers).map(([name, value]) => ({ name, value }));

  return entries
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((entry) => `${entry.name}\0${entry.value}`)
    .join('\n');
}

function headersEqual(
  left: BackendHeaderEntry[],
  right: Record<string, string> | undefined,
): boolean {
  return normalizeHeaderSnapshot(left) === normalizeHeaderSnapshot(right ?? {});
}

export function BackendHealthCard() {
  const { data: config, error: configError, isPending: configLoading } = useBackendConfigQuery();
  const saveBackend = useSaveBackendConfigMutation();
  const checkBackend = useCheckBackendHealthMutation();

  const [urlInput, setUrlInput] = useState('');
  const [headerRows, setHeaderRows] = useState<HeaderRow[]>([]);
  const [status, setStatus] = useState('');
  const [statusError, setStatusError] = useState(false);
  const [healthResult, setHealthResult] = useState<BackendHealthResult | null>(null);

  useEffect(() => {
    setUrlInput(config?.backendUrl ?? '');
    setHeaderRows(entriesFromHeaders(config?.backendHeaders));
  }, [config]);

  const trimmedInput = urlInput.trim();
  const serializedHeaders = serializeHeaders(headerRows);
  const inputChanged =
    trimmedInput !== (config?.backendUrl ?? '') ||
    !headersEqual(serializedHeaders, config?.backendHeaders);
  const canSave = inputChanged && trimmedInput.length > 0 && !saveBackend.isPending;

  function onSave() {
    setStatus('');
    setStatusError(false);
    saveBackend.mutate(
      { backendUrl: trimmedInput, backendHeaders: serializedHeaders },
      {
        onSuccess: () => {
          setStatus('Backend configuration saved.');
          checkBackend.mutate(undefined, {
            onSuccess: (result) => {
              setHealthResult(result);
            },
          });
        },
        onError: (error) => {
          setStatus(error instanceof Error ? error.message : 'Failed to save backend config.');
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

  function updateHeaderRow(id: string, patch: Partial<BackendHeaderEntry>) {
    setHeaderRows((rows) => rows.map((row) => (row.id === id ? { ...row, ...patch } : row)));
  }

  function removeHeaderRow(id: string) {
    setHeaderRows((rows) => rows.filter((row) => row.id !== id));
  }

  function addHeaderRow(name = '') {
    setHeaderRows((rows) => [...rows, createHeaderRow(name)]);
  }

  const checking = checkBackend.isPending;
  const saving = saveBackend.isPending;
  const configuredHeaderCount = Object.keys(config?.backendHeaders ?? {}).length;

  return (
    <Card className="mb-6 min-w-0 w-full max-w-full border-violet-200 bg-linear-to-br from-violet-50 to-background dark:border-violet-900 dark:from-violet-950">
      <Card.Header>
        <Card.Title>Backend</Card.Title>
        <Card.Description>
          Configure any upstream OpenAI-compatible API URL and optional auth headers, then verify it
          responds to{' '}
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
              {configuredHeaderCount > 0 ? (
                <span className="text-muted">
                  {configuredHeaderCount} upstream header{configuredHeaderCount === 1 ? '' : 's'}
                </span>
              ) : null}
            </div>

            <label className="mb-4 block text-sm">
              <span className="mb-1 block font-semibold text-muted">Backend URL</span>
              <Input
                type="url"
                value={urlInput}
                placeholder="https://api.openai.com/v1 or https://llm.example.com"
                onChange={(event) => setUrlInput(event.currentTarget.value)}
                fullWidth
              />
            </label>

            <div className="mb-4">
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <span className="text-sm font-semibold text-muted">Upstream headers</span>
                <div className="flex flex-wrap gap-2">
                  {HEADER_PRESETS.map((preset) => (
                    <Button
                      key={preset.name}
                      size="sm"
                      variant="secondary"
                      onPress={() => addHeaderRow(preset.name)}
                    >
                      + {preset.label}
                    </Button>
                  ))}
                  <Button size="sm" variant="secondary" onPress={() => addHeaderRow()}>
                    + Header
                  </Button>
                </div>
              </div>

              {headerRows.length === 0 ? (
                <p className="text-sm text-muted">
                  Add headers for API keys or bearer tokens (for example{' '}
                  <code className="rounded bg-default px-1 py-0.5 font-mono text-xs">
                    Authorization
                  </code>{' '}
                  or{' '}
                  <code className="rounded bg-default px-1 py-0.5 font-mono text-xs">x-api-key</code>
                  ).
                </p>
              ) : (
                <div className="space-y-3">
                  {headerRows.map((row) => (
                    <div key={row.id} className="grid gap-2 md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)_auto]">
                      <Input
                        aria-label="Header name"
                        placeholder="Header name"
                        value={row.name}
                        onChange={(event) =>
                          updateHeaderRow(row.id, { name: event.currentTarget.value })
                        }
                        fullWidth
                      />
                      <Input
                        aria-label="Header value"
                        type="password"
                        placeholder="Header value"
                        value={row.value}
                        onChange={(event) =>
                          updateHeaderRow(row.id, { value: event.currentTarget.value })
                        }
                        fullWidth
                      />
                      <Button variant="secondary" onPress={() => removeHeaderRow(row.id)}>
                        Remove
                      </Button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <Button variant="primary" isDisabled={!canSave} onPress={() => onSave()}>
                {saving ? <Spinner size="sm" color="current" /> : null}
                {saving ? 'Saving…' : 'Save config'}
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
