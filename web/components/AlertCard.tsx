"use client";

import { Alert } from "@/types/alert";

interface AlertCardProps {
  alert: Alert;
  expanded: boolean;
  onToggle: () => void;
}

export default function AlertCard({ alert, expanded, onToggle }: AlertCardProps) {
  const typeIcon = alert.type === "Bullish" ? "▲" : alert.type === "Bearish" ? "▼" : "◆";
  const typePillClass =
    alert.type === "Bullish"
      ? "bg-green-bg text-green border-green-border"
      : alert.type === "Bearish"
      ? "bg-red-bg text-red border-red-border"
      : "bg-yellow-bg text-yellow border-yellow-border";

  const probClass = (prob: number) => {
    if (prob >= 70) return { text: "text-green", bg: "bg-green" };
    if (prob >= 50) return { text: "text-yellow", bg: "bg-yellow" };
    return { text: "text-red", bg: "bg-red" };
  };

  const pc = probClass(alert.probProfit);

  return (
    <div
      onClick={onToggle}
      className={`bg-bg-white border rounded-lg overflow-hidden shadow-sm transition-all cursor-pointer hover:shadow-md hover:border-grad-purple/30 
        ${alert.isNew ? "border-l-[3px] border-l-grad-purple" : "border-border"}`}
    >
      {/* Header */}
      <div className="p-5 pb-[14px]">
        <div className="flex justify-between items-center mb-[10px]">
          <div className="flex items-center gap-2">
            <span className={`inline-flex items-center gap-[5px] px-3 py-1 rounded-full text-xs font-semibold border ${typePillClass}`}>
              {typeIcon} {alert.type}
            </span>
            <span className="inline-flex items-center gap-[5px] px-3 py-1 rounded-full text-xs font-semibold border bg-grad-purple/8 text-grad-purple border-grad-purple/20">
              ✦ AI-Powered
            </span>
            <span className="text-xs text-text-muted">{alert.time} ET</span>
          </div>
          <span className="inline-flex items-center gap-[5px] px-3 py-1 rounded-full text-[11px] font-semibold border bg-grad-purple/8 text-grad-purple border-grad-purple/20">
            {alert.aiConfidence} confidence
          </span>
        </div>
        <div className="flex items-baseline gap-2 mb-[2px]">
          <span className="text-[22px] font-extrabold text-text tracking-[-0.5px]">{alert.ticker}</span>
          <span className="text-sm font-semibold text-text-secondary">${alert.price.toFixed(2)}</span>
        </div>
        <div className="text-[13px] text-text-muted">{alert.company}</div>
        <div className="text-sm text-text-secondary mt-1 font-medium">
          {alert.strategy} <em className="font-normal text-text-muted not-italic">— {alert.strategyDesc}</em>
        </div>
      </div>

      {/* Quick Stats */}
      <div className="grid grid-cols-3 border-t border-border-light">
        <div className="p-3 px-[18px] border-r border-border-light">
          <div className="text-[10.5px] font-semibold text-text-muted uppercase tracking-[0.5px] mb-1">Max Profit</div>
          <div className="text-[15px] font-bold text-green">{alert.maxProfit}</div>
        </div>
        <div className="p-3 px-[18px] border-r border-border-light">
          <div className="text-[10.5px] font-semibold text-text-muted uppercase tracking-[0.5px] mb-1">Max Loss</div>
          <div className="text-[15px] font-bold text-red">{alert.maxLoss}</div>
        </div>
        <div className="p-3 px-[18px]">
          <div className="text-[10.5px] font-semibold text-text-muted uppercase tracking-[0.5px] mb-1">Prob. of Profit</div>
          <div className="flex items-center gap-2">
            <div className="flex-1 h-[5px] rounded-[3px] bg-bg-subtle overflow-hidden max-w-[70px]">
              <div className={`h-full rounded-[3px] transition-all duration-700 ${pc.bg}`} style={{ width: `${alert.probProfit}%` }} />
            </div>
            <span className={`text-[15px] font-bold ${pc.text}`}>{alert.probProfit}%</span>
          </div>
        </div>
      </div>

      {/* Expanded Details */}
      {expanded && (
        <div className="p-5 pt-4 border-t border-border-light">
          <div className="mb-[14px]">
            <div className="text-[11px] font-semibold uppercase tracking-[0.5px] text-text-muted mb-2">Trade Legs</div>
            {alert.legs.map((leg, idx) => (
              <div key={idx} className="flex items-center gap-2 p-[7px] px-3 bg-bg-subtle rounded-sm mb-1 text-[13.5px]">
                <span className={`text-[11px] font-bold px-2 py-[2px] rounded ${leg.action === "Sell" ? "bg-red-bg text-red" : "bg-green-bg text-green"}`}>
                  {leg.action}
                </span>
                <span className="text-text font-medium">
                  {leg.qty} {leg.ticker} {leg.expiry} ${leg.strike} {leg.type}
                </span>
                <span className="ml-auto text-text-muted font-medium">@ ${leg.price.toFixed(2)}</span>
              </div>
            ))}
          </div>
          {alert.netPremium && <div className="text-[13.5px] text-text-secondary mb-1"><strong className="text-text font-semibold">Net premium:</strong> {alert.netPremium}</div>}
          <div className="text-[13.5px] text-text-secondary mb-1"><strong className="text-text font-semibold">Max profit:</strong> {alert.maxProfit} — {alert.maxProfitCond}</div>
          <div className="text-[13.5px] text-text-secondary mb-1"><strong className="text-text font-semibold">Max loss:</strong> {alert.maxLoss} — {alert.maxLossCond}</div>
          <div className="text-[13.5px] text-text-secondary mb-[14px]"><strong className="text-text font-semibold">Breakeven:</strong> {alert.breakeven}</div>
          <div className="mb-[14px]">
            <div className="text-[11px] font-semibold uppercase tracking-[0.5px] text-text-muted mb-2">Why This Trade?</div>
            {alert.reasoning.map((reason, idx) => (
              <div key={idx} className="flex gap-2 mb-[6px] text-[13.5px] text-text-secondary leading-[1.55]">
                <span className="text-grad-purple flex-shrink-0 mt-[1px]">•</span>
                <span>{reason}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Expand Hint */}
      <div className="text-center py-[6px] pb-3 text-[11px] text-text-dim tracking-[0.3px]">
        {expanded ? "▲ Collapse" : "▼ View full analysis"}
      </div>
    </div>
  );
}
