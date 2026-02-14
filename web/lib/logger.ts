const isDev = process.env.NODE_ENV === 'development'

export const logger = {
  info: (msg: string, data?: Record<string, unknown>) => {
    if (isDev) console.log(`[INFO] ${msg}`, data || '')
  },
  warn: (msg: string, data?: Record<string, unknown>) => {
    console.warn(`[WARN] ${msg}`, data || '')
  },
  error: (msg: string, data?: Record<string, unknown>) => {
    console.error(`[ERROR] ${msg}`, data || '')
  },
  debug: (msg: string, data?: Record<string, unknown>) => {
    if (isDev) console.debug(`[DEBUG] ${msg}`, data || '')
  },
}
