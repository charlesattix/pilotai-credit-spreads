"use client";

const TICKERS = [
  { sym: "SPY", price: "601.22", change: "+0.34%", up: true },
  { sym: "QQQ", price: "523.18", change: "+0.51%", up: true },
  { sym: "NVDA", price: "875.30", change: "+1.22%", up: true },
  { sym: "TSLA", price: "328.50", change: "-0.78%", up: false },
  { sym: "AAPL", price: "241.80", change: "+0.15%", up: true },
  { sym: "MU", price: "422.95", change: "+2.31%", up: true },
  { sym: "AMZN", price: "226.44", change: "+0.44%", up: true },
  { sym: "META", price: "712.30", change: "-0.21%", up: false },
  { sym: "MSFT", price: "448.92", change: "+0.18%", up: true },
  { sym: "AMD", price: "168.55", change: "+1.05%", up: true },
  { sym: "VIX", price: "14.82", change: "-3.12%", up: false },
  { sym: "GOOGL", price: "188.77", change: "+0.62%", up: true },
];

export default function TickerTape() {
  const doubled = [...TICKERS, ...TICKERS];
  
  return (
    <div className="bg-bg-white border-b border-border py-2 overflow-hidden whitespace-nowrap">
      <div className="inline-flex gap-8 animate-scroll">
        {doubled.map((ticker, idx) => (
          <span key={idx} className="inline-flex items-center gap-[6px] text-[12.5px] font-medium">
            <span className="text-text font-bold">{ticker.sym}</span>
            <span className="text-text-secondary">{ticker.price}</span>
            <span className={`font-semibold ${ticker.up ? 'text-green' : 'text-red'}`}>
              {ticker.change}
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}
