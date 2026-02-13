"use client";

export default function StreakCard() {
  const days = [
    "win", "win", "loss", "win", "win", "win", "win",
    "loss", "win", "win", "win", "loss", "win", "win",
    "win", "win", "win", "loss", "win", "win", "win",
    "win", "loss", "win", "win", "win", "win", "win",
  ];

  return (
    <div className="bg-bg-white border border-border rounded-lg p-[18px] shadow-sm">
      <h3 className="text-sm font-bold mb-3">Recent 28 Days</h3>
      <div className="grid grid-cols-7 gap-1">
        {days.map((day, idx) => {
          const isStrong = day === "win" && Math.random() > 0.4;
          return (
            <div
              key={idx}
              className={`aspect-square rounded ${
                day === "win"
                  ? `bg-green ${isStrong ? "opacity-100" : "opacity-70"}`
                  : day === "loss"
                  ? "bg-red opacity-60"
                  : "bg-bg-subtle"
              }`}
            />
          );
        })}
      </div>
      <div className="flex gap-3 mt-[10px] text-[11px] text-text-muted">
        <span>
          <span className="inline-block w-[10px] h-[10px] rounded-[3px] bg-green mr-1 align-middle" /> Win
        </span>
        <span>
          <span className="inline-block w-[10px] h-[10px] rounded-[3px] bg-red mr-1 align-middle" /> Loss
        </span>
        <span>
          <span className="inline-block w-[10px] h-[10px] rounded-[3px] bg-bg-subtle mr-1 align-middle" /> No alert
        </span>
      </div>
    </div>
  );
}
