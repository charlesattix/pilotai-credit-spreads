const ALPACA_BASE = process.env.ALPACA_PAPER === 'false'
  ? 'https://api.alpaca.markets'
  : 'https://paper-api.alpaca.markets'

function alpacaHeaders() {
  return {
    'APCA-API-KEY-ID': process.env.ALPACA_API_KEY ?? '',
    'APCA-API-SECRET-KEY': process.env.ALPACA_API_SECRET ?? '',
  }
}

export interface AlpacaAccount {
  equity: number
  buying_power: number
  cash: number
}

export interface AlpacaPosition {
  symbol: string
  qty: string
  side: 'long' | 'short'
  avg_entry_price: string
  current_price: string
  unrealized_pl: string
  unrealized_plpc: string
}

export interface AlpacaOrderLeg {
  symbol: string
  side: string        // 'buy' | 'sell'
  qty: string | null
  status: string
}

export interface AlpacaOrder {
  id: string
  client_order_id: string
  status: string      // 'filled' | 'cancelled' | 'rejected' | ...
  order_class: string // 'mleg' | 'simple' | ...
  qty: string | null
  filled_qty: string | null
  filled_avg_price: string | null
  limit_price: string | null
  submitted_at: string
  filled_at: string | null
  legs: AlpacaOrderLeg[]
}

// ---------------------------------------------------------------------------
// Parsed OCC option symbol
// ---------------------------------------------------------------------------

export interface ParsedOCC {
  ticker: string
  expiration: string  // YYYY-MM-DD
  optionType: 'P' | 'C'
  strike: number
}

/**
 * Parse an Alpaca/Polygon OCC option symbol into its components.
 * Handles both "O:SPY250321P00450000" and "SPY250321P00450000"
 * and padded variants like "SPY   250321P00450000".
 */
export function parseOCC(raw: string): ParsedOCC | null {
  // Strip "O:" prefix if present, then collapse internal whitespace
  const clean = raw.startsWith('O:') ? raw.slice(2).replace(/\s+/g, '') : raw.replace(/\s+/g, '')
  const match = clean.match(/^([A-Z]{1,6})(\d{6})([PC])(\d{8})$/)
  if (!match) return null
  const [, ticker, dateStr, optionType, strikeStr] = match
  const expiration = `20${dateStr.slice(0, 2)}-${dateStr.slice(2, 4)}-${dateStr.slice(4, 6)}`
  return { ticker, expiration, optionType: optionType as 'P' | 'C', strike: parseInt(strikeStr) / 1000 }
}

// ---------------------------------------------------------------------------
// Fetch helpers
// ---------------------------------------------------------------------------

export async function fetchAlpacaAccount(): Promise<AlpacaAccount | null> {
  try {
    const res = await fetch(`${ALPACA_BASE}/v2/account`, { headers: alpacaHeaders() })
    if (!res.ok) return null
    const data = await res.json()
    return {
      equity: parseFloat(data.equity),
      buying_power: parseFloat(data.buying_power),
      cash: parseFloat(data.cash),
    }
  } catch {
    return null
  }
}

/** Returns null on network/auth error; empty array when no positions. */
export async function fetchAlpacaPositions(): Promise<AlpacaPosition[] | null> {
  try {
    const res = await fetch(`${ALPACA_BASE}/v2/positions`, { headers: alpacaHeaders() })
    if (!res.ok) return null
    return await res.json() as AlpacaPosition[]
  } catch {
    return null
  }
}

/**
 * Fetch order history from Alpaca.
 * Uses status=all to get both open and closed orders; includes nested leg detail.
 * Returns null on network/auth error.
 */
export async function fetchAlpacaOrders(limit = 500): Promise<AlpacaOrder[] | null> {
  try {
    const params = new URLSearchParams({
      status: 'all',
      limit: String(limit),
      nested: 'true',
      direction: 'desc',
    })
    const res = await fetch(`${ALPACA_BASE}/v2/orders?${params}`, { headers: alpacaHeaders() })
    if (!res.ok) return null
    return await res.json() as AlpacaOrder[]
  } catch {
    return null
  }
}
