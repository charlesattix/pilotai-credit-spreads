export interface TradeLeg {
  action: "Sell" | "Buy";
  qty: number;
  ticker: string;
  expiry: string;
  strike: number;
  type: "Put" | "Call";
  price: number;
}

export interface Alert {
  id: number;
  type: "Bullish" | "Bearish" | "Neutral";
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
}
