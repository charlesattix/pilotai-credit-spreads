type LogLevel = 'info' | 'error' | 'warn'

function log(level: LogLevel, msg: string, meta?: Record<string, unknown>) {
  const entry = {
    level,
    msg,
    ts: new Date().toISOString(),
    ...meta,
  }
  const output = JSON.stringify(entry)
  if (level === 'error') {
    console.error(output)
  } else if (level === 'warn') {
    console.warn(output)
  } else {
    console.log(output)
  }
}

export const logger = {
  info: (msg: string, meta?: Record<string, unknown>) => log('info', msg, meta),
  error: (msg: string, meta?: Record<string, unknown>) => log('error', msg, meta),
  warn: (msg: string, meta?: Record<string, unknown>) => log('warn', msg, meta),
}
