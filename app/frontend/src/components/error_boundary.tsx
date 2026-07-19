import type React from 'react';
import type {ReactNode} from 'react';
import {Component} from 'react';
import {logUiError} from '@/lib/ui_logging';
import {Icon} from './icon';

interface ErrorBoundaryProps {
  children: ReactNode;
  /**
   * Optional replacement UI; when set it renders instead of the default
   * card.
   */
  fallback?: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
  // component stack; arrives after the error itself
  errorInfo: React.ErrorInfo | null;
}

const FALLBACK_CARD_CLASSES =
  'w-full max-w-2xl rounded-xl border border-th-border bg-th-card ' +
  'text-th-card-fg';

const FALLBACK_TITLE_CLASSES =
  'flex items-center gap-2 text-lg font-semibold leading-none ' +
  'text-th-destructive';

const FALLBACK_DESCRIPTION_CLASSES = 'mt-2 text-sm text-th-muted-fg';

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

// Static header of the fallback card: title plus subtitle.
function FallbackHeader() {
  return (
    <header className="p-6">
      <h1 className={FALLBACK_TITLE_CLASSES}>
        <span aria-hidden="true">
          <Icon name="warning" />
        </span>
        Something went wrong
      </h1>
      <p className={FALLBACK_DESCRIPTION_CLASSES}>
        An error occurred while rendering this component
      </p>
    </header>
  );
}

// The caught error's message, rendered in a highlighted block.
function FallbackErrorMessage({error}: {error: Error | null}) {
  return (
    <div className="rounded-lg border border-th-destructive bg-th-muted p-4">
      <p className="font-mono text-sm text-th-destructive">
        {error?.toString()}
      </p>
    </div>
  );
}

// Collapsible component-stack details; renders nothing until
// componentDidCatch has captured `errorInfo` (see ErrorFallbackCard).
function FallbackComponentStack({
  errorInfo,
}: {
  errorInfo: React.ErrorInfo | null;
}) {
  if (!errorInfo) return null;
  return (
    <details className="text-sm">
      <summary className="mb-2 cursor-pointer font-medium">
        Component Stack
      </summary>
      <pre className="overflow-auto rounded bg-th-muted p-4 text-xs">
        {errorInfo.componentStack}
      </pre>
    </details>
  );
}

// "Try Again" (calls onReset) and "Reload Page" (hard reload) actions.
function FallbackActions({onReset}: {onReset: () => void}) {
  return (
    <div className="flex gap-2">
      <button
        type="button"
        className={FALLBACK_BUTTON_CLASSES}
        onClick={onReset}
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
  );
}

// Default fallback UI shown in place of a subtree that threw during render;
// `errorInfo` (the component stack) arrives one commit after `error` itself,
// so FallbackComponentStack renders only once componentDidCatch has
// captured it.
function ErrorFallbackCard({
  error,
  errorInfo,
  onReset,
}: {
  error: Error | null;
  errorInfo: React.ErrorInfo | null;
  onReset: () => void;
}) {
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <section className={FALLBACK_CARD_CLASSES}>
        <FallbackHeader />
        <div className="space-y-4 p-6 pt-0">
          <FallbackErrorMessage error={error} />
          <FallbackComponentStack errorInfo={errorInfo} />
          <FallbackActions onReset={onReset} />
        </div>
      </section>
    </div>
  );
}

/**
 * Catches render-time errors in its subtree and shows a fallback UI.
 *
 * A class component because error boundaries have no hook equivalent: only
 * getDerivedStateFromError / componentDidCatch can intercept descendant render
 * errors. Note the boundary contract: it catches errors thrown during render,
 * lifecycle methods, and constructors of the tree below it, but NOT errors in
 * event handlers, async code, or the boundary's own render.
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

  // Render phase: flip to the fallback UI synchronously so the broken
  // subtree is never committed. Must be pure (no side effects here).
  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return {hasError: true, error};
  }

  // Commit phase: side effects are allowed here, so log and capture the
  // component stack for the collapsible details section.
  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('ErrorBoundary caught an error:', error, errorInfo);
    // Also persist it: a render crash is exactly what someone debugging
    // later needs to see in the app-wide log, not only in this console.
    logUiError(
      `render error: ${String(error)}`,
      errorInfo.componentStack ?? undefined,
    );
    this.setState({errorInfo});
  }

  // Clears the error state and re-renders children; recovery only sticks if
  // whatever threw was transient.
  handleReset = () => {
    this.setState({hasError: false, error: null, errorInfo: null});
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <ErrorFallbackCard
          error={this.state.error}
          errorInfo={this.state.errorInfo}
          onReset={this.handleReset}
        />
      );
    }
    return this.props.children;
  }
}
