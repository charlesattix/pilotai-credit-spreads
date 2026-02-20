'use client'

import { useEffect, useRef } from 'react'

interface TvChartProps {
  ticker: string
  days: number
}

/**
 * Embeds a TradingView Advanced Chart widget for the given ticker.
 * Uses the same embed pattern as the ticker tape in layout/ticker.tsx.
 */
export function TvChart({ ticker, days }: TvChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)

  // Map lookback days to TradingView range string
  const range = days <= 90 ? '3M' : days <= 180 ? '6M' : days <= 365 ? '12M' : '60M'

  // Map ticker to TradingView exchange-qualified symbol
  const symbolMap: Record<string, string> = {
    SPY: 'AMEX:SPY',
    QQQ: 'NASDAQ:QQQ',
    IWM: 'AMEX:IWM',
    DIA: 'AMEX:DIA',
    AAPL: 'NASDAQ:AAPL',
    MSFT: 'NASDAQ:MSFT',
    NVDA: 'NASDAQ:NVDA',
    TSLA: 'NASDAQ:TSLA',
    AMZN: 'NASDAQ:AMZN',
    META: 'NASDAQ:META',
    GOOGL: 'NASDAQ:GOOGL',
  }
  const symbol = symbolMap[ticker] || `AMEX:${ticker}`

  useEffect(() => {
    if (!containerRef.current) return
    containerRef.current.innerHTML = ''

    const script = document.createElement('script')
    script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js'
    script.async = true
    script.innerHTML = JSON.stringify({
      symbol,
      interval: 'D',
      timezone: 'America/New_York',
      theme: 'light',
      style: '1',
      locale: 'en',
      allow_symbol_change: false,
      hide_top_toolbar: false,
      hide_legend: false,
      save_image: false,
      calendar: false,
      hide_volume: false,
      support_host: '',
      range,
      height: '100%',
      width: '100%',
    })
    containerRef.current.appendChild(script)

    // Cleanup on unmount or prop change
    return () => {
      if (containerRef.current) {
        containerRef.current.innerHTML = ''
      }
    }
  }, [ticker, days, symbol, range])

  return (
    <div className="bg-white rounded-lg border border-border overflow-hidden">
      <div className="px-4 py-3 border-b border-border flex items-center justify-between">
        <h3 className="text-lg font-semibold">{ticker} Price Chart</h3>
        <span className="text-xs text-muted-foreground">Powered by TradingView</span>
      </div>
      <div className="h-[400px]">
        <div className="tradingview-widget-container h-full" ref={containerRef}>
          <div className="tradingview-widget-container__widget h-full"></div>
        </div>
      </div>
    </div>
  )
}
