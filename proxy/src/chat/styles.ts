export const chatStyles = `
  * { box-sizing: border-box; }

  :root {
    color-scheme: light dark;
    --bg: #f8fafc;
    --surface: #ffffff;
    --border: #e2e8f0;
    --text: #0f172a;
    --muted: #64748b;
    --accent: #3b82f6;
    --accent-soft: #dbeafe;
    --user-bg: #dbeafe;
    --assistant-bg: #f1f5f9;
    --error: #ef4444;
    font-family: ui-sans-serif, system-ui, -apple-system, sans-serif;
    line-height: 1.5;
  }

  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #0b1120;
      --surface: #111827;
      --border: #1f2937;
      --text: #f1f5f9;
      --muted: #94a3b8;
      --accent: #60a5fa;
      --accent-soft: #1e3a5f;
      --user-bg: #1e3a5f;
      --assistant-bg: #1f2937;
    }
  }

  html, body {
    margin: 0;
    height: 100%;
    background: var(--bg);
    color: var(--text);
  }

  body {
    display: flex;
    flex-direction: column;
    min-height: 100vh;
  }

  .chat-shell {
    flex: 1;
    display: flex;
    flex-direction: column;
    padding-top: 1rem;
    padding-bottom: 1.25rem;
    min-height: 0;
  }

  .chat-toolbar {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: 0.75rem 1rem;
    margin-bottom: 1rem;
  }

  .field {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    flex: 1 1 12rem;
  }

  .field-label {
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--muted);
  }

  .field-input,
  .field-select {
    font: inherit;
    padding: 0.55rem 0.8rem;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface);
    color: var(--text);
    min-width: 0;
  }

  .field-input:focus,
  .field-select:focus,
  .chat-textarea:focus {
    outline: none;
    border-color: var(--accent);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 25%, transparent);
  }

  .btn {
    cursor: pointer;
    font: inherit;
    font-weight: 600;
    padding: 0.55rem 1rem;
    border-radius: 8px;
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--text);
  }

  .btn:hover:not(:disabled) {
    border-color: var(--accent);
    color: var(--accent);
  }

  .btn:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }

  .btn-primary {
    border: none;
    background: var(--accent);
    color: #fff;
  }

  .btn-primary:hover:not(:disabled) {
    opacity: 0.9;
    color: #fff;
  }

  .messages {
    flex: 1;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    padding: 1rem;
    border: 1px solid var(--border);
    border-radius: 12px;
    background: var(--surface);
    min-height: 280px;
    margin-bottom: 1rem;
  }

  .messages-empty {
    margin: auto;
    color: var(--muted);
    text-align: center;
    font-size: 0.9rem;
  }

  .message {
    max-width: 85%;
    padding: 0.75rem 1rem;
    border-radius: 12px;
    white-space: pre-wrap;
    word-break: break-word;
  }

  .message-user {
    align-self: flex-end;
    background: var(--user-bg);
    border-bottom-right-radius: 4px;
  }

  .message-assistant {
    align-self: flex-start;
    background: var(--assistant-bg);
    border-bottom-left-radius: 4px;
  }

  .message-role {
    display: block;
    font-size: 0.7rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--muted);
    margin-bottom: 0.35rem;
  }

  .composer {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .chat-textarea {
    font: inherit;
    width: 100%;
    min-height: 5rem;
    resize: vertical;
    padding: 0.75rem 0.9rem;
    border: 1px solid var(--border);
    border-radius: 10px;
    background: var(--surface);
    color: var(--text);
  }

  .composer-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.75rem;
    justify-content: flex-end;
  }

  .error-banner {
    margin-bottom: 1rem;
    padding: 0.75rem 1rem;
    border-radius: 8px;
    background: rgba(239, 68, 68, 0.1);
    color: var(--error);
    font-weight: 600;
    font-size: 0.875rem;
  }

  .status-line {
    margin: 0 0 0.75rem;
    font-size: 0.8rem;
    color: var(--muted);
  }

  @media (max-width: 640px) {
    .chat-shell {
      padding-top: 0.75rem;
      padding-bottom: 0.75rem;
    }

    .message {
      max-width: 100%;
    }

    .composer-actions .btn {
      flex: 1 1 auto;
    }
  }
`;
