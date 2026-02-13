"use client";

export default function UpsellCard() {
  return (
    <div className="bg-gradient-to-br from-grad-purple/6 to-grad-orange/6 border border-grad-purple/15 rounded-lg p-5 text-center">
      <h3 className="text-[15px] font-bold mb-[6px]">
        <span className="gradient-text">Let AI Trade For You</span>
      </h3>
      <p className="text-[13px] text-text-secondary mb-[14px] leading-[1.5]">
        Love these alerts? PilotAI can build and manage a full portfolio based on strategies like these — paper trade or go live.
      </p>
      <button
        onClick={() => window.open("https://pilotai.com", "_blank")}
        className="px-6 py-[10px] rounded-[10px] border-none cursor-pointer bg-gradient-brand text-white font-semibold text-[13px] font-sans transition-opacity hover:opacity-90"
      >
        Explore PilotAI →
      </button>
    </div>
  );
}
