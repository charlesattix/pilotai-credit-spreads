"use client";

import { useState, useEffect } from "react";
import { Alert } from "@/types/alert";
import { MOCK_ALERTS } from "@/lib/mockData";
import AlertCard from "./AlertCard";

const FILTERS = ["All", "Bullish", "Bearish", "Neutral", "High Prob. (>70%)"];

export default function AlertsFeed() {
  const [alerts, setAlerts] = useState<Alert[]>(MOCK_ALERTS);
  const [activeFilter, setActiveFilter] = useState("All");
  const [expandedId, setExpandedId] = useState<number | null>(null);

  // Fetch alerts on mount and refresh every 60s
  useEffect(() => {
    fetchAlerts();
    const interval = setInterval(fetchAlerts, 60000);
    return () => clearInterval(interval);
  }, []);

  const fetchAlerts = async () => {
    try {
      const res = await fetch("/api/alerts");
      if (res.ok) {
        const data = await res.json();
        if (data.alerts && data.alerts.length > 0) {
          setAlerts(data.alerts);
        }
      }
    } catch (error) {
      // Keep using mock data on error
      console.log("Using mock data");
    }
  };

  const filteredAlerts = alerts.filter((alert) => {
    if (activeFilter === "All") return true;
    if (activeFilter === "Bullish") return alert.type === "Bullish";
    if (activeFilter === "Bearish") return alert.type === "Bearish";
    if (activeFilter === "Neutral") return alert.type === "Neutral";
    if (activeFilter.includes("High")) return alert.probProfit >= 70;
    return true;
  });

  const today = new Date().toLocaleDateString("en-US", {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  return (
    <div>
      <div className="flex justify-between items-center mb-[14px]">
        <div>
          <div className="text-lg font-bold">Today's Alerts</div>
          <div className="text-[13px] text-text-muted">
            AI-generated trade ideas · Click to expand full analysis
          </div>
        </div>
        <div className="text-[12.5px] text-text-muted font-medium">{today}</div>
      </div>

      <div className="flex gap-[6px] mb-4 flex-wrap">
        {FILTERS.map((filter) => (
          <button
            key={filter}
            onClick={() => {
              setActiveFilter(filter);
              setExpandedId(null);
            }}
            className={`px-4 py-[6px] rounded-full text-[13px] font-medium cursor-pointer transition-all border font-sans
              ${
                activeFilter === filter
                  ? "bg-gradient-brand text-white border-transparent"
                  : "bg-bg-white text-text-secondary border-border hover:border-grad-purple hover:text-grad-purple"
              }`}
          >
            {filter}
          </button>
        ))}
      </div>

      <div className="flex flex-col gap-3">
        {filteredAlerts.map((alert) => (
          <AlertCard
            key={alert.id}
            alert={alert}
            expanded={expandedId === alert.id}
            onToggle={() => setExpandedId(expandedId === alert.id ? null : alert.id)}
          />
        ))}
      </div>
    </div>
  );
}
