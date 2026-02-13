"use client";

export default function StatsRow() {
  const stats = [
    { label: "Today's Alerts", value: "5", change: null },
    { label: "Avg Prob. of Profit", value: "66.1%", change: null },
    { label: "30-Day Win Rate", value: "74%", change: "+3% vs last month", green: true },
    { label: "Avg Return/Trade", value: "+$285", change: null, green: true },
    { label: "Alerts This Week", value: "23", change: null },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3 mb-6">
      {stats.map((stat, idx) => (
        <div 
          key={idx} 
          className="bg-bg-white border border-border rounded-[12px] p-4 px-[18px] shadow-sm"
        >
          <div className="text-[11.5px] font-medium text-text-muted uppercase tracking-[0.5px] mb-1">
            {stat.label}
          </div>
          <div className={`text-[22px] font-bold ${stat.green ? 'text-green' : 'text-text'}`}>
            {stat.value}
          </div>
          {stat.change && (
            <div className="text-[11.5px] font-medium text-green mt-[2px]">
              {stat.change}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
