import { Alert, BacktestResult, Position } from '@/lib/types'

export type { Alert, BacktestResult, Position }

export interface AlertsResponse {
  timestamp: string
  alerts: Alert[]
  opportunities: Alert[]
  count: number
}

export interface Trade {
  id: string
  ticker: string
  type: string
  entry_date: string
  exit_date?: string
  short_strike: number
  long_strike: number
  credit: number
  debit?: number
  pnl?: number
  status: 'open' | 'closed'
  entry_price: number
  exit_price?: number
  dte_entry: number
  dte_exit?: number
}

export interface Config {
  tickers: string[]
  strategy: {
    min_dte: number
    max_dte: number
    manage_dte: number
    min_delta: number
    max_delta: number
    spread_width: number
    min_iv_rank: number
    min_iv_percentile: number
    technical: {
      use_trend_filter: boolean
      use_rsi_filter: boolean
      use_support_resistance: boolean
      fast_ma: number
      slow_ma: number
      rsi_period: number
      rsi_oversold: number
      rsi_overbought: number
    }
  }
  risk: {
    account_size: number
    max_risk_per_trade: number
    max_positions: number
    profit_target: number
    stop_loss_multiplier: number
    delta_threshold: number
    min_credit_pct: number
  }
  alerts: {
    output_json: boolean
    output_text: boolean
    output_csv: boolean
    json_file: string
    text_file: string
    csv_file: string
    telegram: {
      enabled: boolean
      bot_token: string
      chat_id: string
    }
  }
  data: {
    provider: string
    backtest_lookback: number
    use_cache: boolean
    cache_expiry_minutes: number
  }
  logging: {
    level: string
    file: string
    console: boolean
  }
  backtest: {
    starting_capital: number
    commission_per_contract: number
    slippage: number
    generate_reports: boolean
    report_dir: string
  }
}

// Retry wrapper for API calls — retries on 500/503 with 1s delay, max 2 retries
// Authentication is handled via HttpOnly session cookies (set by /api/auth)
export async function apiFetch<T>(url: string, options?: RequestInit, retries = 2): Promise<T> {
  let lastError: Error | null = null
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const res = await fetch(url, {
        cache: 'no-store',
        credentials: 'same-origin',
        ...options,
        headers: { ...options?.headers },
      })
      if (res.ok) return res.json()
      if ((res.status === 500 || res.status === 503) && attempt < retries) {
        await new Promise(r => setTimeout(r, 1000))
        continue
      }
      throw new Error(`API ${url} returned ${res.status}`)
    } catch (err) {
      lastError = err as Error
      if (attempt < retries) {
        await new Promise(r => setTimeout(r, 1000))
        continue
      }
    }
  }
  throw lastError || new Error(`API ${url} failed after retries`)
}

export async function fetchAlerts(): Promise<AlertsResponse> {
  return apiFetch<AlertsResponse>('/api/alerts')
}

export async function fetchConfig(): Promise<Config> {
  return apiFetch<Config>('/api/config')
}

export async function runScan(): Promise<AlertsResponse> {
  return apiFetch<AlertsResponse>('/api/scan', { method: 'POST' })
}
