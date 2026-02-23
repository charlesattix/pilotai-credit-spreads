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
