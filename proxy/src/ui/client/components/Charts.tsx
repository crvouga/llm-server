import Chart from 'chart.js/auto';
import { useEffect, useRef } from 'react';

const chartPanelClass =
  'min-w-0 w-full max-w-full rounded-xl border border-separator bg-surface p-5 shadow-sm';

interface ChartData {
  labels: string[];
  totalTokens: number[];
  promptTokens: number[];
  completionTokens: number[];
  estCostUsd: number[];
  colors: string[];
  dailyLabels: string[];
  dailyPrompt: number[];
  dailyCompletion: number[];
  dailyTotal: number[];
}

export function Charts({ data }: { data: ChartData | null }) {
  const chartsContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!data || (data.labels.length === 0 && data.dailyLabels.length === 0)) return;

    const isDark = document.documentElement.classList.contains('dark');
    const textColor = isDark ? '#94a3b8' : '#64748b';
    const gridColor = isDark ? 'rgba(148,163,184,0.15)' : 'rgba(128,128,128,0.15)';
    const isMobile = window.innerWidth < 768;
    const charts: Chart[] = [];
    let resizeObserver: ResizeObserver | null = null;
    let resizeFrame: number | null = null;

    function scheduleChartResize() {
      if (resizeFrame) cancelAnimationFrame(resizeFrame);
      resizeFrame = requestAnimationFrame(() => {
        for (const chart of charts) chart.resize();
      });
    }

    function truncateLabel(label: unknown, maxLen = isMobile ? 14 : 32) {
      const text = String(label);
      return text.length > maxLen ? `${text.slice(0, maxLen - 1)}…` : text;
    }

      const baseOpts = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { labels: { color: textColor, font: { size: isMobile ? 10 : 11 } } } },
        scales: {
          x: {
            ticks: {
              color: textColor,
              font: { size: isMobile ? 9 : 10 },
              maxRotation: isMobile ? 45 : 0,
              autoSkip: true,
              maxTicksLimit: isMobile ? 8 : undefined,
              callback(value: string | number) {
                return truncateLabel(value);
              },
            },
            grid: { color: gridColor },
          },
          y: {
            ticks: {
              color: textColor,
              font: { size: isMobile ? 9 : 10 },
              callback(value: string | number) {
                return truncateLabel(value);
              },
            },
            grid: { color: gridColor },
          },
        },
      } as const;

    if (data.labels.length > 0) {
      const tokensEl = document.getElementById('chart-tokens-per-model') as HTMLCanvasElement | null;
      if (tokensEl) {
        charts.push(
          new Chart(tokensEl, {
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
            options: { ...baseOpts, indexAxis: 'y' as const, plugins: { legend: { display: false } } },
          }),
        );
      }

      const stackedEl = document.getElementById('chart-stacked-tokens') as HTMLCanvasElement | null;
      if (stackedEl) {
        charts.push(
          new Chart(stackedEl, {
            type: 'bar',
            data: {
              labels: data.labels,
              datasets: [
                { label: 'Prompt', data: data.promptTokens, backgroundColor: '#3b82f6', borderRadius: 2 },
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
              scales: {
                x: { ...baseOpts.scales.x, stacked: true },
                y: { ...baseOpts.scales.y, stacked: true },
              },
            },
          }),
        );
      }

      const shareEl = document.getElementById('chart-share') as HTMLCanvasElement | null;
      if (shareEl) {
        charts.push(
          new Chart(shareEl, {
            type: 'doughnut',
            data: {
              labels: data.labels,
              datasets: [{ data: data.totalTokens, backgroundColor: data.colors, borderWidth: 0 }],
            },
            options: {
              responsive: true,
              maintainAspectRatio: false,
              plugins: {
                legend: {
                  position: isMobile ? 'bottom' : 'right',
                  labels: { color: textColor, font: { size: isMobile ? 10 : 11 }, boxWidth: 12 },
                },
              },
            },
          }),
        );
      }

      const costEl = document.getElementById('chart-cost') as HTMLCanvasElement | null;
      if (costEl) {
        charts.push(
          new Chart(costEl, {
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
                x: baseOpts.scales.x,
                y: {
                  ...baseOpts.scales.y,
                  ticks: {
                    ...baseOpts.scales.y.ticks,
                    callback: (v) => '$' + Number(v).toFixed(4),
                  },
                },
              },
            },
          }),
        );
      }
    }

    if (data.dailyLabels.length > 0) {
      const dailyEl = document.getElementById('chart-daily') as HTMLCanvasElement | null;
      if (dailyEl) {
        charts.push(
          new Chart(dailyEl, {
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

    scheduleChartResize();

    const container = chartsContainerRef.current;
    if (container && typeof ResizeObserver !== 'undefined') {
      resizeObserver = new ResizeObserver(() => scheduleChartResize());
      resizeObserver.observe(container);
    } else {
      window.addEventListener('resize', scheduleChartResize);
    }

    return () => {
      if (resizeFrame) cancelAnimationFrame(resizeFrame);
      if (resizeObserver) resizeObserver.disconnect();
      else window.removeEventListener('resize', scheduleChartResize);
      for (const chart of charts) chart.destroy();
    };
  }, [data]);

  if (!data || (data.labels.length === 0 && data.dailyLabels.length === 0)) return null;

  return (
    <div
      ref={chartsContainerRef}
      className="mb-6 grid min-w-0 w-full max-w-full grid-cols-1 gap-6 md:grid-cols-2"
    >
      {data.labels.length > 0 ? (
        <>
          <div className={chartPanelClass}>
            <h3 className="mb-4 text-sm font-semibold">Total tokens per model</h3>
            <div className="chart-wrap tall">
              <canvas id="chart-tokens-per-model" />
            </div>
          </div>
          <div className={chartPanelClass}>
            <h3 className="mb-4 text-sm font-semibold">Token share by model</h3>
            <div className="chart-wrap tall">
              <canvas id="chart-share" />
            </div>
          </div>
          <div className={`${chartPanelClass} md:col-span-2`}>
            <h3 className="mb-4 text-sm font-semibold">Prompt vs completion tokens per model</h3>
            <div className="chart-wrap">
              <canvas id="chart-stacked-tokens" />
            </div>
          </div>
          <div className={`${chartPanelClass} md:col-span-2`}>
            <h3 className="mb-4 text-sm font-semibold">Estimated cloud cost per model</h3>
            <div className="chart-wrap">
              <canvas id="chart-cost" />
            </div>
          </div>
        </>
      ) : null}
      {data.dailyLabels.length > 0 ? (
        <div className={`${chartPanelClass} md:col-span-2`}>
          <h3 className="mb-4 text-sm font-semibold">Daily token usage over time</h3>
          <div className="chart-wrap">
            <canvas id="chart-daily" />
          </div>
        </div>
      ) : null}
    </div>
  );
}
