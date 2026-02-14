export interface Alert {
  ticker: string
  type: string
  expiration: string
  dte: number
  short_strike: number
  long_strike: number
  short_delta: number
  credit: number
  max_loss: number
  max_profit: number
  profit_target: number
  stop_loss: number
  spread_width: number
  current_price: number
  distance_to_short: number
  pop: number
  risk_reward: number
  score: number
}

export interface AlertsResponse {
  timestamp: string
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

export interface Position {
  ticker: string
  type: string
  short_strike: number
  long_strike: number
  credit: number
  entry_date: string
  dte: number
  current_price: number
  unrealized_pnl: number
  profit_target: number
  stop_loss: number
}

export interface BacktestResult {
  total_trades: number
  winning_trades: number
  losing_trades: number
  win_rate: number
  total_pnl: number
  avg_win: number
  avg_loss: number
  profit_factor: number
  sharpe_ratio: number
  max_drawdown: number
  max_drawdown_pct: number
  equity_curve: Array<{ date: string; equity: number }>
  trade_distribution: Array<{ range: string; count: number }>
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
async function apiFetch<T>(url: string, options?: RequestInit, retries = 2): Promise<T> {
  const authToken = typeof window !== 'undefined'
    ? process.env.NEXT_PUBLIC_API_AUTH_TOKEN
    : undefined
  const authHeaders: Record<string, string> = {}
  if (authToken) {
    authHeaders['Authorization'] = `Bearer ${authToken}`
  }

  let lastError: Error | null = null
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const res = await fetch(url, {
        cache: 'no-store',
        ...options,
        headers: { ...authHeaders, ...options?.headers },
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

export async function fetchPositions(): Promise<Position[]> {
  return apiFetch<Position[]>('/api/positions')
}

export async function fetchTrades(): Promise<Trade[]> {
  return apiFetch<Trade[]>('/api/trades')
}

export async function fetchBacktest(): Promise<BacktestResult> {
  return apiFetch<BacktestResult>('/api/backtest')
}

export async function fetchConfig(): Promise<Config> {
  return apiFetch<Config>('/api/config')
}

export async function runScan(): Promise<AlertsResponse> {
  return apiFetch<AlertsResponse>('/api/scan', { method: 'POST' })
}

export async function runBacktest(): Promise<BacktestResult> {
  return apiFetch<BacktestResult>('/api/backtest/run', { method: 'POST' })
}

export async function updateConfig(config: Config): Promise<void> {
  await apiFetch<void>('/api/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  })
}
