import '@material/web/icon/icon.js';
import '@material/web/button/outlined-button.js';
import type {ReactNode} from 'react';
import {Link, useLocation, useNavigate} from 'react-router-dom';
import {LogConsole} from './components/LogConsole';
import {ThemeToggle} from './components/ThemeToggle';

/**
 * Renders the app shell with header navigation, main content, and footer.
 *
 * @param props The page content to render inside the layout.
 */
export function Layout({children}: {children: ReactNode}) {
  const navigate = useNavigate();
  const location = useLocation();
  const isPublicRoute = !location.pathname.startsWith('/runs');
  return (
    <div
      className="min-h-screen flex flex-col"
      style={{
        backgroundColor: 'var(--color-th-bg)',
        color: 'var(--color-th-fg)',
      }}
    >
      <header
        className="border-b sticky top-0 z-30 backdrop-blur-xl"
        style={{
          backgroundColor:
            'color-mix(in srgb, var(--md-sys-color-surface-container) 70%, transparent)',
          borderColor: 'var(--color-th-border)',
        }}
      >
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-3 flex items-center justify-between gap-2">
          <Link
            to="/"
            className="flex items-center gap-2 font-semibold shrink-0"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 14 13"
              className="w-5 h-5 shrink-0"
              aria-hidden="true"
              style={{color: 'var(--md-sys-color-primary)'}}
            >
              <path
                d="M1.70627 12.6C1.23127 12.6 0.825025 12.4375 0.487525 12.1125C0.162524 11.7875 2.44677e-05 11.3938 2.44677e-05 10.9313C2.44677e-05 10.7563 0.0187744 10.6 0.0562744 10.4625C0.0937746 10.325 0.150025 10.2 0.225025 10.0875L4.36877 4.10625C4.48127 3.93125 4.56877 3.75 4.63127 3.5625C4.69377 3.3625 4.72503 3.1625 4.72503 2.9625V0.900002H4.27502C4.15002 0.900002 4.04377 0.856252 3.95627 0.768753C3.86877 0.681253 3.82502 0.575002 3.82502 0.450002C3.82502 0.325002 3.86877 0.218752 3.95627 0.131253C4.04377 0.0437527 4.15002 2.6226e-06 4.27502 2.6226e-06H8.77503C8.90003 2.6226e-06 9.00627 0.0437527 9.09377 0.131253C9.18128 0.218752 9.22503 0.325002 9.22503 0.450002C9.22503 0.575002 9.18128 0.681253 9.09377 0.768753C9.00627 0.856252 8.90003 0.900002 8.77503 0.900002H8.32502V2.9625C8.32502 3.1625 8.35627 3.3625 8.41877 3.5625C8.48127 3.75 8.56878 3.93125 8.68127 4.10625L12.825 10.0875C12.9 10.2 12.9563 10.325 12.9938 10.4625C13.0313 10.5875 13.05 10.7375 13.05 10.9125C13.05 11.3875 12.8875 11.7875 12.5625 12.1125C12.2375 12.4375 11.8375 12.6 11.3625 12.6H1.70627ZM5.62502 0.900002V2.9625C5.62502 3.25 5.58127 3.53125 5.49377 3.80625C5.41877 4.08125 5.30627 4.33125 5.15627 4.55625L2.71877 8.0625C2.66877 8.1375 2.63127 8.21875 2.60627 8.30625C2.58127 8.38125 2.56877 8.4625 2.56877 8.55C2.56877 8.8125 2.67502 9.0375 2.88752 9.225C3.10002 9.4 3.36252 9.4875 3.67502 9.4875C4.02503 9.4875 4.36877 9.4125 4.70627 9.2625C5.05627 9.1 5.57502 8.7875 6.26252 8.325C6.95002 7.875 7.51877 7.55 7.96877 7.35C8.41878 7.1375 8.86253 7 9.30002 6.9375C9.35002 6.925 9.38127 6.9 9.39377 6.8625C9.41877 6.8125 9.41877 6.76875 9.39377 6.73125L7.93128 4.6125C7.75628 4.375 7.62503 4.11875 7.53753 3.84375C7.46252 3.55625 7.42502 3.2625 7.42502 2.9625V0.900002H5.62502Z"
                fill="currentColor"
                stroke="currentColor"
                strokeWidth="0.4"
              />
            </svg>
            <span className="text-base tracking-tight">Co-Scientist</span>
          </Link>
          <nav className="flex items-center gap-2 sm:gap-3 text-sm">
            {isPublicRoute && (
              <div className="hidden md:flex items-center gap-6 mr-2">
                <a className="public-nav-link" href="/#workflow-title">
                  How it works
                </a>
                <Link
                  className="public-nav-link"
                  to="/demos/ferroptosis-pancreatic-cancer"
                >
                  Demo
                </Link>
                <a className="public-nav-link" href="/#research">
                  Research
                </a>
              </div>
            )}
            <span className="inline-flex">
              <ThemeToggle />
            </span>
            <md-outlined-button
              onclick={(() => navigate('/runs')) as EventListener}
              style={
                location.pathname.startsWith('/runs')
                  ? ({
                      '--md-outlined-button-outline-width': '1px',
                      '--md-outlined-button-outline-color':
                        'var(--md-sys-color-primary)',
                      '--md-outlined-button-label-text-color':
                        'var(--md-sys-color-primary)',
                    } as React.CSSProperties)
                  : ({
                      '--md-outlined-button-outline-width': '1px',
                      '--md-outlined-button-outline-color':
                        'var(--color-th-border)',
                      '--md-outlined-button-label-text-color':
                        'var(--color-th-muted-fg)',
                    } as React.CSSProperties)
              }
            >
              {isPublicRoute ? 'Workbench' : 'Dashboard'}
            </md-outlined-button>
            {!isPublicRoute && (
              <span className="hidden sm:inline-flex">
                <LogConsole />
              </span>
            )}
          </nav>
        </div>
      </header>
      <main
        className={
          isPublicRoute
            ? 'flex-1 w-full wb-fade-in'
            : 'flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 py-4 sm:py-6 wb-fade-in'
        }
      >
        {children}
      </main>
      <footer
        className="text-sm py-4 border-t text-center"
        style={{
          borderColor: 'var(--color-th-border)',
          color: 'var(--color-th-muted-fg)',
          fontFamily: 'system-ui, -apple-system, sans-serif',
        }}
      >
        &copy; 2026{' '}
        <a
          href="https://github.com/guy915/Co-Scientist"
          target="_blank"
          rel="noopener noreferrer"
          className="underline"
          style={{color: 'inherit'}}
        >
          Co-Scientist
        </a>
      </footer>
    </div>
  );
}
