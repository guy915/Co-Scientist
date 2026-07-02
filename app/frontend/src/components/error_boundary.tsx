import '@material/web/icon/icon.js';
import type React from 'react';
import type {ReactNode} from 'react';
import {Component} from 'react';

interface ErrorBoundaryProps {
  children: ReactNode;
  fallback?: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
  errorInfo: React.ErrorInfo | null;
}

const FALLBACK_CARD_CLASSES =
  'w-full max-w-2xl rounded-xl border border-th-border bg-th-card ' +
  'text-th-card-fg';

const FALLBACK_TITLE_CLASSES =
  'flex items-center gap-2 text-lg font-semibold leading-none ' +
  'text-th-destructive';

const FALLBACK_DESCRIPTION_CLASSES = 'mt-2 text-sm text-muted-foreground';

const FALLBACK_BUTTON_CLASSES =
  'inline-flex min-h-10 cursor-pointer items-center justify-center ' +
  'rounded-full border border-transparent bg-th-primary px-5 text-sm ' +
  'font-medium text-th-primary-fg hover:opacity-90 focus-visible:outline-2 ' +
  'focus-visible:outline-offset-2 focus-visible:outline-th-ring';

const FALLBACK_OUTLINE_BUTTON_CLASSES =
  'inline-flex min-h-10 cursor-pointer items-center justify-center ' +
  'rounded-full border border-th-border bg-transparent px-5 text-sm ' +
  'font-medium text-th-fg hover:bg-th-muted focus-visible:outline-2 ' +
  'focus-visible:outline-offset-2 focus-visible:outline-th-ring';

/**
 * Catches render-time errors in its subtree and shows a fallback UI.
 *
 * @param props The children to guard and an optional custom fallback.
 */
export class ErrorBoundary extends Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = {hasError: false, error: null, errorInfo: null};
  }

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return {hasError: true, error};
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('ErrorBoundary caught an error:', error, errorInfo);
    this.setState({errorInfo});
  }

  handleReset = () => {
    this.setState({hasError: false, error: null, errorInfo: null});
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;

      return (
        <div className="flex min-h-screen items-center justify-center p-4">
          <section className={FALLBACK_CARD_CLASSES}>
            <header className="p-6">
              <h1 className={FALLBACK_TITLE_CLASSES}>
                <span aria-hidden="true">
                  <md-icon>warning</md-icon>
                </span>
                Something went wrong
              </h1>
              <p className={FALLBACK_DESCRIPTION_CLASSES}>
                An error occurred while rendering this component
              </p>
            </header>
            <div className="space-y-4 p-6 pt-0">
              <div className="rounded-lg border border-th-destructive bg-th-muted p-4">
                <p className="font-mono text-sm text-th-destructive">
                  {this.state.error?.toString()}
                </p>
              </div>
              {this.state.errorInfo && (
                <details className="text-sm">
                  <summary className="mb-2 cursor-pointer font-medium">
                    Component Stack
                  </summary>
                  <pre className="overflow-auto rounded bg-th-muted p-4 text-xs">
                    {this.state.errorInfo.componentStack}
                  </pre>
                </details>
              )}
              <div className="flex gap-2">
                <button
                  type="button"
                  className={FALLBACK_BUTTON_CLASSES}
                  onClick={this.handleReset}
                >
                  Try Again
                </button>
                <button
                  type="button"
                  className={FALLBACK_OUTLINE_BUTTON_CLASSES}
                  onClick={() => window.location.reload()}
                >
                  Reload Page
                </button>
              </div>
            </div>
          </section>
        </div>
      );
    }
    return this.props.children;
  }
}
