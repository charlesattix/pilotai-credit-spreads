'use client'

export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <html>
      <body style={{ margin: 0, backgroundColor: '#030712', display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100vh', fontFamily: 'system-ui, sans-serif' }}>
        <div style={{ textAlign: 'center', maxWidth: 400, padding: 24 }}>
          <h1 style={{ color: '#fff', fontSize: 24, marginBottom: 8 }}>Critical Error</h1>
          <p style={{ color: '#9ca3af', marginBottom: 24 }}>{error.message || 'The application encountered a fatal error.'}</p>
          <button
            onClick={reset}
            style={{ padding: '12px 24px', borderRadius: 8, border: 'none', color: '#fff', fontWeight: 600, cursor: 'pointer', background: 'linear-gradient(to right, #3b82f6, #a855f7, #ec4899)' }}
          >
            Try again
          </button>
        </div>
      </body>
    </html>
  )
}
