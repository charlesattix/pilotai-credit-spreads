"use client";

export default function Navbar() {
  return (
    <nav className="sticky top-0 z-[100] bg-white/85 backdrop-blur-[16px] border-b border-border px-8 h-14 flex items-center justify-between">
      <div className="flex items-center gap-6">
        <a href="#" className="flex items-center gap-[9px] no-underline">
          <svg width="26" height="26" viewBox="0 0 32 32" fill="none">
            <defs>
              <linearGradient id="logoGrad" x1="0" y1="0" x2="32" y2="32">
                <stop offset="0%" stopColor="#9B6DFF" />
                <stop offset="50%" stopColor="#E84FAD" />
                <stop offset="100%" stopColor="#F59E42" />
              </linearGradient>
            </defs>
            <path d="M16 3L28 16L16 29L4 16Z" stroke="url(#logoGrad)" strokeWidth="2.5" fill="none" />
            <circle cx="16" cy="12" r="2" fill="url(#logoGrad)" />
            <circle cx="12" cy="17" r="1.5" fill="url(#logoGrad)" opacity="0.6" />
            <circle cx="20" cy="17" r="1.5" fill="url(#logoGrad)" opacity="0.6" />
          </svg>
          <div className="text-[17px] font-bold text-text">
            Alerts <span className="font-normal text-text-muted">by</span> PilotAI
          </div>
        </a>
        <div className="flex gap-1">
          <button className="px-[14px] py-[6px] rounded-lg text-[13.5px] font-semibold text-text bg-bg-subtle">
            Today's Alerts
          </button>
          <button className="px-[14px] py-[6px] rounded-lg text-[13.5px] font-medium text-text-secondary hover:bg-bg-subtle hover:text-text transition-all">
            History
          </button>
          <button className="px-[14px] py-[6px] rounded-lg text-[13.5px] font-medium text-text-secondary hover:bg-bg-subtle hover:text-text transition-all">
            AI Leaderboard
          </button>
          <button className="px-[14px] py-[6px] rounded-lg text-[13.5px] font-medium text-text-secondary hover:bg-bg-subtle hover:text-text transition-all">
            Learn
          </button>
        </div>
      </div>
      <div className="flex items-center gap-[10px]">
        <div className="flex items-center gap-[6px] text-xs font-medium text-green">
          <div className="w-[7px] h-[7px] rounded-full bg-green animate-pulse-dot" />
          Markets Open
        </div>
        <button 
          onClick={() => window.open('https://pilotai.com', '_blank')}
          className="px-[18px] py-[7px] rounded-lg border-none cursor-pointer bg-gradient-brand text-white font-semibold text-[13px] hover:opacity-90 transition-opacity"
        >
          Try PilotAI →
        </button>
      </div>
    </nav>
  );
}
