'use client'

import { useState } from 'react'
import { PlayCircle, Loader2 } from 'lucide-react'

const TICKERS = ['SPY', 'QQQ', 'IWM', 'DIA', 'AAPL', 'MSFT', 'NVDA', 'TSLA', 'AMZN', 'META', 'GOOGL']

const DAYS_PRESETS = [
  { label: '3 months', value: 90 },
  { label: '6 months', value: 180 },
  { label: '1 year', value: 365 },
  { label: '2 years', value: 730 },
]

interface BacktestFormProps {
  onRun: (ticker: string, days: number) => void
  loading: boolean
}

export function BacktestForm({ onRun, loading }: BacktestFormProps) {
  const [ticker, setTicker] = useState('SPY')
  const [days, setDays] = useState(365)

  return (
    <div className="bg-white rounded-lg border border-border p-6">
      <h2 className="text-lg font-semibold mb-4">Configure Backtest</h2>

      <div className="grid gap-4 sm:grid-cols-3">
        {/* Ticker Select */}
        <div>
          <label className="block text-sm font-medium text-muted-foreground mb-1.5">
            Ticker
          </label>
          <select
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            disabled={loading}
            className="w-full px-3 py-2.5 rounded-lg border border-border bg-white text-sm font-medium focus:outline-none focus:ring-2 focus:ring-brand-purple/30 focus:border-brand-purple disabled:opacity-50"
          >
            {TICKERS.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </div>

        {/* Days / Lookback */}
        <div>
          <label className="block text-sm font-medium text-muted-foreground mb-1.5">
            Lookback Period
          </label>
          <div className="flex gap-1.5">
            {DAYS_PRESETS.map((p) => (
              <button
                key={p.value}
                onClick={() => setDays(p.value)}
                disabled={loading}
                className={`flex-1 px-2 py-2.5 rounded-lg text-xs font-medium border transition-colors disabled:opacity-50 ${
                  days === p.value
                    ? 'bg-brand-purple text-white border-brand-purple'
                    : 'bg-white text-muted-foreground border-border hover:border-brand-purple/50'
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        {/* Run Button */}
        <div className="flex items-end">
          <button
            onClick={() => onRun(ticker, days)}
            disabled={loading}
            className="w-full flex items-center justify-center gap-2 px-6 py-2.5 bg-gradient-brand text-white font-medium rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50"
          >
            {loading ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                Running...
              </>
            ) : (
              <>
                <PlayCircle className="w-5 h-5" />
                Run Backtest
              </>
            )}
          </button>
        </div>
      </div>

      {loading && (
        <div className="mt-4 p-3 bg-brand-purple/5 rounded-lg border border-brand-purple/20">
          <p className="text-sm text-brand-purple">
            Backtest is running. This may take up to a few minutes if fetching historical options data from Polygon...
          </p>
        </div>
      )}
    </div>
  )
}
