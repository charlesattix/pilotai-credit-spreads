/**
 * Shared SQLite database module for the Node.js/Next.js side.
 * Opens the same pilotai.db file used by Python (with WAL mode for concurrent reads).
 * Scanner trades are read-only from Node; user trades can be read/written.
 *
 * IMPORTANT: better-sqlite3 is a native C++ addon. If it fails to load
 * (e.g. missing binary in standalone build), all functions return safe defaults
 * so API routes don't crash at import time.
 */

import path from 'path'
import { DB_PATH as SHARED_DB_PATH } from '@/lib/paths'

// Dynamic import of better-sqlite3 to handle missing native binary gracefully
let DatabaseConstructor: typeof import('better-sqlite3') | null = null
try {
  DatabaseConstructor = require('better-sqlite3')
} catch (err) {
  console.error('[database] better-sqlite3 failed to load (native module missing?):', err)
}

type DatabaseInstance = import('better-sqlite3').Database

const DB_PATH = SHARED_DB_PATH
const DB_PATH_ALT = path.join(process.cwd(), 'data', 'pilotai.db')

let _db: DatabaseInstance | null = null
let _dbFailed = false

function getDb(): DatabaseInstance | null {
  if (_db) return _db
  if (_dbFailed || !DatabaseConstructor) return null

  try {
    // Try both paths (standalone build vs dev)
    let dbPath = DB_PATH_ALT
    try {
      const fs = require('fs')
      if (fs.existsSync(DB_PATH)) {
        dbPath = DB_PATH
      }
    } catch {
      // Use alt path
    }

    // Ensure data directory exists
    const dir = path.dirname(dbPath)
    try {
      const fs = require('fs')
      fs.mkdirSync(dir, { recursive: true })
    } catch {
      // ignore
    }

    _db = new DatabaseConstructor(dbPath)
    _db.pragma('journal_mode = WAL')
    _db.pragma('foreign_keys = ON')

    // Ensure tables exist
    _db.exec(`
      CREATE TABLE IF NOT EXISTS trades (
        id TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        ticker TEXT NOT NULL,
        strategy_type TEXT,
        status TEXT DEFAULT 'open',
        short_strike REAL,
        long_strike REAL,
        expiration TEXT,
        credit REAL,
        contracts INTEGER DEFAULT 1,
        entry_date TEXT,
        exit_date TEXT,
        exit_reason TEXT,
        pnl REAL,
        metadata JSON,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
      );

      CREATE TABLE IF NOT EXISTS alerts (
        id TEXT PRIMARY KEY,
        ticker TEXT NOT NULL,
        data JSON NOT NULL,
        created_at TEXT DEFAULT (datetime('now'))
      );

      CREATE TABLE IF NOT EXISTS regime_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        regime TEXT,
        confidence REAL,
        features JSON,
        created_at TEXT DEFAULT (datetime('now'))
      );

      CREATE TABLE IF NOT EXISTS rate_limits (
        key TEXT NOT NULL,
        ts INTEGER NOT NULL
      );
      CREATE INDEX IF NOT EXISTS idx_rate_limits_key_ts ON rate_limits(key, ts);

      CREATE TABLE IF NOT EXISTS process_locks (
        name TEXT PRIMARY KEY,
        locked_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL
      );
    `)

    return _db
  } catch (err) {
    console.error('[database] Failed to open SQLite database:', err)
    _dbFailed = true
    return null
  }
}

export interface TradeRow {
  id: string
  source: string
  ticker: string
  strategy_type: string | null
  status: string
  short_strike: number | null
  long_strike: number | null
  expiration: string | null
  credit: number | null
  contracts: number
  entry_date: string | null
  exit_date: string | null
  exit_reason: string | null
  pnl: number | null
  metadata: string | null
  created_at: string
  updated_at: string
}

export interface TradeFilters {
  status?: string
  source?: string
}

export function getTrades(filters: TradeFilters = {}): TradeRow[] {
  const db = getDb()
  if (!db) return []

  let query = 'SELECT * FROM trades WHERE 1=1'
  const params: (string | number)[] = []

  if (filters.status) {
    query += ' AND status = ?'
    params.push(filters.status)
  }
  if (filters.source) {
    query += ' AND source = ?'
    params.push(filters.source)
  }
  query += ' ORDER BY created_at DESC'

  return db.prepare(query).all(...params) as TradeRow[]
}

export function getUserTrades(userId: string): TradeRow[] {
  const db = getDb()
  if (!db) return []
  return db.prepare(
    "SELECT * FROM trades WHERE source = 'user' AND metadata LIKE ? ORDER BY created_at DESC"
  ).all(`%"user_id":"${userId}"%`) as TradeRow[]
}

export function upsertUserTrade(trade: {
  id: string
  ticker: string
  strategy_type: string
  status: string
  short_strike: number
  long_strike: number
  expiration: string
  credit: number
  contracts: number
  entry_date: string
  exit_date?: string | null
  exit_reason?: string | null
  pnl?: number | null
  metadata?: Record<string, unknown>
}): void {
  const db = getDb()
  if (!db) return
  const meta = JSON.stringify(trade.metadata || {})
  db.prepare(`
    INSERT INTO trades (id, source, ticker, strategy_type, status,
      short_strike, long_strike, expiration, credit, contracts,
      entry_date, exit_date, exit_reason, pnl, metadata, updated_at)
    VALUES (?, 'user', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
    ON CONFLICT(id) DO UPDATE SET
      status=excluded.status,
      exit_date=excluded.exit_date,
      exit_reason=excluded.exit_reason,
      pnl=excluded.pnl,
      metadata=excluded.metadata,
      updated_at=datetime('now')
  `).run(
    trade.id, trade.ticker, trade.strategy_type, trade.status,
    trade.short_strike, trade.long_strike, trade.expiration,
    trade.credit, trade.contracts, trade.entry_date,
    trade.exit_date ?? null, trade.exit_reason ?? null, trade.pnl ?? null, meta,
  )
}

export function closeUserTrade(tradeId: string, pnl: number, reason: string): TradeRow | null {
  const db = getDb()
  if (!db) return null
  const status = pnl > 0 ? 'closed_profit' : pnl < 0 ? 'closed_loss' : reason === 'manual' ? 'closed_manual' : 'closed_expiry'
  db.prepare(`
    UPDATE trades SET status=?, exit_date=datetime('now'), exit_reason=?, pnl=?, updated_at=datetime('now')
    WHERE id=? AND source='user'
  `).run(status, reason, pnl, tradeId)

  return db.prepare('SELECT * FROM trades WHERE id=?').get(tradeId) as TradeRow | null
}

export function getAlerts(limit: number = 50): Record<string, unknown>[] {
  const db = getDb()
  if (!db) return []
  const rows = db.prepare(
    'SELECT * FROM alerts ORDER BY created_at DESC LIMIT ?'
  ).all(limit) as { id: string; data: string; created_at: string }[]

  return rows.map(r => {
    try {
      return { ...JSON.parse(r.data), id: r.id, created_at: r.created_at }
    } catch {
      return { id: r.id, created_at: r.created_at }
    }
  })
}

export function getRegimeSnapshot(): { regime: string; confidence: number; features: Record<string, unknown> } | null {
  const db = getDb()
  if (!db) return null
  const row = db.prepare(
    'SELECT * FROM regime_snapshots ORDER BY created_at DESC LIMIT 1'
  ).get() as { regime: string; confidence: number; features: string } | undefined

  if (!row) return null
  return {
    regime: row.regime,
    confidence: row.confidence,
    features: JSON.parse(row.features || '{}'),
  }
}

/**
 * SQLite-based rate limiting. Returns true if the request is allowed.
 * Cleans up expired entries on each call.
 */
export function checkRateLimit(key: string, limit: number, windowMs: number): boolean {
  const db = getDb()
  if (!db) return true // Allow requests if DB unavailable
  const now = Date.now()
  const cutoff = now - windowMs

  // Clean expired entries for this key
  db.prepare('DELETE FROM rate_limits WHERE key = ? AND ts < ?').run(key, cutoff)

  // Count recent entries
  const row = db.prepare('SELECT COUNT(*) as cnt FROM rate_limits WHERE key = ? AND ts >= ?').get(key, cutoff) as { cnt: number }

  if (row.cnt >= limit) return false

  // Record this request
  db.prepare('INSERT INTO rate_limits (key, ts) VALUES (?, ?)').run(key, now)
  return true
}

/**
 * SQLite-based process lock. Returns true if lock was acquired.
 * Automatically expires stale locks after timeoutMs.
 */
export function acquireProcessLock(name: string, timeoutMs: number): boolean {
  const db = getDb()
  if (!db) return true // Allow if DB unavailable
  const now = Date.now()

  // Clean expired locks
  db.prepare('DELETE FROM process_locks WHERE expires_at < ?').run(now)

  // Try to insert (fails if lock already held)
  try {
    db.prepare(
      'INSERT INTO process_locks (name, locked_at, expires_at) VALUES (?, ?, ?)'
    ).run(name, now, now + timeoutMs)
    return true
  } catch {
    return false
  }
}

/**
 * Release a process lock.
 */
export function releaseProcessLock(name: string): void {
  const db = getDb()
  if (!db) return
  db.prepare('DELETE FROM process_locks WHERE name = ?').run(name)
}
