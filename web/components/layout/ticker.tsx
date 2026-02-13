'use client'

import { useEffect, useRef } from 'react'

export function Ticker() {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!containerRef.current) return
    containerRef.current.innerHTML = ''

    const script = document.createElement('script')
    script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-ticker-tape.js'
    script.async = true
    script.innerHTML = JSON.stringify({
      symbols: [
        { proName: 'AMEX:SPY', title: 'SPY' },
        { proName: 'NASDAQ:QQQ', title: 'QQQ' },
        { proName: 'AMEX:IWM', title: 'IWM' },
        { proName: 'AMEX:DIA', title: 'DIA' },
        { proName: 'NASDAQ:NVDA', title: 'NVDA' },
        { proName: 'NASDAQ:AAPL', title: 'AAPL' },
        { proName: 'NASDAQ:MSFT', title: 'MSFT' },
        { proName: 'NASDAQ:TSLA', title: 'TSLA' },
        { proName: 'NASDAQ:AMZN', title: 'AMZN' },
        { proName: 'NASDAQ:META', title: 'META' },
        { proName: 'NASDAQ:GOOGL', title: 'GOOGL' },
      ],
      showSymbolLogo: true,
      isTransparent: true,
      displayMode: 'adaptive',
      colorTheme: 'light',
      locale: 'en',
      largeChartUrl: '',
    })
    containerRef.current.appendChild(script)
  }, [])

  return (
    <div className="bg-white border-b border-border overflow-hidden">
      <div className="tradingview-widget-container" ref={containerRef}>
        <div className="tradingview-widget-container__widget"></div>
      </div>
    </div>
  )
}
