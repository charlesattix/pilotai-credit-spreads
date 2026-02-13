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

export interface TradeLeg {
  action: 'Sell' | 'Buy';
  qty: number;
  ticker: string;
  expiry: string;
  strike: number;
  type: 'Put' | 'Call';
  price: number;
}

export interface Alert {
  id: number;
  type: 'Bullish' | 'Bearish' | 'Neutral';
  ticker: string;
  company: string;
  price: number;
  strategy: string;
  strategyDesc: string;
  legs: TradeLeg[];
  netPremium?: string;
  maxProfit: string;
  maxProfitCond: string;
  maxLoss: string;
  maxLossCond: string;
  breakeven: string;
  probProfit: number;
  reasoning: string[];
  time: string;
  aiConfidence: string;
  isNew?: boolean;
  // Fields used when opening a paper trade from an alert
  current_price?: number;
  credit?: number;
  spread_width?: number;
  short_strike?: number;
  long_strike?: number;
  expiration?: string;
  dte?: number;
  pop?: number;
  score?: number;
  short_delta?: number;
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
