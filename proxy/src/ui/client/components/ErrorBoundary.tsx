import { Component, type ErrorInfo, type ReactNode } from 'react';
import { PAGE_CONTENT_NARROW_CLASS, PAGE_PADDING_CLASS } from '../lib/layout';

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: unknown;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: unknown) {
    return { hasError: true, error };
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    console.error('ErrorBoundary caught:', error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className={`${PAGE_CONTENT_NARROW_CLASS} ${PAGE_PADDING_CLASS} py-8`}>
          <div className="rounded-xl border border-red-200 bg-red-50 p-6 dark:border-red-900 dark:bg-red-950">
            <h2 className="text-lg font-semibold text-red-600 dark:text-red-400">Something went wrong</h2>
            {this.state.error != null && (
              <p className="mt-2 text-slate-700 dark:text-slate-300">{String(this.state.error)}</p>
            )}
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
