/** @jsxImportSource hono/jsx/dom */
import { useEffect } from 'hono/jsx';
import { Chart } from 'chart.js/auto';
import type { DashboardPayload } from '../types';

function themeColors() {
  const textColor =
    getComputedStyle(document.documentElement).getPropertyValue('--muted').trim() || '#64748b';
  const gridColor = 'rgba(128,128,128,0.15)';
  return { textColor, gridColor };
}

function baseOptions(textColor: string, gridColor: string) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { labels: { color: textColor, font: { size: 11 } } },
    },
    scales: {
      x: { ticks: { color: textColor, font: { size: 10 } }, grid: { color: gridColor } },
      y: { ticks: { color: textColor, font: { size: 10 } }, grid: { color: gridColor } },
    },
  };
}

export function Charts({ data }: { data: DashboardPayload }) {
  useEffect(() => {
    if (data.labels.length === 0 && data.dailyLabels.length === 0) return;

    const { textColor, gridColor } = themeColors();
    const charts: Chart[] = [];
    const baseOpts = baseOptions(textColor, gridColor);

    if (data.labels.length > 0) {
      const tokensEl = document.getElementById('chart-tokens-per-model');
      if (tokensEl) {
        charts.push(
          new Chart(tokensEl as HTMLCanvasElement, {
            type: 'bar',
            data: {
              labels: data.labels,
              datasets: [
                {
                  label: 'Total tokens',
                  data: data.totalTokens,
                  backgroundColor: data.colors,
                  borderRadius: 4,
                },
              ],
            },
            options: {
              ...baseOpts,
              indexAxis: 'y',
              plugins: { legend: { display: false } },
            },
          }),
        );
      }

      const stackedEl = document.getElementById('chart-stacked-tokens');
      if (stackedEl) {
        charts.push(
          new Chart(stackedEl as HTMLCanvasElement, {
            type: 'bar',
            data: {
              labels: data.labels,
              datasets: [
                {
                  label: 'Prompt',
                  data: data.promptTokens,
                  backgroundColor: '#3b82f6',
                  borderRadius: 2,
                },
                {
                  label: 'Completion',
                  data: data.completionTokens,
                  backgroundColor: '#8b5cf6',
                  borderRadius: 2,
                },
              ],
            },
            options: {
              ...baseOpts,
              scales: { x: { stacked: true }, y: { stacked: true } },
            },
          }),
        );
      }

      const shareEl = document.getElementById('chart-share');
      if (shareEl) {
        charts.push(
          new Chart(shareEl as HTMLCanvasElement, {
            type: 'doughnut',
            data: {
              labels: data.labels,
              datasets: [
                {
                  data: data.totalTokens,
                  backgroundColor: data.colors,
                  borderWidth: 0,
                },
              ],
            },
            options: {
              responsive: true,
              maintainAspectRatio: false,
              plugins: {
                legend: {
                  position: 'right',
                  labels: { color: textColor, font: { size: 11 }, boxWidth: 12 },
                },
              },
            },
          }),
        );
      }

      const costEl = document.getElementById('chart-cost');
      if (costEl) {
        charts.push(
          new Chart(costEl as HTMLCanvasElement, {
            type: 'bar',
            data: {
              labels: data.labels,
              datasets: [
                {
                  label: 'Est. cost (USD)',
                  data: data.estCostUsd,
                  backgroundColor: '#10b981',
                  borderRadius: 4,
                },
              ],
            },
            options: {
              ...baseOpts,
              plugins: { legend: { display: false } },
              scales: {
                y: {
                  ticks: {
                    color: textColor,
                    callback: (v) => '$' + Number(v).toFixed(4),
                  },
                  grid: { color: gridColor },
                },
              },
            },
          }),
        );
      }
    }

    if (data.dailyLabels.length > 0) {
      const dailyEl = document.getElementById('chart-daily');
      if (dailyEl) {
        charts.push(
          new Chart(dailyEl as HTMLCanvasElement, {
            type: 'line',
            data: {
              labels: data.dailyLabels,
              datasets: [
                {
                  label: 'Prompt',
                  data: data.dailyPrompt,
                  borderColor: '#3b82f6',
                  backgroundColor: 'rgba(59,130,246,0.1)',
                  fill: true,
                  tension: 0.3,
                  pointRadius: 2,
                },
                {
                  label: 'Completion',
                  data: data.dailyCompletion,
                  borderColor: '#8b5cf6',
                  backgroundColor: 'rgba(139,92,246,0.1)',
                  fill: true,
                  tension: 0.3,
                  pointRadius: 2,
                },
                {
                  label: 'Total',
                  data: data.dailyTotal,
                  borderColor: '#10b981',
                  backgroundColor: 'transparent',
                  borderDash: [4, 4],
                  tension: 0.3,
                  pointRadius: 0,
                },
              ],
            },
            options: baseOpts,
          }),
        );
      }
    }

    return () => {
      for (const chart of charts) chart.destroy();
    };
  }, []);

  if (data.labels.length === 0 && data.dailyLabels.length === 0) return null;

  return (
    <div class="charts-grid">
      {data.labels.length > 0 ? (
        <>
          <div class="chart-card">
            <h3>Total tokens per model</h3>
            <div class="chart-wrap tall">
              <canvas id="chart-tokens-per-model" />
            </div>
          </div>
          <div class="chart-card">
            <h3>Token share by model</h3>
            <div class="chart-wrap tall">
              <canvas id="chart-share" />
            </div>
          </div>
          <div class="chart-card wide">
            <h3>Prompt vs completion tokens per model</h3>
            <div class="chart-wrap">
              <canvas id="chart-stacked-tokens" />
            </div>
          </div>
          <div class="chart-card wide">
            <h3>Estimated cloud cost per model</h3>
            <div class="chart-wrap">
              <canvas id="chart-cost" />
            </div>
          </div>
        </>
      ) : null}
      {data.dailyLabels.length > 0 ? (
        <div class="chart-card wide">
          <h3>Daily token usage over time</h3>
          <div class="chart-wrap">
            <canvas id="chart-daily" />
          </div>
        </div>
      ) : null}
    </div>
  );
}
