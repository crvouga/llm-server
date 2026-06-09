export const dashboardStyles = `
  * { box-sizing: border-box; }
  
  /* Prevent horizontal overflow globally */
  html, body {
    width: 100%;
    max-width: 100vw;
    overflow-x: hidden;
    position: relative;
  }

  * { box-sizing: border-box; }

  html {
    overflow-y: scroll;
    scrollbar-gutter: stable;
    -webkit-text-size-adjust: 100%;
  }

  body {
    margin: 0;
    padding: 0;
    background: var(--bg);
    color: var(--text);
  }

  /* Prevent horizontal overflow on all containers */
  .page,
  .top-bar-inner {
    width: 100%;
    box-sizing: border-box;
  }

  :root {
    color-scheme: light dark;
    --bg: #f8fafc;
    --surface: #ffffff;
    --border: #e2e8f0;
    --text: #0f172a;
    --muted: #64748b;
    --accent: #3b82f6;
    --accent-soft: #dbeafe;
    --success: #10b981;
    --shadow: 0 1px 3px rgba(15, 23, 42, 0.08), 0 1px 2px rgba(15, 23, 42, 0.04);
    --shadow-lg: 0 10px 25px rgba(15, 23, 42, 0.08);
    font-family: ui-sans-serif, system-ui, -apple-system, sans-serif;
    line-height: 1.5;
    --touch-target-min: 44px; /* Apple's recommended minimum */
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
      --success: #34d399;
      --shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
      --shadow-lg: 0 10px 25px rgba(0, 0, 0, 0.35);
    }
  }


  .top-bar {
    position: sticky;
    top: 0;
    z-index: 100;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    box-shadow: var(--shadow);
  }

  .top-bar-inner {
    margin: 0 auto;
    padding-top: 0.875rem;
    padding-bottom: 0.875rem;
  }

  .top-bar-title {
    margin: 0;
    font-size: 1.125rem;
    font-weight: 700;
    letter-spacing: -0.02em;
  }

  .btn-refresh {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    cursor: pointer;
    font: inherit;
    font-size: 0.875rem;
    font-weight: 600;
    padding: 0.45rem 0.9rem;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--bg);
    color: var(--text);
    transition: border-color 0.15s, background 0.15s, color 0.15s;
  }

  .btn-refresh:hover {
    border-color: var(--accent);
    background: var(--accent-soft);
    color: var(--accent);
  }

  .btn-refresh-icon {
    width: 1rem;
    height: 1rem;
    flex-shrink: 0;
  }

  .page {
    margin: 0 auto;
    padding-top: 1.5rem;
    padding-bottom: 3rem;
    padding-left: var(--content-padding-x, 1.5rem);
    padding-right: var(--content-padding-x, 1.5rem);
  }

  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    box-shadow: var(--shadow);
    padding: 1.25rem;
    margin-bottom: 1.5rem;
  }

  .card h2 {
    margin: 0 0 1rem;
    font-size: 1.1rem;
    font-weight: 600;
  }

  .card-subtitle {
    margin: -0.5rem 0 1rem;
    color: var(--muted);
    font-size: 0.875rem;
  }

  .summary-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 1rem;
    margin-bottom: 0.75rem;
  }

  .stat-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    box-shadow: var(--shadow);
    padding: 1.25rem;
    flex: 1 1 calc(25% - 1rem);
  }

  .stat-card-hero {
    padding: 1.5rem 1.75rem;
    border-color: color-mix(in srgb, var(--accent) 35%, var(--border));
    background: linear-gradient(
      135deg,
      color-mix(in srgb, var(--accent-soft) 80%, var(--surface)) 0%,
      var(--surface) 100%
    );
    box-shadow: var(--shadow-lg);
    flex: 1 1 100%;
  }

  @media (min-width: 768px) {
    .stat-card:not(.stat-card-hero) {
      flex: 1 1 calc(33.333% - 0.67rem);
    }
  }

  .stat-card-hero .stat-label {
    font-size: 0.8rem;
    letter-spacing: 0.08em;
    color: var(--accent);
  }

  .stat-card-hero .stat-value {
    font-size: 2.75rem;
    font-weight: 800;
    color: var(--accent);
    line-height: 1.1;
    margin-top: 0.15rem;
  }

  .stat-card-hero .stat-detail {
    margin-top: 0.5rem;
    font-size: 0.875rem;
  }

  .summary-meta {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.75rem;
    margin-bottom: 1.5rem;
  }

  .stat-label {
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--muted);
    margin-bottom: 0.35rem;
  }

  .stat-value {
    font-size: 1.5rem;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.02em;
  }

  .stat-detail {
    margin-top: 0.25rem;
    font-size: 0.8rem;
    color: var(--muted);
  }

  fieldset {
    border: 1px solid var(--border);
    border-radius: 10px;
    margin-bottom: 1rem;
    padding: 1rem 1.25rem;
  }

  legend {
    font-weight: 600;
    font-size: 0.9rem;
    padding: 0 0.25rem;
  }

  .form-row {
    display: flex;
    flex-wrap: wrap;
    gap: 1rem 2rem;
    align-items: flex-end;
  }

  .cost-input-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 1rem 1.5rem;
    margin-bottom: 0.75rem;
  }

  .input-field {
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }

  .input-field-label {
    font-size: 0.8rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--muted);
  }

  .input-shell {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.15rem 0.15rem 0.15rem 0.85rem;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--bg);
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04) inset;
    transition: border-color 0.2s ease, box-shadow 0.2s ease, background 0.2s ease;
  }

  .input-shell:hover {
    border-color: color-mix(in srgb, var(--accent) 40%, var(--border));
    background: color-mix(in srgb, var(--accent-soft) 25%, var(--bg));
  }

  .input-shell:focus-within {
    border-color: var(--accent);
    background: var(--surface);
    box-shadow:
      0 0 0 3px color-mix(in srgb, var(--accent) 25%, transparent),
      0 1px 2px rgba(15, 23, 42, 0.04) inset;
  }

  .input-prefix {
    font-size: 0.875rem;
    font-weight: 600;
    color: var(--muted);
    user-select: none;
  }

  .date-buckets {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin-bottom: 0.25rem;
  }

  .date-bucket {
    display: inline-flex;
    align-items: center;
    text-decoration: none;
    color: inherit;
    font-size: 0.875rem;
    font-weight: 500;
    padding: 0.45rem 0.9rem;
    border-radius: 999px;
    border: 1px solid var(--border);
    background: var(--bg);
    transition: border-color 0.15s, background 0.15s, color 0.15s;
    user-select: none;
  }

  .date-bucket.active {
    border-color: var(--accent);
    background: var(--accent-soft);
    color: var(--accent);
  }

  .date-bucket:hover {
    border-color: color-mix(in srgb, var(--accent) 50%, var(--border));
    color: var(--accent);
  }

  label {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.9rem;
  }

  input[type="date"] {
    font: inherit;
    padding: 0.5rem 0.8rem;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--bg);
    color: var(--text);
    min-width: 0;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04) inset;
    transition: border-color 0.2s ease, box-shadow 0.2s ease;
  }

  input[type="date"]:focus {
    outline: none;
    border-color: var(--accent);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 25%, transparent);
  }

  input[type="number"],
  .number-input {
    font: inherit;
    font-variant-numeric: tabular-nums;
    padding: 0.5rem 0.8rem;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--bg);
    color: var(--text);
    min-width: 0;
    width: 7.5rem;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04) inset;
    transition: border-color 0.2s ease, box-shadow 0.2s ease, background 0.2s ease;
  }

  input[type="number"]:hover,
  .number-input:hover {
    border-color: color-mix(in srgb, var(--accent) 40%, var(--border));
    background: color-mix(in srgb, var(--accent-soft) 25%, var(--bg));
  }

  input[type="number"]:focus,
  .number-input:focus {
    outline: none;
    border-color: var(--accent);
    background: var(--surface);
    box-shadow:
      0 0 0 3px color-mix(in srgb, var(--accent) 25%, transparent),
      0 1px 2px rgba(15, 23, 42, 0.04) inset;
  }

  .input-shell .number-input {
    flex: 1;
    width: auto;
    min-width: 5rem;
    border: none;
    border-radius: 999px;
    background: transparent;
    box-shadow: none;
    padding: 0.45rem 0.75rem 0.45rem 0;
  }

  .input-shell .number-input:hover,
  .input-shell .number-input:focus {
    border: none;
    background: transparent;
    box-shadow: none;
  }

  .input-shell:focus-within .number-input {
    background: transparent;
  }

  table .input-shell {
    width: fit-content;
    min-width: 8.5rem;
  }

  table .input-shell .number-input {
    min-width: 4.5rem;
  }

  .model-cost-overrides {
    width: 100%;
    max-width: 100%;
  }

  .btn-primary {
    cursor: pointer;
    font: inherit;
    font-weight: 600;
    padding: 0.6rem 1.25rem;
    border: none;
    border-radius: 8px;
    background: var(--accent);
    color: #fff;
    transition: opacity 0.15s;
  }

  .btn-primary:hover { opacity: 0.9; }

  .charts-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
    gap: 1.5rem;
    margin-bottom: 1.5rem;
  }

  .chart-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    box-shadow: var(--shadow);
    padding: 1.25rem;
  }

  .chart-card h3 {
    margin: 0 0 1rem;
    font-size: 0.95rem;
    font-weight: 600;
  }

  .chart-card.wide {
    grid-column: 1 / -1;
  }

  .chart-wrap {
    position: relative;
    height: 280px;
  }

  .chart-wrap.tall { height: 320px; }

  table {
    border-collapse: collapse;
    width: 100%;
    font-size: 0.875rem;
  }

  th, td {
    border-bottom: 1px solid var(--border);
    padding: 0.65rem 0.75rem;
    text-align: left;
    vertical-align: middle;
  }

  th {
    font-weight: 600;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--muted);
    white-space: nowrap;
    user-select: none;
  }

  th.sortable {
    cursor: pointer;
  }

  th.sortable:hover {
    color: var(--text);
  }

  th.sortable::after {
    content: ' ↕';
    opacity: 0.35;
    font-size: 0.7rem;
  }

  th.sort-asc::after { content: ' ↑'; opacity: 1; }
  th.sort-desc::after { content: ' ↓'; opacity: 1; }

  /* Mobile table optimizations */
  @media (max-width: 768px) {
    table {
      font-size: 0.8125rem;
    }
    
    th, td {
      padding: 0.45rem 0.5rem;
      word-break: break-word;
    }

    th.sortable::after {
      font-size: 0.6rem;
    }
    
    /* Hide less important columns on very small screens */
    @media (max-width: 480px) {
      .table-scroll table tr td:nth-child(5),
      .table-scroll table tr th:nth-child(5) {
        display: none;
      }
    }
  }

  .num {
    text-align: right;
    font-variant-numeric: tabular-nums;
  }

  .total-row td {
    border-top: 2px solid var(--border);
    font-weight: 600;
  }

  code {
    font-size: 0.8rem;
    background: var(--accent-soft);
    padding: 0.15rem 0.4rem;
    border-radius: 4px;
    word-break: break-all;
  }

  .muted { color: var(--muted); }
  .error {
    color: #ef4444;
    font-weight: 600;
    padding: 0.75rem 1rem;
    background: rgba(239, 68, 68, 0.1);
    border-radius: 8px;
    margin-bottom: 1rem;
  }

  .success {
    color: var(--success);
    font-weight: 600;
    padding: 0.75rem 1rem;
    background: rgba(16, 185, 129, 0.12);
    border-radius: 8px;
    margin-bottom: 1rem;
  }

  .form-actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.75rem 1rem;
    margin-top: 1rem;
  }

  .form-action-hint {
    margin: 0;
    flex: 1 1 16rem;
  }

  .cost-rates-status {
    margin: 0;
    width: 100%;
    font-size: 0.875rem;
  }

  .cost-rates-status.error {
    color: #ef4444;
    font-weight: 600;
  }

  .table-scroll {
    overflow-x: auto;
    overflow-y: hidden;
    scrollbar-gutter: stable both-edges;
    -webkit-overflow-scrolling: touch;
    max-width: 100%;
  }
  
  .table-scroll::-webkit-scrollbar {
    height: 10px;
  }
  
  .table-scroll::-webkit-scrollbar-track {
    background: var(--bg);
    border-radius: 5px;
  }
  
  .table-scroll::-webkit-scrollbar-thumb {
    background: var(--border);
    border-radius: 5px;
    cursor: pointer;
  }
  
  .table-scroll::-webkit-scrollbar-thumb:hover {
    background: color-mix(in srgb, var(--muted) 30%, var(--border));
  }

  .range-badge {
    display: inline-block;
    background: var(--accent-soft);
    color: var(--accent);
    font-size: 0.8rem;
    font-weight: 600;
    padding: 0.25rem 0.6rem;
    border-radius: 999px;
    margin-top: 0.5rem;
    white-space: nowrap;
  }

  /* Mobile-first responsive design */
  @media (max-width: 768px) {
    .stat-card:not(.stat-card-hero) {
      flex: 1 1 calc(50% - 0.5rem);
      max-width: 48%;
    }
    
    .top-bar-inner {
      padding: 0.75rem 1rem;
      gap: 0.75rem;
    }
    
    .top-bar-title {
      font-size: 1rem;
    }
    
    .btn-refresh {
      padding: 0.4rem 0.75rem;
      font-size: 0.8125rem;
    }

    .page {
      padding: 1rem;
    }

    .card {
      padding: 1rem;
      border-radius: 10px;
    }

    .summary-meta {
      flex-direction: column;
      align-items: flex-start;
      gap: 0.5rem;
    }
    
    .range-badge {
      font-size: 0.75rem;
      padding: 0.2rem 0.5rem;
    }

    .chart-wrap { height: 240px; }
    .chart-wrap.tall { height: 280px; }

    .stat-card-hero .stat-value {
      font-size: 2.25rem;
    }

    .stat-value {
      font-size: 1.375rem;
    }

    fieldset {
      padding: 0.75rem 1rem;
      margin-bottom: 0.75rem;
    }

    legend {
      font-size: 0.825rem;
      padding: 0 0.2rem;
    }
    
    .form-row {
      flex-direction: column;
      align-items: stretch;
    }
    
    .date-buckets {
      gap: 0.375rem;
    }

    .date-bucket {
      font-size: 0.75rem;
      padding: 0.35rem 0.6rem;
      white-space: nowrap;
      min-width: auto;
    }

    /* If date bucket labels overflow, show ellipsis */
    @media (max-width: 480px) {
      .date-bucket {
        font-size: 0.7rem;
        padding: 0.3rem 0.5rem;
        flex-shrink: 1;
      }
    }

    .cost-input-grid {
      grid-template-columns: 1fr;
    }
    
    .input-shell {
      padding: 0.15rem 0.15rem 0.15rem 0.75rem;
    }

    input[type="date"],
    input[type="number"] {
      font-size: 1rem;
      padding: 0.6rem 1rem;
    }
    
    .btn-primary {
      width: 100%;
      text-align: center;
      padding: 0.7rem 1.5rem;
    }

    .form-actions {
      flex-direction: column;
      gap: 0.75rem 0.75rem;
    }
    
    .form-action-hint {
      width: 100%;
      margin-top: 0.25rem;
      font-size: 0.8125rem;
    }
    
    .cost-rates-status {
      width: 100%;
    }

    .model-cost-overrides {
      overflow-x: visible;
    }

    .model-cost-overrides thead {
      display: none;
    }

    .model-cost-overrides tbody tr {
      display: block;
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 0.875rem 1rem;
      margin-bottom: 0.75rem;
      background: var(--bg);
    }

    .model-cost-overrides tbody tr:last-child {
      margin-bottom: 0;
    }

    .model-cost-overrides tbody td {
      display: block;
      border-bottom: none;
      padding: 0.35rem 0;
    }

    .model-cost-overrides tbody td::before {
      content: attr(data-label);
      display: block;
      font-size: 0.8rem;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--muted);
      margin-bottom: 0.35rem;
    }

    .model-cost-overrides tbody td:first-child {
      margin-bottom: 0.75rem;
      padding-bottom: 0;
    }

    .model-cost-overrides tbody td:first-child::before {
      content: none;
    }

    .model-cost-overrides tbody td code {
      word-break: break-word;
    }

    .model-cost-overrides table .input-shell {
      width: 100%;
      min-width: 0;
      max-width: 100%;
    }

    .model-cost-overrides table .input-shell .number-input {
      min-width: 0;
      width: 100%;
    }

    /* Touch target minimum sizing */
    button,
    a.date-bucket,
    input[type="date"] {
      min-height: var(--touch-target-min);
    }

    input[type="number"]:not(.model-cost-overrides .number-input) {
      min-height: var(--touch-target-min);
      min-width: var(--touch-target-min);
    }

    .model-cost-overrides .number-input {
      min-height: var(--touch-target-min);
      min-width: 0;
    }
  }

  @media (max-width: 480px) {
    .stat-card:not(.stat-card-hero) {
      flex: 1 1 100%;
      max-width: 100%;
    }

    .page {
      padding: 0.75rem 0.875rem 2rem;
    }

    .card h2 {
      font-size: 0.95rem;
      margin-bottom: 0.75rem;
    }

    .card-subtitle,
    p.muted,
    .form-action-hint {
      font-size: 0.8125rem;
    }
    
    th, td {
      padding: 0.5rem 0.6rem;
      font-size: 0.8125rem;
    }

    .table-scroll {
      -ms-overflow-style: -ms-autohiding-scrollbar;
      scrollbar-width: thin;
    }
    
    .table-scroll::-webkit-scrollbar {
      height: 8px;
    }
    
    .table-scroll::-webkit-scrollbar-track {
      background: var(--bg);
    }
    
    .table-scroll::-webkit-scrollbar-thumb {
      background: var(--border);
      border-radius: 4px;
    }

    /* Handle long model names in tables */
    code {
      word-break: break-word;
      hyphens: auto;
    }
    
    /* Ensure all numbers display properly without overflow */
    .num {
      word-break: break-all;
    }

    input[type="date"] {
      width: 100%;
      max-width: 200px;
    }

    .input-shell .number-input {
      font-size: 1rem;
    }
    
    .stat-card-hero,
    .stat-card {
      margin-bottom: 0.75rem;
    }
    
    /* Prevent any content from overflowing horizontally */
    [class*="-card"],
    [class*="grid"] {
      overflow-x: hidden;
    }
    
    canvas {
      max-width: 100%;
    }
  }

`;
