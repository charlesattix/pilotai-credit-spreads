import path from 'path'

/**
 * Root directory of the Python backend project.
 * Uses PROJECT_ROOT env var if set, otherwise falls back to process.cwd()/..
 * In Docker: /app (web runs from /app/web, Python from /app)
 * In dev: parent of the web/ directory
 */
export const PROJECT_ROOT = process.env.PROJECT_ROOT || path.join(process.cwd(), '..')

/** Path to config.yaml */
export const CONFIG_PATH = path.join(PROJECT_ROOT, 'config.yaml')

/**
 * Path to data/ directory.
 * Override via PILOTAI_DATA_DIR env var for persistent volumes
 * (e.g. Railway volume mount at /app/data).
 */
export const DATA_DIR = process.env.PILOTAI_DATA_DIR || path.join(PROJECT_ROOT, 'data')

/** Path to output/ directory */
export const OUTPUT_DIR = process.env.PILOTAI_OUTPUT_DIR || path.join(PROJECT_ROOT, 'output')

/** Path to SQLite database */
export const DB_PATH = path.join(DATA_DIR, 'pilotai.db')
