export const sharedStyles = `
  :root {
    --content-max-width: 1280px;
    --content-padding-x: 1.5rem;
  }

  .top-bar-inner,
  .page,
  .chat-shell {
    width: 100%;
    max-width: var(--content-max-width);
    box-sizing: border-box;
  }

  .top-bar-inner {
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: center;
    gap: 1rem;
    margin-left: auto;
    margin-right: auto;
    padding-left: var(--content-padding-x);
    padding-right: var(--content-padding-x);
  }

  .chat-shell {
    margin-left: auto;
    margin-right: auto;
    padding-left: var(--content-padding-x);
    padding-right: var(--content-padding-x);
  }

  .tab-bar {
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 0.35rem;
    flex-wrap: wrap;
  }

  .tab-link {
    display: inline-flex;
    align-items: center;
    text-decoration: none;
    color: var(--muted);
    font-size: 0.875rem;
    font-weight: 600;
    padding: 0.45rem 0.9rem;
    border-radius: 999px;
    border: 1px solid transparent;
    transition: border-color 0.15s, background 0.15s, color 0.15s;
  }

  .tab-link:hover {
    color: var(--accent);
    border-color: color-mix(in srgb, var(--accent) 35%, var(--border));
    background: color-mix(in srgb, var(--accent-soft) 50%, transparent);
  }

  .tab-link.active {
    color: var(--accent);
    border-color: var(--accent);
    background: var(--accent-soft);
  }

  .top-bar-spacer {
    width: 6.5rem;
  }

  .spinner {
    display: inline-block;
    border: 2px solid currentColor;
    border-right-color: transparent;
    border-radius: 50%;
    animation: ui-spin 0.65s linear infinite;
    flex-shrink: 0;
  }

  .spinner-sm {
    width: 0.9rem;
    height: 0.9rem;
  }

  .spinner-md {
    width: 1.25rem;
    height: 1.25rem;
  }

  .spinner-lg {
    width: 2.25rem;
    height: 2.25rem;
    border-width: 3px;
  }

  @keyframes ui-spin {
    to {
      transform: rotate(360deg);
    }
  }

  .btn-with-spinner {
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
  }

  .btn-refresh:disabled,
  .btn-primary:disabled {
    cursor: not-allowed;
    opacity: 0.7;
  }

  .loading-panel {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 16rem;
    padding: 3rem 1rem;
  }

  @media (max-width: 768px) {
    .top-bar-inner {
      grid-template-columns: 1fr;
      justify-items: stretch;
      text-align: center;
    }

    .top-bar-title {
      justify-self: center;
    }

    .tab-bar {
      justify-content: center;
    }

    .btn-refresh,
    .top-bar-spacer {
      justify-self: center;
    }
  }
`;
