"use client";

import ChatWidget from "./ChatWidget";
import PerformanceCard from "./PerformanceCard";
import StreakCard from "./StreakCard";
import UpsellCard from "./UpsellCard";

export default function Sidebar() {
  return (
    <div className="flex flex-col gap-4 sticky top-[76px]">
      <ChatWidget />
      <PerformanceCard />
      <StreakCard />
      <UpsellCard />
    </div>
  );
}
