'use client'

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  return (
    <html lang="en">
      <head>
        <meta charSet="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>Application Error</title>
        <style>{`
          :root {
            --error-bg: #0f0f0f;
            --error-surface: #1a1a1a;
            --error-text: #f0f0f0;
            --error-reject: #ef5350;
            --error-reject-dim: #ffaaaa;
            --error-subtle: #888888;
            --error-accent: #4ade80;
            --error-accent-bg: #1a3a2a;
            --error-accent-border: #2d6a4f;
            --radius-md: 6px;
            --radius-lg: 10px;
          }
          *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
          body {
            font-family: system-ui, -apple-system, 'Segoe UI', sans-serif;
            background: var(--error-bg);
            color: var(--error-text);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
          }
        `}</style>
      </head>
      <body>
        <div style={{
          maxWidth: '640px',
          width: '100%',
          margin: '2rem',
          padding: '1.75rem',
          background: 'var(--error-surface)',
          border: '1px solid var(--error-reject)',
          borderRadius: 'var(--radius-lg)',
          display: 'flex',
          flexDirection: 'column',
          gap: '0.75rem',
        }}>
          <h2 style={{
            fontSize: '18px',
            fontWeight: 600,
            color: 'var(--error-reject)',
          }}>
            Application Error
          </h2>
          <pre style={{
            fontSize: '13px',
            fontFamily: 'ui-monospace, SFMono-Regular, "Cascadia Code", Consolas, monospace',
            whiteSpace: 'pre-wrap',
            color: 'var(--error-reject-dim)',
            lineHeight: 1.5,
          }}>
            {error.message}
            {process.env.NODE_ENV === 'development' && error.stack ? '\n\n' + error.stack : ''}
          </pre>
          {error.digest && (
            <p style={{ fontSize: '12px', color: 'var(--error-subtle)' }}>
              Error ID: {error.digest}
            </p>
          )}
          <div style={{
            display: 'flex',
            gap: '0.75rem',
            marginTop: '0.5rem',
          }}>
            <button
              onClick={reset}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                height: '34px',
                padding: '0 1rem',
                borderRadius: 'var(--radius-md)',
                background: 'transparent',
                color: 'var(--error-text)',
                border: '1px solid #555',
                fontFamily: 'inherit',
                fontSize: '13px',
                cursor: 'pointer',
              }}
            >
              Retry
            </button>
            <a
              href="/"
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                height: '34px',
                padding: '0 1rem',
                borderRadius: 'var(--radius-md)',
                background: 'var(--error-accent-bg)',
                color: 'var(--error-accent)',
                border: '1px solid var(--error-accent-border)',
                fontFamily: 'inherit',
                fontSize: '13px',
                textDecoration: 'none',
              }}
            >
              Back to Dashboard
            </a>
          </div>
        </div>
      </body>
    </html>
  )
}
