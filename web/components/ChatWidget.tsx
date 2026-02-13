"use client";

import { useState } from "react";

const SUGGESTIONS = [
  "Give me a bullish AAPL play",
  "Safe income trade today?",
  "Explain the MU spread",
  "High probability trades",
];

const CHAT_RESPONSES: Record<string, string> = {
  default:
    "Based on current market conditions, I'd look at high-IV stocks for credit spread opportunities. Elevated volatility means larger premiums while staying far OTM. Want me to find a specific setup on any ticker?",
  bullish:
    "Here's an idea: AAPL is consolidating near $242 with strong support. A Bull Call Spread — Buy $240C, Sell $250C for 28 Feb — gives a defined-risk directional play. ~$340 risk for $660 max profit, 55% probability. Check the AAPL alert below for full details!",
  income:
    "For safe income plays, look at selling puts on mega-caps trading well above support. The MU Short Put alert today has a 90.6% probability of profit — that's about as safe as it gets for a 2-day trade. MU would need to drop 10%+ before you're at risk.",
  explain:
    "The MU Bull Put Spread collects $1.30 in premium by selling the $380 Put and buying the $375 Put. With MU at $423, both puts are deeply OTM — MU would need to fall over 10% to threaten your position. Max profit is $130 if MU stays above $380 at expiry. The trade benefits from time decay working in your favor.",
  prob: "High probability trades today: the MU Short Put at 90.6% tops the list, followed by the MU Bull Put Spread at 75%. Both are credit strategies that profit from time decay and the stock simply not crashing. The tradeoff is always capped profit for higher probability.",
};

interface Message {
  role: "assistant" | "user";
  content: string;
}

export default function ChatWidget() {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content: "Hey! I can help you find trade ideas, explain any alert, or analyze a ticker. What are you looking for?",
    },
  ]);
  const [input, setInput] = useState("");
  const [showSuggestions, setShowSuggestions] = useState(true);
  const [typing, setTyping] = useState(false);

  const sendMessage = (text: string) => {
    if (!text.trim()) return;

    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setInput("");
    setShowSuggestions(false);
    setTyping(true);

    setTimeout(() => {
      const lower = text.toLowerCase();
      let reply = CHAT_RESPONSES.default;
      if (lower.includes("bullish") || lower.includes("aapl")) reply = CHAT_RESPONSES.bullish;
      else if (lower.includes("safe") || lower.includes("income")) reply = CHAT_RESPONSES.income;
      else if (lower.includes("explain") || lower.includes("spread")) reply = CHAT_RESPONSES.explain;
      else if (lower.includes("prob") || lower.includes("high")) reply = CHAT_RESPONSES.prob;

      setMessages((prev) => [...prev, { role: "assistant", content: reply }]);
      setTyping(false);
    }, 1200);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      sendMessage(input);
    }
  };

  return (
    <div className="bg-bg-white border border-border rounded-lg overflow-hidden shadow-sm">
      {/* Header */}
      <div className="p-[14px] px-4 flex items-center gap-[10px] border-b border-border-light">
        <div className="w-8 h-8 rounded-full bg-gradient-brand flex items-center justify-center text-white text-sm">✦</div>
        <div>
          <h3 className="text-sm font-semibold">Ask PilotAI</h3>
          <span className="text-[11px] text-green">● Online — get custom trade ideas</span>
        </div>
      </div>

      {/* Messages */}
      <div className="p-[14px] max-h-[260px] overflow-y-auto">
        {messages.map((msg, idx) => (
          <div
            key={idx}
            className={`mb-[10px] p-[10px] px-3 rounded-xl text-[13px] leading-[1.5] max-w-[92%] ${
              msg.role === "assistant"
                ? "bg-bg-subtle text-text-secondary rounded-bl-[4px]"
                : "bg-gradient-brand text-white rounded-br-[4px] ml-auto"
            }`}
          >
            {msg.content}
          </div>
        ))}
        {typing && <div className="mb-[10px] p-[10px] px-3 rounded-xl text-[13px] bg-bg-subtle text-text-secondary rounded-bl-[4px] opacity-50">Thinking...</div>}
      </div>

      {/* Suggestions */}
      {showSuggestions && (
        <div className="px-[14px] pb-[10px] flex flex-wrap gap-[5px]">
          {SUGGESTIONS.map((suggestion, idx) => (
            <button
              key={idx}
              onClick={() => sendMessage(suggestion)}
              className="px-[10px] py-[5px] rounded-full text-[11.5px] border border-grad-purple/20 bg-grad-purple/5 text-grad-purple cursor-pointer font-sans transition-all hover:bg-grad-purple/12 hover:border-grad-purple/35"
            >
              {suggestion}
            </button>
          ))}
        </div>
      )}

      {/* Input */}
      <div className="flex gap-[6px] p-[10px] px-[14px] border-t border-border-light">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about any ticker or strategy..."
          className="flex-1 px-3 py-[9px] rounded-[10px] border border-border text-[13px] font-sans outline-none bg-bg-subtle text-text transition-colors focus:border-grad-purple placeholder:text-text-dim"
        />
        <button
          onClick={() => sendMessage(input)}
          className="w-9 h-9 rounded-[10px] border-none bg-gradient-brand text-white cursor-pointer text-[15px] flex items-center justify-center transition-opacity hover:opacity-85"
        >
          ➤
        </button>
      </div>
    </div>
  );
}
