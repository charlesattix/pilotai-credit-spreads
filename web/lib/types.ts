// Canonical domain types for the PilotAI credit spread system

export type TradeStatus = 'open' | 'closed_profit' | 'closed_loss' | 'closed_expiry' | 'closed_manual';

export interface PaperTrade {
  id: string;
  ticker: string;
  type: string; // e.g. "bear_call_spread", "bull_put_spread"
  short_strike: number;
  long_strike: number;
  spread_width: number;
  expiration: string;
  dte_at_entry: number;
  entry_credit: number;
  entry_price: number;
  current_price?: number;
  contracts: number;
  max_profit: number;
  max_loss: number;
  status: TradeStatus;
  entry_date: string;
  exit_date?: string;
  exit_credit?: number;
  realized_pnl?: number;
  unrealized_pnl?: number;
  days_remaining?: number;
  profit_target?: number;
  stop_loss?: number;
  pop?: number;
  score?: number;
  short_delta?: number;
}

export interface Portfolio {
  trades: PaperTrade[];
  starting_balance: number;
  created_at: string;
  user_id: string;
}

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

export interface BacktestResult {
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  total_pnl: number;
  avg_win: number;
  avg_loss: number;
  profit_factor: number;
  sharpe_ratio: number;
  max_drawdown: number;
  max_drawdown_pct: number;
  equity_curve: Array<{ date: string; equity: number }>;
  trade_distribution: Array<{ range: string; count: number }>;
}

export interface Position {
  ticker: string;
  type: string;
  short_strike: number;
  long_strike: number;
  unrealized_pnl: number;
  credit?: number;
  entry_date?: string;
  dte?: number;
  current_price?: number;
  profit_target?: number;
  stop_loss?: number;
  contracts?: number;
  total_credit?: number;
  total_max_loss?: number;
  days_remaining?: number;
  days_held?: number;
  max_profit?: number;
  pnl_pct?: number;
  expiration?: string;
}

export interface PortfolioStats {
  total_trades: number;
  open_trades: number;
  closed_trades: number;
  winners: number;
  losers: number;
  win_rate: number;
  total_realized_pnl: number;
  total_unrealized_pnl: number;
  total_pnl: number;
  balance: number;
  starting_balance: number;
}

export interface PositionsSummary {
  account_size: number;
  starting_balance: number;
  current_balance: number;
  total_pnl: number;
  total_realized_pnl: number;
  total_unrealized_pnl: number;
  total_trades: number;
  open_count: number;
  closed_count: number;
  win_rate: number;
  total_credit: number;
  total_max_loss: number;
  open_positions: PaperTrade[];
  closed_trades: PaperTrade[];
}
