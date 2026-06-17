import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from 'react';
import {
  Alert,
  Button,
  Input,
  ListBox,
  Select,
  Spinner,
  TextArea,
} from '@heroui/react';
import { useChatCompletionMutation, useModelsQuery } from '../hooks/queries';
import { computeTokensPerSecond, formatDurationMs, formatInt, formatTps } from '../lib/format';
import { MarkdownContent } from './MarkdownContent';

interface MessageMetricsProps {
  message: {
    model?: string;
    promptTokens?: number | null;
    completionTokens?: number | null;
    durationMs?: number | null;
  };
}

export function MessageMetrics({ message }: MessageMetricsProps) {
  const { model, promptTokens, completionTokens, durationMs } = message;
  if (
    promptTokens === null ||
    promptTokens === undefined ||
    completionTokens === null ||
    completionTokens === undefined ||
    durationMs === null ||
    durationMs === undefined
  ) {
    return null;
  }

  const totalTokens = promptTokens + completionTokens;
  const tokensPerSecond = computeTokensPerSecond(totalTokens, durationMs);

  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-slate-200/70 pt-3 text-xs text-slate-500 dark:border-slate-700/70 dark:text-slate-400">
      {model ? (
        <>
          <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[0.8rem] text-slate-600 dark:bg-slate-800 dark:text-slate-300">
            {model}
          </code>
          <span aria-hidden="true">·</span>
        </>
      ) : null}
      <span className="tabular-nums">{formatInt(promptTokens)} prompt</span>
      <span aria-hidden="true">·</span>
      <span className="tabular-nums">{formatInt(completionTokens)} completion</span>
      <span aria-hidden="true">·</span>
      <span className="tabular-nums">{formatDurationMs(durationMs)}</span>
      <span aria-hidden="true">·</span>
      <span className="tabular-nums font-medium text-slate-600 dark:text-slate-300">
        {formatTps(tokensPerSecond)} tok/s
      </span>
    </div>
  );
}

function resizeTextarea(textarea: HTMLTextAreaElement) {
  textarea.style.height = 'auto';
  textarea.style.height = `${Math.min(textarea.scrollHeight, 160)}px`;
}

interface ChatMessage {
  role: string;
  content: string;
  model?: string;
  promptTokens?: number | null;
  completionTokens?: number | null;
  durationMs?: number | null;
}

interface ChatViewProps {
  onRegisterClear?: (clear: () => void) => void;
}

export function ChatView({ onRegisterClear }: ChatViewProps) {
  const messagesRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const STORAGE_KEY_MESSAGES = 'llm-chat-messages';
  const STORAGE_KEY_MODEL = 'llm-chat-model';

  const [messages, setMessages] = useState<ChatMessage[]>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY_MESSAGES);
      return saved ? JSON.parse(saved) : [];
    } catch {
      return [];
    }
  });
  const [input, setInput] = useState('');
  const [model, setModel] = useState(() => {
    try {
      return localStorage.getItem(STORAGE_KEY_MODEL) || '';
    } catch {
      return '';
    }
  });
  const [error, setError] = useState<string | null>(null);

  const { data: models = [], isLoading: loadingModels } = useModelsQuery();
  const chatMutation = useChatCompletionMutation();
  const loading = chatMutation.isPending;

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY_MESSAGES, JSON.stringify(messages));
  }, [messages]);

  useEffect(() => {
    if (model) localStorage.setItem(STORAGE_KEY_MODEL, model);
  }, [model]);

  useEffect(() => {
    if (models.length > 0 && !model) {
      setModel(models[0]);
    }
  }, [models, model]);

  useEffect(() => {
    const container = messagesRef.current;
    if (container) container.scrollTop = container.scrollHeight;
  }, [messages, loading]);

  useEffect(() => {
    if (textareaRef.current) resizeTextarea(textareaRef.current);
  }, [input]);

  function sendMessage() {
    const content = input.trim();
    if (!content || loading) return;
    if (!model.trim()) {
      setError('Choose a model before sending a message.');
      return;
    }
    if (abortControllerRef.current) abortControllerRef.current.abort();
    abortControllerRef.current = new AbortController();

    const nextMessages = [...messages, { role: 'user', content }];
    setMessages(nextMessages);
    setInput('');
    setError(null);

    const assistantIndex = nextMessages.length;
    const modelUsed = model.trim();
    setMessages([...nextMessages, { role: 'assistant', content: '' }]);

    chatMutation.mutate(
      {
        messages: nextMessages,
        model: modelUsed,
        signal: abortControllerRef.current.signal,
        onChunk: (assistantContent) => {
          setMessages((current) => {
            const updated = [...current];
            updated[assistantIndex] = {
              ...updated[assistantIndex],
              role: 'assistant',
              content: assistantContent,
            };
            return updated;
          });
        },
      },
      {
        onSuccess: (result) => {
          setMessages((current) => {
            const updated = [...current];
            updated[assistantIndex] = {
              ...updated[assistantIndex],
              role: 'assistant',
              content: result.content,
              model: modelUsed,
              promptTokens: result.promptTokens,
              completionTokens: result.completionTokens,
              durationMs: result.durationMs,
            };
            return updated;
          });
        },
        onError: (sendError) => {
          if (sendError.name === 'AbortError') {
            setError('Chat request was cancelled');
          } else {
            setMessages(nextMessages);
            setError(sendError instanceof Error ? sendError.message : String(sendError));
          }
        },
      },
    );
  }

  const clearChat = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    chatMutation.reset();
    setMessages([]);
    localStorage.removeItem(STORAGE_KEY_MESSAGES);
    setError(null);
    setInput('');
  }, [chatMutation]);

  useEffect(() => {
    onRegisterClear?.(clearChat);
  }, [onRegisterClear, clearChat]);

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <div ref={messagesRef} className="flex-1 overflow-y-auto pb-40" aria-live="polite">
        {messages.length === 0 ? (
          <p className="flex min-h-full items-center justify-center p-8 text-center text-slate-500">
            How can I help you today?
          </p>
        ) : (
          messages.map((message, index) => {
            const isAssistant = message.role === 'assistant';
            const isStreaming =
              loading && isAssistant && index === messages.length - 1 && !message.content;
            return (
              <div
                key={`${message.role}-${index}`}
                className={`border-b border-slate-200/60 ${isAssistant ? 'bg-transparent' : 'bg-slate-100 dark:bg-slate-900'}`}
              >
                <div className="mx-auto max-w-3xl px-4 py-5 md:px-6">
                  {isAssistant ? (
                    isStreaming ? (
                      <p className="italic text-slate-500">Thinking…</p>
                    ) : (
                      <>
                        <MarkdownContent content={message.content} />
                        <MessageMetrics message={message} />
                      </>
                    )
                  ) : (
                    <div className="whitespace-pre-wrap wrap-break-word text-[0.95rem] leading-6">
                      {message.content}
                    </div>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>

      <div className="fixed bottom-0 left-0 right-0 z-50 bg-linear-to-t from-slate-50 via-slate-50/95 to-transparent px-4 pb-4 pt-3 dark:from-slate-950 dark:via-slate-950/95">
        <div className="mx-auto flex max-w-3xl flex-col gap-2">
          {error ? (
            <Alert status="danger">
              <Alert.Indicator />
              <Alert.Content>
                <Alert.Description>{error}</Alert.Description>
              </Alert.Content>
            </Alert>
          ) : null}
          <div className="flex items-end gap-2 rounded-2xl border border-slate-200 bg-white p-2 shadow-lg dark:border-slate-700 dark:bg-slate-900">
            <TextArea
              ref={textareaRef}
              className="min-h-6 max-h-40 flex-1 resize-none border-0 bg-transparent px-2 py-1 text-base touch-manipulation"
              value={input}
              rows={1}
              placeholder="Message the model…"
              disabled={loading}
              onChange={(event) => {
                setInput(event.currentTarget.value);
                resizeTextarea(event.currentTarget);
              }}
              onKeyDown={(event: KeyboardEvent<HTMLTextAreaElement>) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault();
                  sendMessage();
                }
              }}
            />
            {loading ? (
              <Button
                isIconOnly
                variant="secondary"
                aria-label="Stop generating"
                onPress={() => abortControllerRef.current?.abort()}
              >
                <span className="block h-3 w-3 rounded-sm bg-slate-700 dark:bg-slate-200" />
              </Button>
            ) : (
              <Button
                isIconOnly
                variant="primary"
                aria-label="Send message"
                isDisabled={input.trim().length === 0}
                onPress={() => sendMessage()}
              >
                ↑
              </Button>
            )}
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2 px-1">
            <label className="flex min-w-0 flex-1 items-center gap-2 text-sm">
              <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Model</span>
              {models.length > 0 ? (
                <Select
                  className="min-w-0 flex-1"
                  selectedKey={model || null}
                  isDisabled={loading || loadingModels}
                  onSelectionChange={(key) => {
                    if (key != null) setModel(String(key));
                  }}
                >
                  <Select.Trigger>
                    <Select.Value />
                    <Select.Indicator />
                  </Select.Trigger>
                  <Select.Popover>
                    <ListBox>
                      {models.map((entry) => (
                        <ListBox.Item key={entry} id={entry} textValue={entry}>
                          {entry}
                        </ListBox.Item>
                      ))}
                    </ListBox>
                  </Select.Popover>
                </Select>
              ) : (
                <Input
                  className="min-w-0 flex-1"
                  type="text"
                  value={model}
                  placeholder="model-name"
                  disabled={loading}
                  onChange={(event) => setModel(event.currentTarget.value)}
                />
              )}
            </label>
            {loadingModels ? (
              <span className="inline-flex items-center gap-2 text-xs text-slate-500">
                <Spinner size="sm" />
                Loading models…
              </span>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
