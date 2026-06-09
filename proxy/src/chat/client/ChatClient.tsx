/** @jsxImportSource hono/jsx/dom */
import { useEffect, useState } from 'hono/jsx';
import { Spinner } from '../../ui/client/Spinner';
import { fetchAvailableModels, streamChatCompletion } from '../lib/api';
import type { ChatMessage } from '../types';

export function ChatClient() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [model, setModel] = useState('');
  const [models, setModels] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadingModels, setLoadingModels] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    (async () => {
      const availableModels = await fetchAvailableModels();
      if (cancelled) {
        return;
      }

      setModels(availableModels);
      if (availableModels.length > 0) {
        setModel((current) => current || availableModels[0]);
      }
      setLoadingModels(false);
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  async function sendMessage() {
    const content = input.trim();
    if (!content || loading) {
      return;
    }

    if (!model.trim()) {
      setError('Choose a model before sending a message.');
      return;
    }

    const nextMessages: ChatMessage[] = [...messages, { role: 'user', content }];
    setMessages(nextMessages);
    setInput('');
    setLoading(true);
    setError(null);

    const assistantIndex = nextMessages.length;
    setMessages([...nextMessages, { role: 'assistant', content: '' }]);

    try {
      await streamChatCompletion(nextMessages, model.trim(), (assistantContent) => {
        setMessages((current) => {
          const updated = [...current];
          updated[assistantIndex] = { role: 'assistant', content: assistantContent };
          return updated;
        });
      });
    } catch (sendError) {
      setMessages(nextMessages);
      setError(sendError instanceof Error ? sendError.message : String(sendError));
    } finally {
      setLoading(false);
    }
  }

  function clearChat() {
    setMessages([]);
    setError(null);
    setInput('');
  }

  function onComposerKeyDown(event: KeyboardEvent) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      void sendMessage();
    }
  }

  return (
    <div class="chat-shell">
      <div class="chat-toolbar">
        <label class="field">
          <span class="field-label">Model</span>
          {models.length > 0 ? (
            <select
              class="field-select"
              value={model}
              disabled={loading || loadingModels}
              onChange={(event: Event) => {
                const target = event.currentTarget as HTMLSelectElement;
                setModel(target.value);
              }}
            >
              {models.map((entry) => (
                <option key={entry} value={entry}>
                  {entry}
                </option>
              ))}
            </select>
          ) : (
            <input
              class="field-input"
              type="text"
              value={model}
              placeholder="model-name"
              disabled={loading}
              onInput={(event: Event) => {
                const target = event.currentTarget as HTMLInputElement;
                setModel(target.value);
              }}
            />
          )}
        </label>
        <button type="button" class="btn" disabled={loading} onClick={clearChat}>
          Clear chat
        </button>
      </div>

      {loadingModels ? <p class="status-line">Loading models from /v1/models...</p> : null}
      {error ? <p class="error-banner">{error}</p> : null}

      <div class="messages" aria-live="polite">
        {messages.length === 0 ? (
          <p class="messages-empty">Send a message to test the proxy chat API.</p>
        ) : (
          messages.map((message, index) => (
            <div
              key={`${message.role}-${index}`}
              class={`message ${message.role === 'user' ? 'message-user' : 'message-assistant'}`}
            >
              <span class="message-role">{message.role}</span>
              {message.content || (loading && index === messages.length - 1 ? '...' : '')}
            </div>
          ))
        )}
      </div>

      <div class="composer">
        <textarea
          class="chat-textarea"
          value={input}
          placeholder="Type a message. Press Enter to send, Shift+Enter for a new line."
          disabled={loading}
          onInput={(event: Event) => {
            const target = event.currentTarget as HTMLTextAreaElement;
            setInput(target.value);
          }}
          onKeyDown={onComposerKeyDown}
        />
        <div class="composer-actions">
          <button
            type="button"
            class="btn btn-primary btn-with-spinner"
            disabled={loading || input.trim().length === 0}
            aria-busy={loading}
            onClick={() => void sendMessage()}
          >
            {loading ? <Spinner size="sm" /> : null}
            {loading ? 'Sending…' : 'Send'}
          </button>
        </div>
      </div>
    </div>
  );
}
