import { logger } from './logger'

export function captureException(error: unknown, context?: Record<string, unknown>) {
  const message = error instanceof Error ? error.message : String(error)
  logger.error('Unhandled exception', { error: message, ...context })

  // TODO: Add Sentry.captureException(error) when @sentry/nextjs is installed
}

export function captureMessage(message: string, level: 'info' | 'warning' | 'error' = 'info') {
  logger[level === 'warning' ? 'warn' : level](message)
}
