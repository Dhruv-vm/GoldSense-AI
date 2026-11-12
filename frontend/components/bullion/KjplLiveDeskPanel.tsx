"use client";

import React from "react";

interface LiveRateQuote {
  product_id: string;
  product_name: string;
  latest_price: number;
  buy_price?: number | null;
  change_inr?: number;
  change_pct?: number;
  currency: string;
  unit: string;
  source_updated_time?: string;
  observed_at?: string;
  freshness?: string;
}

interface KjplLiveDeskProps {
  terminal?: {
    spot_gold_usd?: LiveRateQuote | null;
    spot_silver_usd?: LiveRateQuote | null;
    spot_usdinr?: LiveRateQuote | null;
    gold_contract_10g?: LiveRateQuote | null;
    silver_contract_1kg?: LiveRateQuote | null;
    lbma_gold_am_usd?: LiveRateQuote | null;
    lbma_gold_pm_usd?: LiveRateQuote | null;
    lbma_silver_usd?: LiveRateQuote | null;
  } | null;
  renderBadge: (status?: string) => React.ReactNode;
}

export function KjplLiveDeskPanel({ terminal, renderBadge }: KjplLiveDeskProps) {
  const quotes: Array<{ label: string; item?: LiveRateQuote | null; decimals: number }> = [
    { label: "KJPL SPOT GOLD ($/oz)", item: terminal?.spot_gold_usd, decimals: 2 },
    { label: "KJPL SPOT SILVER ($/oz)", item: terminal?.spot_silver_usd, decimals: 2 },
    { label: "KJPL USD / INR", item: terminal?.spot_usdinr, decimals: 2 },
    { label: "KJPL GOLD CONTRACT (₹/10g)", item: terminal?.gold_contract_10g, decimals: 0 },
    { label: "KJPL SILVER CONTRACT (₹/1kg)", item: terminal?.silver_contract_1kg, decimals: 0 },
    { label: "LBMA LONDON GOLD AM ($/oz)", item: terminal?.lbma_gold_am_usd, decimals: 2 },
    { label: "LBMA LONDON GOLD PM ($/oz)", item: terminal?.lbma_gold_pm_usd, decimals: 2 },
    { label: "LBMA LONDON SILVER ($/oz)", item: terminal?.lbma_silver_usd, decimals: 4 },
  ];

  return (
    <div className="bg-[#111820] border border-[#25313D] rounded-lg p-4 sm:p-5 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#25313D] pb-3">
        <div>
          <span className="text-[10px] font-mono uppercase text-[#D6A84F] font-bold tracking-wider">
            KJPL LIVE TERMINAL TELEMETRY (EXCLUSIVE SOURCE)
          </span>
          <h3 className="text-sm sm:text-base font-bold text-white">
            KJPL International, Contract &amp; LBMA Reference Matrix
          </h3>
        </div>
        <span className="text-[10px] font-mono text-[#8795A3]">
          No external Yahoo / synthetic substitutes
        </span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 font-mono text-xs">
        {quotes.map(({ label, item, decimals }) => {
          const sym = item?.currency === "USD" ? "$" : "₹";
          return (
            <div key={label} className="p-3 rounded bg-[#0D1218] border border-[#25313D] space-y-1.5">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[10px] text-[#8795A3] truncate">{label}</span>
                {item ? renderBadge(item.freshness) : renderBadge("SOURCE_UNAVAILABLE")}
              </div>
              <div className="text-lg font-bold text-white">
                {item ? (
                  <>
                    {sym}
                    {item.latest_price.toLocaleString("en-IN", {
                      minimumFractionDigits: decimals,
                      maximumFractionDigits: decimals,
                    })}
                  </>
                ) : (
                  <span className="text-zinc-500">UNAVAILABLE</span>
                )}
              </div>
              <div className="flex items-center justify-between text-[10px] text-zinc-500">
                <span>
                  {item?.buy_price ? `Bid: ${sym}${item.buy_price.toLocaleString("en-IN")}` : `Unit: ${item?.unit || "—"}`}
                </span>
                <span>Pub: {item?.source_updated_time || "—"}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
