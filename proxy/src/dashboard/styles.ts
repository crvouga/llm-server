export const dashboardStyles = `

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

  * { box-sizing: border-box; }

  html {
    overflow-y: scroll;
    scrollbar-gutter: stable;
  }

  body {
    margin: 0;
    background: var(--bg);
    color: var(--text);
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
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    max-width: 1280px;
    margin: 0 auto;
    padding: 0.875rem 1.5rem;
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
    max-width: 1280px;
    margin: 0 auto;
    padding: 1.5rem 1.5rem 3rem;
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
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 1rem;
    margin-bottom: 1.5rem;
  }

  .stat-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    box-shadow: var(--shadow);
    padding: 1.25rem;
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
    align-items: center;
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

  input[type="date"],
  input[type="number"] {
    font: inherit;
    padding: 0.4rem 0.6rem;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--bg);
    color: var(--text);
    min-width: 0;
  }

  input[type="number"] {
    width: 7rem;
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

  .table-scroll {
    overflow-x: scroll;
    scrollbar-gutter: stable;
    -webkit-overflow-scrolling: touch;
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
  }

`;
