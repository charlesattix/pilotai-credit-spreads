"use client";

export default function PerformanceCard() {
  const rows = [
    { label: "Total Alerts (30d)", value: "87" },
    { label: "Winners", value: "64", green: true },
    { label: "Losers", value: "23" },
    { label: "Win Rate", value: "73.6%", green: true },
    { label: "Avg. Winner", value: "+$312", green: true },
    { label: "Avg. Loser", value: "-$187" },
    { label: "Profit Factor", value: "2.43x", green: true },
  ];

  return (
    <div className="bg-bg-white border border-border rounded-lg p-[18px] shadow-sm">
      <h3 className="text-sm font-bold mb-[14px]">30-Day Performance</h3>
      {rows.map((row, idx) => (
        <div
          key={idx}
          className={`flex justify-between items-center py-2 text-[13px] ${
            idx < rows.length - 1 ? "border-b border-border-light" : ""
          }`}
        >
          <span className="text-text-secondary">{row.label}</span>
          <span className={`font-semibold ${row.green ? "text-green" : ""}`}>{row.value}</span>
        </div>
      ))}
    </div>
  );
}
