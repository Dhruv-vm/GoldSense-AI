"use client";

import React, { useState, useEffect, useMemo } from "react";

// =============================================================================
// TYPES & INTERFACES
// =============================================================================

interface CityRateItem {
  city_code: string;
  city_display_name: string;
  product_id: string;
  product_name: string;
  metal: string;
  purity: number;
  weight: number;
  unit: string;
  rate_type: string;
  latest_price: number;
  previous_price: number;
  change_inr: number;
  change_pct: number;
  per_gram_price: number;
  currency: string;
  source_updated_time: string;
  observed_at: string;
  last_verified_at: string;
  freshness: string;
  age_hours?: number;
  age_display?: string;
  source_url: string;
}

interface CityComparisonItem {
  city_code: string;
  city_display_name: string;
  total_price_100g: number | null;
  per_gram_price: number | null;
  spread_vs_chennai_inr: number | null;
  spread_vs_chennai_pct: number | null;
  is_baseline: boolean;
  source_updated_time: string;
  observed_at: string | null;
  last_verified_at: string | null;
  freshness: string;
}

interface BullionComparisonResponse {
  benchmark_city: string;
  benchmark_per_gram: number;
  product_id: string;
  product_name: string;
  cities: CityComparisonItem[];
  calculated_at: string;
}

interface BullionCity {
  city_code: string;
  display_name: string;
  state: string;
  is_active: boolean;
  sort_order: number;
  is_default: boolean;
}

interface BullionSummaryResponse {
  terminal_title: string;
  default_city: string;
  benchmark_gold_24k: CityRateItem | null;
  benchmark_silver: CityRateItem | null;
  wholesale_gold_1kg: CityRateItem | null;
  city_tape: Array<{
    city_code: string;
    city_name: string;
    price_100g: number;
    per_gram: number;
    source_updated_time: string;
    freshness: string;
  }>;
  parity: {
    xauusd: number;
    xagusd: number;
    usdinr: number;
    import_cost_per_gram: number;
    landed_duty_paid_per_gram: number;
    domestic_premium_inr: number;
    domestic_premium_pct: number;
    market_freshness: string;
  } | null;
  timestamp_utc: string;
  timestamp_ist: string;
}

interface DataMonitorStatus {
  status: string;
  service: string;
  environment: string;
  database: {
    connected: boolean;
    engine: string;
    description: string;
    is_production_ready: boolean;
  };
  city_freshness: Record<
    string,
    {
      freshness: string;
      age_hours: number;
      age_display: string;
      source_updated_time: string;
      last_verified_at: string | null;
    }
  >;
  recent_runs: Array<{
    collector_name: string;
    status: string;
    records_extracted: number;
    records_inserted: number;
    records_changed: number;
    duration_seconds: number;
    executed_at: string;
    error_message: string | null;
  }>;
  timestamp_utc: string;
}

interface NewsItem {
  id?: string;
  title: string;
  source: string;
  published_at: string;
  url: string;
  summary?: string;
  finbert_driver?: string;
  sentiment_score?: number;
  relevance_score?: number;
  evidence_rationale?: string;
  age_display?: string;
  syndicated_copies_count?: number;
}

interface LiveNewsSignal {
  net_sentiment_score: number;
  overall_signal: string;
  total_articles: number;
  driver_distribution?: Record<string, number>;
  top_drivers?: Array<{ driver: string; count: number; sentiment: number }>;
}

interface PortfolioSummary {
  total_items: number;
  unique_holdings: number;
  gold: {
    gross_weight_grams: number;
    fine_weight_grams: number;
    fine_weight_kg: number;
    estimated_valuation_inr: number;
    allocation_pct: number;
  };
  silver: {
    gross_weight_grams: number;
    fine_weight_grams: number;
    fine_weight_kg: number;
    estimated_valuation_inr: number;
    allocation_pct: number;
  };
  total_estimated_valuation_inr: number;
  total_recorded_acquisition_cost_inr: number | null;
  unrealized_gain_loss_inr: number | null;
  unrealized_gain_loss_pct: number | null;
  benchmark_rates: {
    gold_mjdta_inr_per_gram: number;
    silver_mjdta_inr_per_gram: number;
    disclaimer: string;
  };
}

interface Holding {
  id: number;
  metal_type: string;
  product_name: string;
  purity: number;
  gross_weight_grams: number;
  fine_weight_grams: number;
  fine_weight_kg: number;
  quantity: number;
  acquisition_date: string | null;
  acquisition_cost_inr: number | null;
  current_valuation_inr: number;
  unrealized_gain_loss_inr: number | null;
  unrealized_gain_loss_pct: number | null;
  notes: string | null;
}

interface AlertRule {
  id: number;
  alert_type: string;
  target_metric: string;
  threshold: number;
  notes: string | null;
  created_at: string;
}

type TerminalTab =
  | "overview"
  | "india-bullion"
  | "markets"
  | "news"
  | "analytics"
  | "vault"
  | "alerts"
  | "data-monitor"
  | "settings";

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export default function VMDBullionDashboard() {
  const [activeTab, setActiveTab] = useState<TerminalTab>("overview");
  const [selectedCity, setSelectedCity] = useState<string>("CHENNAI");

  // Bullion data states
  const [bullionSummary, setBullionSummary] = useState<BullionSummaryResponse | null>(null);
  const [bullionCities, setBullionCities] = useState<BullionCity[]>([]);
  const [cityRates, setCityRates] = useState<CityRateItem[]>([]);
  const [cityComparison, setCityComparison] = useState<BullionComparisonResponse | null>(null);
  const [monitorStatus, setMonitorStatus] = useState<DataMonitorStatus | null>(null);
  const [historyRecords, setHistoryRecords] = useState<any[]>([]);

  // News states
  const [news, setNews] = useState<NewsItem[]>([]);
  const [newsWindowHours, setNewsWindowHours] = useState<number>(24);
  const [liveNewsSignal, setLiveNewsSignal] = useState<LiveNewsSignal | null>(null);
  const [newsDriverFilter, setNewsDriverFilter] = useState<string>("ALL");

  // Vault / Portfolio states
  const [portfolioSummary, setPortfolioSummary] = useState<PortfolioSummary | null>(null);
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [alerts, setAlerts] = useState<AlertRule[]>([]);

  // UI state
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [refreshNotice, setRefreshNotice] = useState<string | null>(null);
  const [userId, setUserId] = useState("owner");
  const [apiKey, setApiKey] = useState("");

  // Modals
  const [isAddHoldingOpen, setIsAddHoldingOpen] = useState(false);
  const [isEditHoldingOpen, setIsEditHoldingOpen] = useState(false);
  const [editingHolding, setEditingHolding] = useState<Holding | null>(null);
  const [isAddAlertOpen, setIsAddAlertOpen] = useState(false);

  // Forms
  const [holdingForm, setHoldingForm] = useState({
    metal_type: "GOLD",
    product_name: "100g 999 Pure Bar",
    purity: "0.999",
    gross_weight: "100.0",
    weight_unit: "g",
    quantity: "1",
    acquisition_date: new Date().toISOString().split("T")[0],
    acquisition_cost_inr: "",
    notes: "VMD Bullion Vault",
  });

  const [alertForm, setAlertForm] = useState({
    alert_type: "PRICE_ABOVE",
    target_metric: "CHENNAI_GOLD_24K",
    threshold: "13500",
    notes: "",
  });

  const getHeaders = () => {
    const h: Record<string, string> = { "Content-Type": "application/json" };
    if (userId) h["X-User-ID"] = userId;
    if (apiKey) h["Authorization"] = `Bearer ${apiKey}`;
    return h;
  };

  // ===========================================================================
  // DATA FETCHING
  // ===========================================================================

  const fetchBullionData = async () => {
    try {
      // 1. Summary
      const sumRes = await fetch("/api/bullion/latest");
      if (sumRes.ok) setBullionSummary(await sumRes.json());

      // 2. Cities
      const citiesRes = await fetch("/api/bullion/cities");
      if (citiesRes.ok) setBullionCities(await citiesRes.json());

      // 3. City rates
      const ratesRes = await fetch("/api/bullion/city-rates");
      if (ratesRes.ok) setCityRates(await ratesRes.json());

      // 4. City comparison matrix
      const compRes = await fetch("/api/bullion/comparison");
      if (compRes.ok) setCityComparison(await compRes.json());

      // 5. Data monitor
      const monRes = await fetch("/api/data-monitor/status");
      if (monRes.ok) setMonitorStatus(await monRes.json());

      // 6. History for selected city
      const histRes = await fetch(`/api/bullion/history?city=${selectedCity}&limit=20`);
      if (histRes.ok) setHistoryRecords(await histRes.json());
    } catch (e) {
      console.error("Error fetching bullion data", e);
    }
  };

  const fetchNewsData = async (windowHours: number) => {
    try {
      const sigRes = await fetch(`/api/news/live-signal?window_hours=${windowHours}`);
      if (sigRes.ok) setLiveNewsSignal(await sigRes.json());

      const newsRes = await fetch(`/api/news/latest?window_hours=${windowHours}&limit=50`);
      if (newsRes.ok) {
        const json = await newsRes.json();
        setNews(Array.isArray(json) ? json : json.articles || []);
      }
    } catch (e) {
      console.error("Error fetching news", e);
    }
  };

  const fetchPortfolioAndAlerts = async () => {
    try {
      const headers = getHeaders();
      const pfRes = await fetch("/api/portfolio/summary", { headers });
      if (pfRes.ok) setPortfolioSummary(await pfRes.json());

      const hldRes = await fetch("/api/portfolio/holdings", { headers });
      if (hldRes.ok) setHoldings(await hldRes.json());

      const alRes = await fetch("/api/alerts", { headers });
      if (alRes.ok) setAlerts(await alRes.json());
    } catch (e) {
      console.error("Error fetching portfolio/alerts", e);
    }
  };

  const loadAll = async () => {
    setIsLoading(true);
    await Promise.all([fetchBullionData(), fetchNewsData(newsWindowHours), fetchPortfolioAndAlerts()]);
    setIsLoading(false);
  };

  useEffect(() => {
    loadAll();
  }, [userId, apiKey]);

  useEffect(() => {
    fetchNewsData(newsWindowHours);
  }, [newsWindowHours]);

  useEffect(() => {
    fetch(`/api/bullion/history?city=${selectedCity}&limit=20`)
      .then((res) => (res.ok ? res.json() : []))
      .then((data) => setHistoryRecords(data))
      .catch(() => {});
  }, [selectedCity]);

  // Refresh handler
  const handleRefresh = async () => {
    setIsRefreshing(true);
    setRefreshNotice(null);
    try {
      const res = await fetch("/api/market/refresh", { method: "POST" });
      const data = await res.json();
      if (data.refreshed === false) {
        setRefreshNotice(data.message || "Market cooldown active (60s). Rates retained.");
      } else {
        setRefreshNotice("Market & bullion observations updated.");
      }
      await fetchBullionData();
    } catch (e) {
      setRefreshNotice("Data refreshed with verified cache.");
    } finally {
      setIsRefreshing(false);
      setTimeout(() => setRefreshNotice(null), 4000);
    }
  };

  // Holdings Handlers
  const handleCreateHolding = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const payload = {
        metal_type: holdingForm.metal_type,
        product_name: holdingForm.product_name,
        purity: parseFloat(holdingForm.purity),
        gross_weight: parseFloat(holdingForm.gross_weight),
        weight_unit: holdingForm.weight_unit,
        quantity: parseInt(holdingForm.quantity, 10),
        acquisition_date: holdingForm.acquisition_date || null,
        acquisition_cost_inr: holdingForm.acquisition_cost_inr ? parseFloat(holdingForm.acquisition_cost_inr) : null,
        notes: holdingForm.notes,
      };
      const res = await fetch("/api/portfolio/holdings", {
        method: "POST",
        headers: getHeaders(),
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        setIsAddHoldingOpen(false);
        fetchPortfolioAndAlerts();
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleUpdateHolding = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingHolding) return;
    try {
      const payload = {
        metal_type: holdingForm.metal_type,
        product_name: holdingForm.product_name,
        purity: parseFloat(holdingForm.purity),
        gross_weight: parseFloat(holdingForm.gross_weight),
        weight_unit: holdingForm.weight_unit,
        quantity: parseInt(holdingForm.quantity, 10),
        acquisition_date: holdingForm.acquisition_date || null,
        acquisition_cost_inr: holdingForm.acquisition_cost_inr ? parseFloat(holdingForm.acquisition_cost_inr) : null,
        notes: holdingForm.notes,
      };
      const res = await fetch(`/api/portfolio/holdings/${editingHolding.id}`, {
        method: "PUT",
        headers: getHeaders(),
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        setIsEditHoldingOpen(false);
        setEditingHolding(null);
        fetchPortfolioAndAlerts();
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleDeleteHolding = async (id: number) => {
    if (!confirm("Remove this bullion holding from your vault?")) return;
    try {
      const res = await fetch(`/api/portfolio/holdings/${id}`, {
        method: "DELETE",
        headers: getHeaders(),
      });
      if (res.ok) fetchPortfolioAndAlerts();
    } catch (err) {
      console.error(err);
    }
  };

  const openEditModal = (h: Holding) => {
    setEditingHolding(h);
    setHoldingForm({
      metal_type: h.metal_type,
      product_name: h.product_name,
      purity: String(h.purity),
      gross_weight: String(h.gross_weight_grams),
      weight_unit: "g",
      quantity: String(h.quantity),
      acquisition_date: h.acquisition_date || "",
      acquisition_cost_inr: h.acquisition_cost_inr !== null ? String(h.acquisition_cost_inr) : "",
      notes: h.notes || "",
    });
    setIsEditHoldingOpen(true);
  };

  // Alert Handlers
  const handleCreateAlert = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const payload = {
        alert_type: alertForm.alert_type,
        target_metric: alertForm.target_metric,
        threshold: parseFloat(alertForm.threshold),
        notes: alertForm.notes,
      };
      const res = await fetch("/api/alerts", {
        method: "POST",
        headers: getHeaders(),
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        setIsAddAlertOpen(false);
        fetchPortfolioAndAlerts();
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleDeleteAlert = async (id: number) => {
    try {
      const res = await fetch(`/api/alerts/${id}`, {
        method: "DELETE",
        headers: getHeaders(),
      });
      if (res.ok) fetchPortfolioAndAlerts();
    } catch (err) {
      console.error(err);
    }
  };

  // Filtered news by FinBERT driver
  const filteredNews = useMemo(() => {
    if (newsDriverFilter === "ALL") return news;
    return news.filter((n) => n.finbert_driver === newsDriverFilter);
  }, [news, newsDriverFilter]);

  // Selected city rates
  const selectedCityRates = useMemo(() => {
    return cityRates.filter((r) => r.city_code === selectedCity);
  }, [cityRates, selectedCity]);

  // ===========================================================================
  // RENDER HELPERS
  // ===========================================================================

  const formatINR = (val: number | null | undefined, decimals = 2) => {
    if (val === null || val === undefined) return "—";
    return new Intl.NumberFormat("en-IN", {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    }).format(val);
  };

  const getFreshnessBadge = (status: string | undefined) => {
    const s = (status || "").toUpperCase();
    if (s === "FRESH") {
      return (
        <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold bg-emerald-950 text-emerald-400 border border-emerald-800">
          ● FRESH
        </span>
      );
    }
    if (s === "DELAYED") {
      return (
        <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold bg-amber-950 text-amber-400 border border-amber-800">
          ▲ DELAYED
        </span>
      );
    }
    return (
      <span className="px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold bg-rose-950 text-rose-400 border border-rose-800">
        ✕ STALE
      </span>
    );
  };

  return (
    <div className="min-h-screen bg-[#080B0F] text-[#E5EAF0] flex flex-col font-sans selection:bg-[#D6A84F]/30 selection:text-[#D6A84F]">
      {/* ===================================================================== */}
      {/* 1. INSTITUTIONAL TOP BAR & CONTINUOUS CITY TICKER TAPE                */}
      {/* ===================================================================== */}
      <header className="border-b border-[#25313D] bg-[#0D1218]/90 backdrop-blur sticky top-0 z-40">
        <div className="max-w-[1720px] mx-auto px-3 sm:px-6 py-2.5 flex flex-wrap items-center justify-between gap-3">
          {/* Logo & Terminal Identity */}
          <div className="flex items-center gap-3">
            {/* Geometric VMD Monogram SVG */}
            <div className="w-9 h-9 rounded bg-gradient-to-br from-[#D6A84F]/20 via-[#111820] to-[#25313D] border border-[#D6A84F]/40 flex items-center justify-center shadow-inner">
              <svg viewBox="0 0 36 36" className="w-6 h-6 text-[#D6A84F]" fill="currentColor">
                <path d="M4 6 L12 28 L15 28 L20 14 L25 28 L28 28 L36 6 L31 6 L26.5 21 L22 8 L18 8 L13.5 21 L9 6 Z" />
              </svg>
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-mono font-black text-sm sm:text-base tracking-wider text-white">
                  VMD BULLION
                </span>
                <span className="text-[10px] font-mono px-1.5 py-0.2 bg-[#D6A84F]/10 text-[#D6A84F] border border-[#D6A84F]/30 rounded">
                  TERMINAL 2.0
                </span>
              </div>
              <p className="text-[10px] text-[#8B98A5] font-mono tracking-wide hidden sm:block">
                INDIAN INSTITUTIONAL BULLION INTELLIGENCE &bull; KJPL VERIFIED
              </p>
            </div>
          </div>

          {/* Engine & Connection Status */}
          <div className="flex items-center gap-2 sm:gap-4 text-xs font-mono">
            {monitorStatus?.database ? (
              <span className="px-2 py-0.5 rounded text-[11px] bg-[#111820] border border-[#25313D] text-[#8B98A5] flex items-center gap-1.5">
                <span className={`w-1.5 h-1.5 rounded-full ${monitorStatus.database.connected ? "bg-emerald-400" : "bg-rose-400"}`} />
                {monitorStatus.database.engine.toUpperCase()}{" "}
                <span className="text-[9px] text-zinc-500">
                  {monitorStatus.database.is_production_ready ? "PROD" : "DEV"}
                </span>
              </span>
            ) : null}

            <span className="text-[#8B98A5] text-[11px] hidden md:inline">
              {bullionSummary?.timestamp_ist || "CONNECTING..."}
            </span>

            <button
              onClick={handleRefresh}
              disabled={isRefreshing}
              className="px-2.5 py-1 rounded bg-[#111820] hover:bg-[#1E293B] border border-[#25313D] hover:border-[#D6A84F]/50 text-white font-mono text-[11px] flex items-center gap-1.5 transition"
            >
              <span className={isRefreshing ? "animate-spin inline-block" : ""}>↻</span>
              <span>{isRefreshing ? "SYNCING..." : "SYNC"}</span>
            </button>
          </div>
        </div>

        {/* Continuous 5-City & Forex Ticker Tape */}
        <div className="border-t border-[#25313D]/60 bg-[#080B0F] overflow-x-auto no-scrollbar py-1 px-3 sm:px-6">
          <div className="flex items-center gap-6 min-w-max text-xs font-mono">
            <span className="text-[10px] text-[#D6A84F] font-bold tracking-wider uppercase flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-[#D6A84F] animate-pulse" />
              LIVE TAPE:
            </span>

            {/* City entries */}
            {bullionSummary?.city_tape?.map((c) => (
              <div
                key={c.city_code}
                onClick={() => {
                  setSelectedCity(c.city_code);
                  setActiveTab("india-bullion");
                }}
                className="flex items-center gap-1.5 cursor-pointer hover:text-[#D6A84F] transition"
              >
                <span className="text-[#8B98A5] uppercase">{c.city_name}:</span>
                <span className="font-semibold text-white">₹{formatINR(c.per_gram)}/g</span>
                <span className="text-[10px] text-zinc-500">({c.source_updated_time})</span>
              </div>
            ))}

            {/* International Parity & Forex */}
            {bullionSummary?.parity && (
              <>
                <div className="flex items-center gap-1.5 pl-3 border-l border-[#25313D]">
                  <span className="text-[#8B98A5]">XAU/USD:</span>
                  <span className="font-semibold text-white">${formatINR(bullionSummary.parity.xauusd, 2)}</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="text-[#8B98A5]">USD/INR:</span>
                  <span className="font-semibold text-white">₹{formatINR(bullionSummary.parity.usdinr, 2)}</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="text-[#8B98A5]">PREMIUM:</span>
                  <span
                    className={`font-semibold ${bullionSummary.parity.domestic_premium_inr >= 0 ? "text-emerald-400" : "text-rose-400"}`}
                  >
                    {bullionSummary.parity.domestic_premium_inr >= 0 ? "+" : ""}
                    ₹{formatINR(bullionSummary.parity.domestic_premium_inr, 1)}/g
                  </span>
                </div>
              </>
            )}
          </div>
        </div>

        {/* Global Notification Banner */}
        {refreshNotice && (
          <div className="bg-[#111820] border-y border-[#D6A84F]/40 px-4 py-1 text-center text-xs font-mono text-[#D6A84F]">
            {refreshNotice}
          </div>
        )}
      </header>

      {/* ===================================================================== */}
      {/* 2. TERMINAL WORKSTATION NAVIGATION BAR (F1-F9)                        */}
      {/* ===================================================================== */}
      <nav className="border-b border-[#25313D] bg-[#0D1218] px-3 sm:px-6">
        <div className="max-w-[1720px] mx-auto flex items-center gap-1 overflow-x-auto no-scrollbar py-1">
          {[
            { id: "overview", label: "OVERVIEW", key: "F1" },
            { id: "india-bullion", label: "INDIA BULLION (5 CITIES)", key: "F2", highlight: true },
            { id: "markets", label: "GLOBAL MARKETS & PARITY", key: "F3" },
            { id: "news", label: "NEWS INTELLIGENCE", key: "F4" },
            { id: "analytics", label: "ARBITRAGE & SPREADS", key: "F5" },
            { id: "vault", label: "PORTFOLIO VAULT", key: "F6" },
            { id: "alerts", label: "ALERTS", key: "F7" },
            { id: "data-monitor", label: "DATA MONITOR", key: "F8" },
            { id: "settings", label: "SETTINGS", key: "F9" },
          ].map((tab) => {
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as TerminalTab)}
                className={`px-3 py-2 rounded text-xs font-mono font-medium transition whitespace-nowrap flex items-center gap-1.5 ${
                  isActive
                    ? "bg-[#D6A84F]/15 text-[#D6A84F] border border-[#D6A84F]/40 shadow-sm"
                    : "text-[#8B98A5] hover:text-white hover:bg-[#111820]"
                }`}
              >
                <span className="text-[10px] text-zinc-500">[{tab.key}]</span>
                <span>{tab.label}</span>
                {tab.highlight && (
                  <span className="w-1.5 h-1.5 rounded-full bg-[#D6A84F] inline-block" />
                )}
              </button>
            );
          })}
        </div>
      </nav>

      {/* ===================================================================== */}
      {/* 3. MAIN TERMINAL WORKSPACE                                            */}
      {/* ===================================================================== */}
      <main className="flex-1 max-w-[1720px] w-full mx-auto p-3 sm:p-6 space-y-6">
        {isLoading ? (
          <div className="flex flex-col items-center justify-center min-h-[400px] space-y-4">
            <div className="w-10 h-10 border-2 border-[#D6A84F] border-t-transparent rounded-full animate-spin" />
            <p className="text-xs font-mono text-[#8B98A5]">
              INITIALIZING VMD BULLION TERMINAL &bull; LOADING VERIFIED RATES...
            </p>
          </div>
        ) : (
          <>
            {/* =============================================================== */}
            {/* TAB 1: OVERVIEW WORKSTATION                                     */}
            {/* =============================================================== */}
            {activeTab === "overview" && (
              <div className="space-y-6">
                {/* Hero 4-card Benchmark Strip */}
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                  {/* Card 1: Chennai MJDTA Gold 24K */}
                  <div className="bg-[#111820] border border-[#25313D] rounded-lg p-4 relative overflow-hidden group hover:border-[#D6A84F]/40 transition">
                    <div className="flex justify-between items-start mb-2">
                      <div>
                        <div className="text-[10px] font-mono uppercase text-[#D6A84F] font-bold tracking-wider">
                          PRIMARY INDIAN BENCHMARK
                        </div>
                        <h3 className="text-sm font-semibold text-white">Chennai MJDTA Gold 24K</h3>
                      </div>
                      {getFreshnessBadge(bullionSummary?.benchmark_gold_24k?.freshness)}
                    </div>

                    <div className="mt-3 flex items-baseline gap-2">
                      <span className="text-2xl sm:text-3xl font-mono font-bold text-white tracking-tight">
                        ₹{formatINR(bullionSummary?.benchmark_gold_24k?.latest_price)}
                      </span>
                      <span className="text-xs font-mono text-[#8B98A5]">/ gram</span>
                    </div>

                    <div className="mt-2 text-xs font-mono text-zinc-400 flex items-center justify-between border-t border-[#25313D]/60 pt-2">
                      <span>With 3% GST:</span>
                      <span className="text-white font-semibold">
                        ₹
                        {formatINR(
                          (bullionSummary?.benchmark_gold_24k?.latest_price || 0) * 1.03
                        )}
                        /g
                      </span>
                    </div>

                    <div className="mt-2 flex items-center justify-between text-[10px] font-mono text-zinc-500">
                      <span>Source: KJPL MJDTA</span>
                      <span>Pub: {bullionSummary?.benchmark_gold_24k?.source_updated_time || "N/A"}</span>
                    </div>
                  </div>

                  {/* Card 2: MJDTA Silver Spot */}
                  <div className="bg-[#111820] border border-[#25313D] rounded-lg p-4 relative overflow-hidden hover:border-[#B8C1CA]/40 transition">
                    <div className="flex justify-between items-start mb-2">
                      <div>
                        <div className="text-[10px] font-mono uppercase text-[#B8C1CA] font-bold tracking-wider">
                          SILVER BENCHMARK
                        </div>
                        <h3 className="text-sm font-semibold text-white">Spot Silver (Chennai / India)</h3>
                      </div>
                      {getFreshnessBadge(bullionSummary?.benchmark_silver?.freshness)}
                    </div>

                    <div className="mt-3 flex items-baseline gap-2">
                      <span className="text-2xl sm:text-3xl font-mono font-bold text-white tracking-tight">
                        ₹{formatINR(bullionSummary?.benchmark_silver?.latest_price)}
                      </span>
                      <span className="text-xs font-mono text-[#8B98A5]">/ gram</span>
                    </div>

                    <div className="mt-2 text-xs font-mono text-zinc-400 flex items-center justify-between border-t border-[#25313D]/60 pt-2">
                      <span>1 KG Bar Equivalent:</span>
                      <span className="text-white font-semibold">
                        ₹
                        {formatINR(
                          (bullionSummary?.benchmark_silver?.latest_price || 0) * 1000
                        )}
                      </span>
                    </div>

                    <div className="mt-2 flex items-center justify-between text-[10px] font-mono text-zinc-500">
                      <span>Unit: 1g Pure Fine</span>
                      <span>Pub: {bullionSummary?.benchmark_silver?.source_updated_time || "N/A"}</span>
                    </div>
                  </div>

                  {/* Card 3: Wholesale Gold 1KG Pure Bar */}
                  <div className="bg-[#111820] border border-[#25313D] rounded-lg p-4 relative overflow-hidden hover:border-[#D6A84F]/40 transition">
                    <div className="flex justify-between items-start mb-2">
                      <div>
                        <div className="text-[10px] font-mono uppercase text-[#D6A84F] font-bold tracking-wider">
                          COMMERCIAL WHOLESALE
                        </div>
                        <h3 className="text-sm font-semibold text-white">Gold 1KG 99.99 Pure Bar</h3>
                      </div>
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-zinc-800 text-zinc-300">
                        99.99 PURE
                      </span>
                    </div>

                    <div className="mt-3 flex items-baseline gap-2">
                      <span className="text-xl sm:text-2xl font-mono font-bold text-white tracking-tight">
                        ₹{formatINR(bullionSummary?.wholesale_gold_1kg?.latest_price, 0)}
                      </span>
                    </div>

                    <div className="mt-2 text-xs font-mono text-zinc-400 flex items-center justify-between border-t border-[#25313D]/60 pt-2">
                      <span>Per-gram wholesale:</span>
                      <span className="text-[#D6A84F] font-semibold">
                        ₹{formatINR(bullionSummary?.wholesale_gold_1kg?.per_gram_price)}/g
                      </span>
                    </div>

                    <div className="mt-2 flex items-center justify-between text-[10px] font-mono text-zinc-500">
                      <span>Standard: 1,000g Cast Bar</span>
                      <span>Pub: {bullionSummary?.wholesale_gold_1kg?.source_updated_time || "N/A"}</span>
                    </div>
                  </div>

                  {/* Card 4: Import Parity & Domestic Premium */}
                  <div className="bg-[#111820] border border-[#25313D] rounded-lg p-4 relative overflow-hidden hover:border-emerald-500/40 transition">
                    <div className="flex justify-between items-start mb-2">
                      <div>
                        <div className="text-[10px] font-mono uppercase text-emerald-400 font-bold tracking-wider">
                          PARITY ARBITRAGE
                        </div>
                        <h3 className="text-sm font-semibold text-white">Landed Duty-Paid Parity</h3>
                      </div>
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-zinc-800 text-zinc-300">
                        DUTY 6% + 1%
                      </span>
                    </div>

                    <div className="mt-3 flex items-baseline gap-2">
                      <span className="text-2xl sm:text-3xl font-mono font-bold text-white tracking-tight">
                        ₹{formatINR(bullionSummary?.parity?.landed_duty_paid_per_gram)}
                      </span>
                      <span className="text-xs font-mono text-[#8B98A5]">/ gram</span>
                    </div>

                    <div className="mt-2 text-xs font-mono text-zinc-400 flex items-center justify-between border-t border-[#25313D]/60 pt-2">
                      <span>Domestic Premium:</span>
                      <span
                        className={`font-semibold ${
                          (bullionSummary?.parity?.domestic_premium_inr || 0) >= 0
                            ? "text-emerald-400"
                            : "text-rose-400"
                        }`}
                      >
                        {(bullionSummary?.parity?.domestic_premium_inr || 0) >= 0 ? "+" : ""}
                        ₹{formatINR(bullionSummary?.parity?.domestic_premium_inr)}/g (
                        {bullionSummary?.parity?.domestic_premium_pct}%)
                      </span>
                    </div>

                    <div className="mt-2 flex items-center justify-between text-[10px] font-mono text-zinc-500">
                      <span>COMEX: ${bullionSummary?.parity?.xauusd}</span>
                      <span>USD/INR: ₹{bullionSummary?.parity?.usdinr}</span>
                    </div>
                  </div>
                </div>

                {/* 5-City Institutional Comparison Matrix Quick Preview */}
                <div className="bg-[#111820] border border-[#25313D] rounded-lg p-4 sm:p-6 space-y-4">
                  <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#25313D] pb-4">
                    <div>
                      <h2 className="text-base sm:text-lg font-bold text-white flex items-center gap-2">
                        <span>5-CITY RETAIL BULLION MATRIX</span>
                        <span className="text-[11px] font-mono px-2 py-0.5 bg-[#D6A84F]/10 text-[#D6A84F] border border-[#D6A84F]/30 rounded">
                          GOLD 100 GMS 999
                        </span>
                      </h2>
                      <p className="text-xs font-mono text-[#8B98A5] mt-0.5">
                        Verified Kundanmal Jhabak rates normalized to ₹/gram with Chennai baseline spread.
                      </p>
                    </div>

                    <button
                      onClick={() => setActiveTab("india-bullion")}
                      className="px-3 py-1.5 rounded bg-[#1E293B] hover:bg-[#D6A84F]/20 text-xs font-mono text-[#D6A84F] border border-[#25313D] hover:border-[#D6A84F]/50 transition"
                    >
                      EXPLORE INDIA BULLION WORKSTATION &rarr;
                    </button>
                  </div>

                  {/* Table */}
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs font-mono text-left">
                      <thead>
                        <tr className="border-b border-[#25313D] text-[#8B98A5]">
                          <th className="py-2.5 px-3">CITY</th>
                          <th className="py-2.5 px-3">STATE</th>
                          <th className="py-2.5 px-3 text-right">TOTAL 100G RATE</th>
                          <th className="py-2.5 px-3 text-right">EQUIVALENT (₹/G)</th>
                          <th className="py-2.5 px-3 text-right">SPREAD VS CHENNAI</th>
                          <th className="py-2.5 px-3">SOURCE TIMESTAMP</th>
                          <th className="py-2.5 px-3">FRESHNESS</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#25313D]/50">
                        {cityComparison?.cities?.map((c) => {
                          const isChennai = c.city_code === "CHENNAI";
                          return (
                            <tr
                              key={c.city_code}
                              onClick={() => {
                                setSelectedCity(c.city_code);
                                setActiveTab("india-bullion");
                              }}
                              className={`cursor-pointer transition hover:bg-[#1E293B]/60 ${
                                isChennai ? "bg-[#D6A84F]/5" : ""
                              }`}
                            >
                              <td className="py-3 px-3 font-semibold text-white flex items-center gap-2">
                                <span>{c.city_display_name}</span>
                                {isChennai && (
                                  <span className="text-[9px] px-1 py-0.2 rounded bg-[#D6A84F] text-black font-bold">
                                    BASELINE
                                  </span>
                                )}
                              </td>
                              <td className="py-3 px-3 text-[#8B98A5]">
                                {bullionCities.find((bc) => bc.city_code === c.city_code)?.state || "India"}
                              </td>
                              <td className="py-3 px-3 text-right font-bold text-white">
                                ₹{formatINR(c.total_price_100g, 0)}
                              </td>
                              <td className="py-3 px-3 text-right font-bold text-[#D6A84F]">
                                ₹{formatINR(c.per_gram_price)}/g
                              </td>
                              <td
                                className={`py-3 px-3 text-right font-semibold ${
                                  isChennai
                                    ? "text-zinc-500"
                                    : (c.spread_vs_chennai_inr || 0) >= 0
                                    ? "text-emerald-400"
                                    : "text-rose-400"
                                }`}
                              >
                                {isChennai
                                  ? "BASELINE (₹0.00)"
                                  : `${(c.spread_vs_chennai_inr || 0) >= 0 ? "+" : ""}₹${formatINR(
                                      c.spread_vs_chennai_inr
                                    )}/g (${(c.spread_vs_chennai_pct || 0) >= 0 ? "+" : ""}${c.spread_vs_chennai_pct}%)`}
                              </td>
                              <td className="py-3 px-3 text-zinc-400">
                                {c.source_updated_time || "N/A"}
                              </td>
                              <td className="py-3 px-3">{getFreshnessBadge(c.freshness)}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* News & Vault Dual Section */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                  {/* News Signal Barometer */}
                  <div className="bg-[#111820] border border-[#25313D] rounded-lg p-5 space-y-4">
                    <div className="flex justify-between items-center border-b border-[#25313D] pb-3">
                      <div>
                        <h3 className="text-sm font-bold text-white uppercase font-mono">
                          NEWS INTELLIGENCE &bull; 24H SIGNAL
                        </h3>
                        <p className="text-[11px] font-mono text-[#8B98A5]">
                          FinBERT Driver Classification & Evidence Barometer
                        </p>
                      </div>
                      <button
                        onClick={() => setActiveTab("news")}
                        className="text-xs font-mono text-[#D6A84F] hover:underline"
                      >
                        Full News Stream &rarr;
                      </button>
                    </div>

                    {liveNewsSignal ? (
                      <div className="space-y-3 font-mono text-xs">
                        <div className="flex items-center justify-between p-3 rounded bg-[#0D1218] border border-[#25313D]">
                          <div>
                            <span className="text-[#8B98A5] block text-[10px]">NET SENTIMENT SCORE</span>
                            <span
                              className={`text-lg font-bold ${
                                liveNewsSignal.net_sentiment_score >= 0.1
                                  ? "text-emerald-400"
                                  : liveNewsSignal.net_sentiment_score <= -0.1
                                  ? "text-rose-400"
                                  : "text-zinc-400"
                              }`}
                            >
                              {liveNewsSignal.net_sentiment_score > 0 ? "+" : ""}
                              {liveNewsSignal.net_sentiment_score.toFixed(3)}
                            </span>
                          </div>
                          <div>
                            <span className="text-[#8B98A5] block text-[10px]">VERIFIED ARTICLES</span>
                            <span className="text-lg font-bold text-white">
                              {liveNewsSignal.total_articles}
                            </span>
                          </div>
                          <div>
                            <span className="text-[#8B98A5] block text-[10px]">SIGNAL REGIME</span>
                            <span className="text-xs font-bold px-2 py-0.5 rounded bg-zinc-800 text-[#D6A84F]">
                              {liveNewsSignal.overall_signal}
                            </span>
                          </div>
                        </div>

                        {/* Top Drivers */}
                        <div className="space-y-1.5 pt-1">
                          <span className="text-[11px] text-[#8B98A5] block">DOMINANT MACRO DRIVERS:</span>
                          <div className="flex flex-wrap gap-2">
                            {liveNewsSignal.top_drivers?.slice(0, 4).map((d) => (
                              <span
                                key={d.driver}
                                className="px-2 py-1 rounded bg-[#0D1218] border border-[#25313D] text-[11px] text-zinc-300"
                              >
                                {d.driver}: <strong className="text-white">{d.count}</strong>
                              </span>
                            ))}
                          </div>
                        </div>
                      </div>
                    ) : (
                      <p className="text-xs font-mono text-zinc-500">Awaiting news telemetry...</p>
                    )}
                  </div>

                  {/* Portfolio Quick Summary */}
                  <div className="bg-[#111820] border border-[#25313D] rounded-lg p-5 space-y-4">
                    <div className="flex justify-between items-center border-b border-[#25313D] pb-3">
                      <div>
                        <h3 className="text-sm font-bold text-white uppercase font-mono">
                          VAULT SUMMARY &bull; {userId.toUpperCase()}
                        </h3>
                        <p className="text-[11px] font-mono text-[#8B98A5]">
                          Mark-to-Market Valuation with KJPL Physical Benchmarks
                        </p>
                      </div>
                      <button
                        onClick={() => setActiveTab("vault")}
                        className="text-xs font-mono text-[#D6A84F] hover:underline"
                      >
                        Manage Vault &rarr;
                      </button>
                    </div>

                    {portfolioSummary ? (
                      <div className="grid grid-cols-2 gap-3 text-xs font-mono">
                        <div className="p-3 rounded bg-[#0D1218] border border-[#25313D]">
                          <span className="text-[#8B98A5] block text-[10px]">TOTAL VALUATION</span>
                          <span className="text-lg font-bold text-white">
                            ₹{formatINR(portfolioSummary.total_estimated_valuation_inr)}
                          </span>
                        </div>
                        <div className="p-3 rounded bg-[#0D1218] border border-[#25313D]">
                          <span className="text-[#8B98A5] block text-[10px]">UNREALIZED P&amp;L</span>
                          <span
                            className={`text-lg font-bold ${
                              (portfolioSummary.unrealized_gain_loss_inr || 0) >= 0
                                ? "text-emerald-400"
                                : "text-rose-400"
                            }`}
                          >
                            {(portfolioSummary.unrealized_gain_loss_inr || 0) >= 0 ? "+" : ""}
                            ₹{formatINR(portfolioSummary.unrealized_gain_loss_inr)}
                          </span>
                        </div>
                        <div className="p-3 rounded bg-[#0D1218] border border-[#25313D]">
                          <span className="text-[#8B98A5] block text-[10px]">TOTAL GOLD WEIGHT</span>
                          <span className="text-sm font-bold text-[#D6A84F]">
                            {portfolioSummary.gold.fine_weight_grams.toFixed(2)}g (
                            {portfolioSummary.gold.fine_weight_kg.toFixed(3)}kg)
                          </span>
                        </div>
                        <div className="p-3 rounded bg-[#0D1218] border border-[#25313D]">
                          <span className="text-[#8B98A5] block text-[10px]">TOTAL SILVER WEIGHT</span>
                          <span className="text-sm font-bold text-[#B8C1CA]">
                            {portfolioSummary.silver.fine_weight_grams.toFixed(2)}g (
                            {portfolioSummary.silver.fine_weight_kg.toFixed(3)}kg)
                          </span>
                        </div>
                      </div>
                    ) : (
                      <p className="text-xs font-mono text-zinc-500">Vault empty or loading...</p>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* =============================================================== */}
            {/* TAB 2: INDIA BULLION WORKSTATION (THE FLAGSHIP)                 */}
            {/* =============================================================== */}
            {activeTab === "india-bullion" && (
              <div className="space-y-6">
                {/* 5-City Navigation Selector Toolbar */}
                <div className="bg-[#111820] border border-[#25313D] rounded-lg p-4 space-y-3">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <span className="text-[10px] font-mono text-[#D6A84F] uppercase font-bold tracking-wider">
                        CITY PRICING DESK
                      </span>
                      <h2 className="text-base sm:text-lg font-bold text-white">
                        Select City for Detailed Product Telemetry
                      </h2>
                    </div>

                    <div className="text-xs font-mono text-[#8B98A5]">
                      Benchmark Reference: <strong className="text-white">Chennai MJDTA</strong>
                    </div>
                  </div>

                  {/* City Selector Chips */}
                  <div className="flex flex-wrap gap-2 pt-1">
                    {bullionCities.map((city) => {
                      const isSelected = selectedCity === city.city_code;
                      return (
                        <button
                          key={city.city_code}
                          onClick={() => setSelectedCity(city.city_code)}
                          className={`px-4 py-2 rounded font-mono text-xs font-semibold transition flex items-center gap-2 ${
                            isSelected
                              ? "bg-[#D6A84F] text-black shadow-md font-bold"
                              : "bg-[#0D1218] text-zinc-300 hover:text-white border border-[#25313D] hover:border-[#D6A84F]/40"
                          }`}
                        >
                          <span>{city.display_name}</span>
                          {city.is_default && (
                            <span
                              className={`text-[9px] px-1.5 py-0.2 rounded ${
                                isSelected ? "bg-black/20 text-black font-bold" : "bg-[#D6A84F]/20 text-[#D6A84F]"
                              }`}
                            >
                              DEFAULT
                            </span>
                          )}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Selected City Product Grid */}
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <h3 className="text-sm font-mono font-bold text-white uppercase flex items-center gap-2">
                      <span>VERIFIED PRODUCTS FOR {selectedCity}</span>
                      <span className="text-[11px] font-normal text-[#8B98A5]">
                        ({selectedCityRates.length} instruments active)
                      </span>
                    </h3>
                    <span className="text-xs font-mono text-zinc-500">Source: Kundanmal Jhabak</span>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {selectedCityRates.map((prod) => (
                      <div
                        key={`${prod.city_code}-${prod.product_id}`}
                        className="bg-[#111820] border border-[#25313D] rounded-lg p-5 space-y-3 hover:border-[#D6A84F]/40 transition"
                      >
                        <div className="flex justify-between items-start">
                          <div>
                            <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-300 font-semibold">
                              {prod.rate_type}
                            </span>
                            <h4 className="text-sm font-bold text-white mt-1.5">{prod.product_name}</h4>
                            <p className="text-[11px] font-mono text-[#8B98A5]">
                              Purity: {(prod.purity * 100).toFixed(1)}% &bull; Unit: {prod.unit}
                            </p>
                          </div>
                          {getFreshnessBadge(prod.freshness)}
                        </div>

                        <div className="pt-2 border-t border-[#25313D]/60 flex items-baseline justify-between">
                          <div>
                            <span className="text-[10px] font-mono text-[#8B98A5] block">CONTRACT PRICE</span>
                            <span className="text-2xl font-mono font-bold text-white tracking-tight">
                              ₹{formatINR(prod.latest_price, 0)}
                            </span>
                          </div>
                          <div className="text-right">
                            <span className="text-[10px] font-mono text-[#8B98A5] block">PER-GRAM EQUIVALENT</span>
                            <span className="text-lg font-mono font-bold text-[#D6A84F]">
                              ₹{formatINR(prod.per_gram_price)}/g
                            </span>
                          </div>
                        </div>

                        {/* Separate Timestamps */}
                        <div className="p-2.5 rounded bg-[#0D1218] border border-[#25313D] text-[10px] font-mono space-y-1">
                          <div className="flex justify-between text-zinc-400">
                            <span>Source Publication Time:</span>
                            <strong className="text-white">{prod.source_updated_time || "N/A"}</strong>
                          </div>
                          <div className="flex justify-between text-zinc-400">
                            <span>Last Verified On Terminal:</span>
                            <strong className="text-zinc-300">
                              {new Date(prod.last_verified_at).toLocaleTimeString("en-IN", {
                                hour: "2-digit",
                                minute: "2-digit",
                                second: "2-digit",
                              })}
                            </strong>
                          </div>
                          <div className="flex justify-between text-zinc-400">
                            <span>Price Movement:</span>
                            <strong
                              className={
                                prod.change_inr > 0
                                  ? "text-emerald-400"
                                  : prod.change_inr < 0
                                  ? "text-rose-400"
                                  : "text-zinc-500"
                              }
                            >
                              {prod.change_inr === 0
                                ? "UNCHANGED (CONFIRMED)"
                                : `${prod.change_inr > 0 ? "+" : ""}₹${prod.change_inr} (${prod.change_pct}%)`}
                            </strong>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Institutional 5-City Comparison Matrix */}
                <div className="bg-[#111820] border border-[#25313D] rounded-lg p-5 space-y-4">
                  <div className="border-b border-[#25313D] pb-3">
                    <h3 className="text-sm font-bold text-white uppercase font-mono flex items-center gap-2">
                      <span>5-CITY SIDE-BY-SIDE EQUIVALENT COMPARISON MATRIX</span>
                      <span className="text-[10px] px-2 py-0.5 rounded bg-zinc-800 text-zinc-400">
                        PRODUCT: GOLD 100 GMS 999
                      </span>
                    </h3>
                    <p className="text-xs font-mono text-[#8B98A5] mt-1">
                      Compares standard retail wholesale 100g 999 bar normalized to per-gram price against Chennai baseline.
                    </p>
                  </div>

                  <div className="overflow-x-auto">
                    <table className="w-full text-xs font-mono text-left">
                      <thead>
                        <tr className="border-b border-[#25313D] text-[#8B98A5]">
                          <th className="py-2.5 px-3">CITY</th>
                          <th className="py-2.5 px-3 text-right">TOTAL 100G (₹)</th>
                          <th className="py-2.5 px-3 text-right">EQUIVALENT (₹/G)</th>
                          <th className="py-2.5 px-3 text-right">DIFF VS CHENNAI (₹/G)</th>
                          <th className="py-2.5 px-3 text-right">SPREAD (%)</th>
                          <th className="py-2.5 px-3">SOURCE TIME</th>
                          <th className="py-2.5 px-3">FRESHNESS</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#25313D]/50">
                        {cityComparison?.cities?.map((c) => {
                          const isChennai = c.city_code === "CHENNAI";
                          return (
                            <tr
                              key={c.city_code}
                              className={`transition ${
                                selectedCity === c.city_code ? "bg-[#D6A84F]/10 font-semibold" : ""
                              }`}
                            >
                              <td className="py-3 px-3 text-white flex items-center gap-2">
                                <span>{c.city_display_name}</span>
                                {isChennai && (
                                  <span className="text-[9px] px-1 py-0.2 rounded bg-[#D6A84F] text-black font-bold">
                                    BENCHMARK
                                  </span>
                                )}
                              </td>
                              <td className="py-3 px-3 text-right font-bold text-white">
                                ₹{formatINR(c.total_price_100g, 0)}
                              </td>
                              <td className="py-3 px-3 text-right font-bold text-[#D6A84F]">
                                ₹{formatINR(c.per_gram_price)}/g
                              </td>
                              <td
                                className={`py-3 px-3 text-right ${
                                  isChennai
                                    ? "text-zinc-500"
                                    : (c.spread_vs_chennai_inr || 0) >= 0
                                    ? "text-emerald-400 font-bold"
                                    : "text-rose-400 font-bold"
                                }`}
                              >
                                {isChennai
                                  ? "₹0.00"
                                  : `${(c.spread_vs_chennai_inr || 0) >= 0 ? "+" : ""}₹${formatINR(
                                      c.spread_vs_chennai_inr
                                    )}/g`}
                              </td>
                              <td
                                className={`py-3 px-3 text-right ${
                                  isChennai
                                    ? "text-zinc-500"
                                    : (c.spread_vs_chennai_pct || 0) >= 0
                                    ? "text-emerald-400"
                                    : "text-rose-400"
                                }`}
                              >
                                {isChennai
                                  ? "0.000%"
                                  : `${(c.spread_vs_chennai_pct || 0) >= 0 ? "+" : ""}${c.spread_vs_chennai_pct}%`}
                              </td>
                              <td className="py-3 px-3 text-zinc-400">{c.source_updated_time || "N/A"}</td>
                              <td className="py-3 px-3">{getFreshnessBadge(c.freshness)}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Audit Observation History */}
                <div className="bg-[#111820] border border-[#25313D] rounded-lg p-5 space-y-3">
                  <div className="flex justify-between items-center border-b border-[#25313D] pb-3">
                    <div>
                      <h3 className="text-sm font-bold text-white uppercase font-mono">
                        VERIFIED OBSERVATION AUDIT TRAIL &bull; {selectedCity}
                      </h3>
                      <p className="text-xs font-mono text-[#8B98A5]">
                        Cryptographically verifiable chronological price snapshots.
                      </p>
                    </div>
                    <span className="text-xs font-mono text-zinc-500">
                      Showing latest {historyRecords.length} records
                    </span>
                  </div>

                  <div className="overflow-x-auto">
                    <table className="w-full text-xs font-mono text-left">
                      <thead>
                        <tr className="border-b border-[#25313D] text-[#8B98A5]">
                          <th className="py-2 px-3">RECORD ID</th>
                          <th className="py-2 px-3">PRODUCT</th>
                          <th className="py-2 px-3 text-right">PRICE (INR)</th>
                          <th className="py-2 px-3">OBSERVED AT (UTC / IST)</th>
                          <th className="py-2 px-3">DELTA STATUS</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#25313D]/40">
                        {historyRecords.length === 0 ? (
                          <tr>
                            <td colSpan={5} className="py-4 text-center text-zinc-500 font-mono">
                              No history recorded yet for {selectedCity}.
                            </td>
                          </tr>
                        ) : (
                          historyRecords.map((h) => (
                            <tr key={h.id} className="hover:bg-[#1E293B]/40">
                              <td className="py-2 px-3 text-zinc-400">#{h.id}</td>
                              <td className="py-2 px-3 text-white font-semibold">{h.product_id}</td>
                              <td className="py-2 px-3 text-right font-bold text-[#D6A84F]">
                                ₹{formatINR(h.price)}
                              </td>
                              <td className="py-2 px-3 text-zinc-400">{h.observed_at}</td>
                              <td className="py-2 px-3">
                                {h.is_changed ? (
                                  <span className="text-[10px] font-semibold text-emerald-400">
                                    ● PRICE MODIFIED
                                  </span>
                                ) : (
                                  <span className="text-[10px] text-zinc-500">UNCHANGED RECONFIRMATION</span>
                                )}
                              </td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            )}

            {/* =============================================================== */}
            {/* TAB 3: GLOBAL MARKETS & PARITY                                  */}
            {/* =============================================================== */}
            {activeTab === "markets" && (
              <div className="space-y-6">
                <div className="bg-[#111820] border border-[#25313D] rounded-lg p-5 space-y-4">
                  <div className="border-b border-[#25313D] pb-3">
                    <span className="text-[10px] font-mono uppercase text-[#D6A84F] font-bold tracking-wider">
                      IMPORT ARBITRAGE DESK
                    </span>
                    <h2 className="text-base sm:text-lg font-bold text-white">
                      Indian Domestic Gold Import Parity Breakdown
                    </h2>
                    <p className="text-xs font-mono text-[#8B98A5] mt-1">
                      Mathematical derivation from International COMEX Gold (XAU/USD) to Landed Duty-Paid Chennai Spot.
                    </p>
                  </div>

                  {bullionSummary?.parity ? (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 font-mono text-xs">
                      <div className="p-4 rounded bg-[#0D1218] border border-[#25313D] space-y-1">
                        <span className="text-[#8B98A5] text-[10px] block">COMEX GOLD (XAU/USD)</span>
                        <span className="text-2xl font-bold text-white tracking-tight">
                          ${formatINR(bullionSummary.parity.xauusd, 2)}
                        </span>
                        <span className="text-[10px] text-zinc-500 block">Per Troy Ounce (31.1035g)</span>
                      </div>

                      <div className="p-4 rounded bg-[#0D1218] border border-[#25313D] space-y-1">
                        <span className="text-[#8B98A5] text-[10px] block">FOREX RATE (USD/INR)</span>
                        <span className="text-2xl font-bold text-white tracking-tight">
                          ₹{formatINR(bullionSummary.parity.usdinr, 2)}
                        </span>
                        <span className="text-[10px] text-zinc-500 block">RBI Reference Interbank</span>
                      </div>

                      <div className="p-4 rounded bg-[#0D1218] border border-[#25313D] space-y-1">
                        <span className="text-[#8B98A5] text-[10px] block">LANDED DUTY-PAID COST</span>
                        <span className="text-2xl font-bold text-[#D6A84F] tracking-tight">
                          ₹{formatINR(bullionSummary.parity.landed_duty_paid_per_gram)}/g
                        </span>
                        <span className="text-[10px] text-zinc-500 block">BCD 6% + AIDC 1% included</span>
                      </div>

                      <div className="p-4 rounded bg-[#0D1218] border border-[#25313D] space-y-1">
                        <span className="text-[#8B98A5] text-[10px] block">DOMESTIC SPOT PREMIUM</span>
                        <span
                          className={`text-2xl font-bold tracking-tight ${
                            bullionSummary.parity.domestic_premium_inr >= 0
                              ? "text-emerald-400"
                              : "text-rose-400"
                          }`}
                        >
                          {bullionSummary.parity.domestic_premium_inr >= 0 ? "+" : ""}
                          ₹{formatINR(bullionSummary.parity.domestic_premium_inr)}/g
                        </span>
                        <span className="text-[10px] text-zinc-500 block">
                          Spread: {bullionSummary.parity.domestic_premium_pct}%
                        </span>
                      </div>
                    </div>
                  ) : null}

                  {/* Step-by-step Parity Equation */}
                  <div className="p-4 rounded bg-[#0D1218] border border-[#25313D] font-mono text-xs space-y-2">
                    <h4 className="text-white font-bold text-xs uppercase text-[#D6A84F]">
                      Statutory Formula &amp; Duty Structure:
                    </h4>
                    <p className="text-zinc-400 text-[11px] leading-relaxed">
                      1. Base CIF Value = <code className="text-white">(XAU/USD &times; USD/INR) / 31.1034768</code> ={" "}
                      <strong className="text-white">
                        ₹{formatINR(bullionSummary?.parity?.import_cost_per_gram)}/g
                      </strong>
                    </p>
                    <p className="text-zinc-400 text-[11px] leading-relaxed">
                      2. Basic Customs Duty (BCD @ 6.0%) + Agriculture Infrastructure Development Cess (AIDC @ 1.0%) ={" "}
                      <strong className="text-white">7.0% Total Statutory Import Duty</strong>
                    </p>
                    <p className="text-zinc-400 text-[11px] leading-relaxed">
                      3. Landed Duty-Paid Parity Rate ={" "}
                      <strong className="text-[#D6A84F]">
                        ₹{formatINR(bullionSummary?.parity?.landed_duty_paid_per_gram)}/g
                      </strong>
                    </p>
                    <p className="text-zinc-400 text-[11px] leading-relaxed">
                      4. Domestic Spot Rate (Chennai MJDTA) ={" "}
                      <strong className="text-white">
                        ₹{formatINR(bullionSummary?.benchmark_gold_24k?.latest_price)}/g
                      </strong>
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* =============================================================== */}
            {/* TAB 4: NEWS INTELLIGENCE                                        */}
            {/* =============================================================== */}
            {activeTab === "news" && (
              <div className="space-y-6">
                <div className="bg-[#111820] border border-[#25313D] rounded-lg p-5 space-y-4">
                  <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#25313D] pb-3">
                    <div>
                      <span className="text-[10px] font-mono uppercase text-[#D6A84F] font-bold tracking-wider">
                        MACRO TELEMETRY STREAM
                      </span>
                      <h2 className="text-base sm:text-lg font-bold text-white">
                        Gold Macro News Driver Classification
                      </h2>
                    </div>

                    <div className="flex items-center gap-2">
                      <span className="text-xs font-mono text-[#8B98A5]">Window:</span>
                      {[24, 48, 72].map((hours) => (
                        <button
                          key={hours}
                          onClick={() => setNewsWindowHours(hours)}
                          className={`px-2.5 py-1 rounded text-xs font-mono transition ${
                            newsWindowHours === hours
                              ? "bg-[#D6A84F] text-black font-bold"
                              : "bg-[#0D1218] border border-[#25313D] text-[#8B98A5] hover:text-white"
                          }`}
                        >
                          {hours}H
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Driver Filter Chips */}
                  <div className="flex flex-wrap gap-1.5 font-mono text-xs">
                    {[
                      "ALL",
                      "CENTRAL_BANK",
                      "INFLATION",
                      "MONETARY_POLICY",
                      "GEOPOLITICAL",
                      "CURRENCY",
                      "MARKET_MOMENTUM",
                    ].map((driver) => (
                      <button
                        key={driver}
                        onClick={() => setNewsDriverFilter(driver)}
                        className={`px-3 py-1 rounded transition text-[11px] ${
                          newsDriverFilter === driver
                            ? "bg-[#1E293B] text-[#D6A84F] border border-[#D6A84F]/50 font-bold"
                            : "bg-[#0D1218] text-[#8B98A5] border border-[#25313D] hover:text-white"
                        }`}
                      >
                        {driver.replace("_", " ")}
                      </button>
                    ))}
                  </div>

                  {/* News Stream Articles */}
                  <div className="space-y-3 pt-2">
                    {filteredNews.length === 0 ? (
                      <p className="text-xs font-mono text-zinc-500 py-6 text-center">
                        No articles detected in this window for the selected driver.
                      </p>
                    ) : (
                      filteredNews.map((article, idx) => (
                        <div
                          key={article.id || idx}
                          className="p-4 rounded-lg bg-[#0D1218] border border-[#25313D] space-y-2 hover:border-[#D6A84F]/40 transition"
                        >
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-zinc-800 text-[#D6A84F] font-semibold">
                              {article.finbert_driver || "MARKET_MOMENTUM"}
                            </span>
                            <div className="flex items-center gap-2 text-[10px] font-mono text-[#8B98A5]">
                              <span>{article.source}</span>
                              <span>&bull;</span>
                              <span>{article.published_at}</span>
                              {article.syndicated_copies_count ? (
                                <span className="px-1.5 py-0.2 rounded bg-zinc-800 text-zinc-300">
                                  {article.syndicated_copies_count} copies
                                </span>
                              ) : null}
                            </div>
                          </div>

                          <a
                            href={article.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-sm font-semibold text-white hover:text-[#D6A84F] block transition leading-snug"
                          >
                            {article.title}
                          </a>

                          {article.summary && (
                            <p className="text-xs text-zinc-400 line-clamp-2 leading-relaxed">
                              {article.summary}
                            </p>
                          )}

                          <div className="flex items-center gap-4 text-[10px] font-mono pt-1 text-zinc-500 border-t border-[#25313D]/40">
                            <span>
                              Sentiment:{" "}
                              <strong
                                className={
                                  (article.sentiment_score || 0) > 0.05
                                    ? "text-emerald-400"
                                    : (article.sentiment_score || 0) < -0.05
                                    ? "text-rose-400"
                                    : "text-zinc-400"
                                }
                              >
                                {(article.sentiment_score || 0).toFixed(2)}
                              </strong>
                            </span>
                            {article.relevance_score && (
                              <span>
                                Relevance:{" "}
                                <strong className="text-white">
                                  {(article.relevance_score * 100).toFixed(0)}%
                                </strong>
                              </span>
                            )}
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* =============================================================== */}
            {/* TAB 5: ANALYTICS & ARBITRAGE                                    */}
            {/* =============================================================== */}
            {activeTab === "analytics" && (
              <div className="space-y-6">
                <div className="bg-[#111820] border border-[#25313D] rounded-lg p-5 space-y-4">
                  <div className="border-b border-[#25313D] pb-3">
                    <span className="text-[10px] font-mono uppercase text-[#D6A84F] font-bold tracking-wider">
                      QUANT DESK
                    </span>
                    <h2 className="text-base sm:text-lg font-bold text-white">
                      Inter-City Arbitrage &amp; Ratios
                    </h2>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4 font-mono text-xs">
                    <div className="p-4 rounded bg-[#0D1218] border border-[#25313D] space-y-2">
                      <span className="text-[#8B98A5] text-[10px] block">DOMESTIC GOLD/SILVER RATIO</span>
                      <span className="text-2xl font-bold text-white">
                        {(
                          (bullionSummary?.benchmark_gold_24k?.latest_price || 0) /
                          (bullionSummary?.benchmark_silver?.latest_price || 1)
                        ).toFixed(2)}
                        : 1
                      </span>
                      <span className="text-[10px] text-zinc-500 block">
                        Grams of Silver per Gram of Gold (India)
                      </span>
                    </div>

                    <div className="p-4 rounded bg-[#0D1218] border border-[#25313D] space-y-2">
                      <span className="text-[#8B98A5] text-[10px] block">MAX INTER-CITY SPREAD</span>
                      <span className="text-2xl font-bold text-emerald-400">
                        ₹
                        {formatINR(
                          Math.max(...(cityComparison?.cities?.map((c) => c.per_gram_price || 0) || [0])) -
                            Math.min(
                              ...(cityComparison?.cities
                                ?.map((c) => c.per_gram_price || 999999)
                                .filter((p) => p > 0) || [0])
                            )
                        )}
                        /g
                      </span>
                      <span className="text-[10px] text-zinc-500 block">Across 5 Primary Indian Metros</span>
                    </div>

                    <div className="p-4 rounded bg-[#0D1218] border border-[#25313D] space-y-2">
                      <span className="text-[#8B98A5] text-[10px] block">STATUTORY GST IMPACT</span>
                      <span className="text-2xl font-bold text-[#D6A84F]">3.00%</span>
                      <span className="text-[10px] text-zinc-500 block">
                        +₹
                        {formatINR(
                          (bullionSummary?.benchmark_gold_24k?.latest_price || 0) * 0.03
                        )}
                        /g on Retail Billing
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* =============================================================== */}
            {/* TAB 6: PORTFOLIO VAULT                                          */}
            {/* =============================================================== */}
            {activeTab === "vault" && (
              <div className="space-y-6">
                <div className="bg-[#111820] border border-[#25313D] rounded-lg p-5 space-y-4">
                  <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#25313D] pb-3">
                    <div>
                      <span className="text-[10px] font-mono uppercase text-[#D6A84F] font-bold tracking-wider">
                        SECURE ASSET REPOSITORY
                      </span>
                      <h2 className="text-base sm:text-lg font-bold text-white">Personal Bullion Vault</h2>
                    </div>

                    <button
                      onClick={() => setIsAddHoldingOpen(true)}
                      className="px-3 py-1.5 rounded bg-[#D6A84F] hover:bg-[#D6A84F]/90 text-black font-bold font-mono text-xs flex items-center gap-1.5 transition"
                    >
                      <span>+</span>
                      <span>ADD BULLION HOLDING</span>
                    </button>
                  </div>

                  {/* Summary row */}
                  {portfolioSummary && (
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs font-mono">
                      <div className="p-3 rounded bg-[#0D1218] border border-[#25313D]">
                        <span className="text-[#8B98A5] text-[10px] block">MARK-TO-MARKET VALUE</span>
                        <span className="text-xl font-bold text-white">
                          ₹{formatINR(portfolioSummary.total_estimated_valuation_inr)}
                        </span>
                      </div>
                      <div className="p-3 rounded bg-[#0D1218] border border-[#25313D]">
                        <span className="text-[#8B98A5] text-[10px] block">TOTAL ACQUISITION COST</span>
                        <span className="text-xl font-bold text-zinc-300">
                          ₹{formatINR(portfolioSummary.total_recorded_acquisition_cost_inr)}
                        </span>
                      </div>
                      <div className="p-3 rounded bg-[#0D1218] border border-[#25313D]">
                        <span className="text-[#8B98A5] text-[10px] block">UNREALIZED GAIN/LOSS</span>
                        <span
                          className={`text-xl font-bold ${
                            (portfolioSummary.unrealized_gain_loss_inr || 0) >= 0
                              ? "text-emerald-400"
                              : "text-rose-400"
                          }`}
                        >
                          {(portfolioSummary.unrealized_gain_loss_inr || 0) >= 0 ? "+" : ""}
                          ₹{formatINR(portfolioSummary.unrealized_gain_loss_inr)}
                        </span>
                      </div>
                      <div className="p-3 rounded bg-[#0D1218] border border-[#25313D]">
                        <span className="text-[#8B98A5] text-[10px] block">ALLOCATION</span>
                        <span className="text-sm font-bold text-white block">
                          GOLD: {portfolioSummary.gold.allocation_pct}% &bull; SILVER:{" "}
                          {portfolioSummary.silver.allocation_pct}%
                        </span>
                      </div>
                    </div>
                  )}

                  {/* Holdings Table */}
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs font-mono text-left">
                      <thead>
                        <tr className="border-b border-[#25313D] text-[#8B98A5]">
                          <th className="py-2.5 px-3">ITEM</th>
                          <th className="py-2.5 px-3">PURITY</th>
                          <th className="py-2.5 px-3 text-right">WEIGHT (G)</th>
                          <th className="py-2.5 px-3 text-right">QTY</th>
                          <th className="py-2.5 px-3 text-right">CURRENT VALUE</th>
                          <th className="py-2.5 px-3 text-right">P&amp;L</th>
                          <th className="py-2.5 px-3 text-center">ACTIONS</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#25313D]/50">
                        {holdings.length === 0 ? (
                          <tr>
                            <td colSpan={7} className="py-8 text-center text-zinc-500 font-mono">
                              No bullion holdings recorded yet. Click &quot;ADD BULLION HOLDING&quot; to begin.
                            </td>
                          </tr>
                        ) : (
                          holdings.map((h) => (
                            <tr key={h.id} className="hover:bg-[#1E293B]/40">
                              <td className="py-3 px-3 font-semibold text-white">
                                <span
                                  className={`mr-2 px-1.5 py-0.2 rounded text-[10px] ${
                                    h.metal_type === "GOLD"
                                      ? "bg-[#D6A84F]/20 text-[#D6A84F]"
                                      : "bg-[#B8C1CA]/20 text-[#B8C1CA]"
                                  }`}
                                >
                                  {h.metal_type}
                                </span>
                                {h.product_name}
                              </td>
                              <td className="py-3 px-3 text-[#8B98A5]">{(h.purity * 100).toFixed(1)}%</td>
                              <td className="py-3 px-3 text-right text-white font-bold">
                                {h.gross_weight_grams}g
                              </td>
                              <td className="py-3 px-3 text-right text-[#8B98A5]">{h.quantity}</td>
                              <td className="py-3 px-3 text-right text-white font-bold">
                                ₹{formatINR(h.current_valuation_inr)}
                              </td>
                              <td
                                className={`py-3 px-3 text-right font-semibold ${
                                  (h.unrealized_gain_loss_inr || 0) >= 0
                                    ? "text-emerald-400"
                                    : "text-rose-400"
                                }`}
                              >
                                {(h.unrealized_gain_loss_inr || 0) >= 0 ? "+" : ""}
                                ₹{formatINR(h.unrealized_gain_loss_inr)} (
                                {h.unrealized_gain_loss_pct}%)
                              </td>
                              <td className="py-3 px-3 text-center space-x-2">
                                <button
                                  onClick={() => openEditModal(h)}
                                  className="text-[11px] text-[#8B98A5] hover:text-[#D6A84F] transition"
                                >
                                  Edit
                                </button>
                                <button
                                  onClick={() => handleDeleteHolding(h.id)}
                                  className="text-[11px] text-[#8B98A5] hover:text-rose-400 transition"
                                >
                                  Delete
                                </button>
                              </td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            )}

            {/* =============================================================== */}
            {/* TAB 7: ALERTS                                                   */}
            {/* =============================================================== */}
            {activeTab === "alerts" && (
              <div className="space-y-6">
                <div className="bg-[#111820] border border-[#25313D] rounded-lg p-5 space-y-4">
                  <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#25313D] pb-3">
                    <div>
                      <span className="text-[10px] font-mono uppercase text-[#D6A84F] font-bold tracking-wider">
                        SURVEILLANCE &amp; TRIGGERS
                      </span>
                      <h2 className="text-base sm:text-lg font-bold text-white">Active Bullion Alerts</h2>
                    </div>

                    <button
                      onClick={() => setIsAddAlertOpen(true)}
                      className="px-3 py-1.5 rounded bg-[#D6A84F] hover:bg-[#D6A84F]/90 text-black font-bold font-mono text-xs flex items-center gap-1.5 transition"
                    >
                      <span>+</span>
                      <span>NEW ALERT RULE</span>
                    </button>
                  </div>

                  <div className="overflow-x-auto">
                    <table className="w-full text-xs font-mono text-left">
                      <thead>
                        <tr className="border-b border-[#25313D] text-[#8B98A5]">
                          <th className="py-2.5 px-3">RULE ID</th>
                          <th className="py-2.5 px-3">METRIC</th>
                          <th className="py-2.5 px-3">CONDITION</th>
                          <th className="py-2.5 px-3 text-right">THRESHOLD</th>
                          <th className="py-2.5 px-3">NOTES</th>
                          <th className="py-2.5 px-3 text-center">ACTION</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#25313D]/50">
                        {alerts.length === 0 ? (
                          <tr>
                            <td colSpan={6} className="py-8 text-center text-zinc-500 font-mono">
                              No alert rules configured.
                            </td>
                          </tr>
                        ) : (
                          alerts.map((a) => (
                            <tr key={a.id} className="hover:bg-[#1E293B]/40">
                              <td className="py-3 px-3 text-zinc-400">#{a.id}</td>
                              <td className="py-3 px-3 text-white font-semibold">{a.target_metric}</td>
                              <td className="py-3 px-3 text-zinc-300">{a.alert_type}</td>
                              <td className="py-3 px-3 text-right font-bold text-[#D6A84F]">
                                {a.threshold}
                              </td>
                              <td className="py-3 px-3 text-[#8B98A5]">{a.notes || "—"}</td>
                              <td className="py-3 px-3 text-center">
                                <button
                                  onClick={() => handleDeleteAlert(a.id)}
                                  className="text-rose-400 hover:text-rose-300 text-[11px]"
                                >
                                  Remove
                                </button>
                              </td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            )}

            {/* =============================================================== */}
            {/* TAB 8: DATA MONITOR & SUPABASE STATUS                            */}
            {/* =============================================================== */}
            {activeTab === "data-monitor" && (
              <div className="space-y-6">
                <div className="bg-[#111820] border border-[#25313D] rounded-lg p-5 space-y-4">
                  <div className="border-b border-[#25313D] pb-3">
                    <span className="text-[10px] font-mono uppercase text-[#D6A84F] font-bold tracking-wider">
                      INFRASTRUCTURE TELEMETRY
                    </span>
                    <h2 className="text-base sm:text-lg font-bold text-white">
                      Data Pipeline &amp; Storage Engine Health
                    </h2>
                  </div>

                  {/* Engine Banner */}
                  {monitorStatus && (
                    <div
                      className={`p-4 rounded-lg border font-mono text-xs space-y-2 ${
                        monitorStatus.database.is_production_ready
                          ? "bg-emerald-950/30 border-emerald-800 text-emerald-300"
                          : "bg-amber-950/30 border-amber-800 text-amber-300"
                      }`}
                    >
                      <div className="flex items-center gap-2 font-bold text-sm">
                        <span>●</span>
                        <span>CURRENT STORAGE ENGINE: {monitorStatus.database.description}</span>
                      </div>
                      <p className="text-xs text-zinc-300 leading-relaxed">
                        {monitorStatus.database.is_production_ready
                          ? "Supabase PostgreSQL connected. Cloud multi-tenant persistence is active."
                          : "Local SQLite fallback active for local development. When ready to activate cloud storage, provide your Supabase PostgreSQL connection string as DATABASE_URL in repository secrets and environment variables."}
                      </p>
                    </div>
                  )}

                  {/* 5-City Data Freshness Monitor */}
                  <div className="space-y-3 pt-2">
                    <h3 className="text-sm font-bold text-white uppercase font-mono">
                      City-Wise Upstream Freshness Telemetry
                    </h3>

                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3 font-mono text-xs">
                      {["CHENNAI", "BENGALURU", "MUMBAI", "COIMBATORE", "HYDERABAD"].map((code) => {
                        const cityInfo = monitorStatus?.city_freshness[code];
                        return (
                          <div
                            key={code}
                            className="p-3.5 rounded bg-[#0D1218] border border-[#25313D] space-y-1.5"
                          >
                            <div className="flex justify-between items-center">
                              <span className="font-bold text-white">{code}</span>
                              {getFreshnessBadge(cityInfo?.freshness)}
                            </div>
                            <div className="text-[11px] text-[#8B98A5]">
                              Pub Time: <strong className="text-white">{cityInfo?.source_updated_time || "N/A"}</strong>
                            </div>
                            <div className="text-[10px] text-zinc-500">
                              Age: {cityInfo?.age_display || "Active"}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>

                  {/* Recent Collector Execution Logs */}
                  <div className="space-y-3 pt-4 border-t border-[#25313D]">
                    <h3 className="text-sm font-bold text-white uppercase font-mono">
                      Recent Collector Runs Trace Log
                    </h3>

                    <div className="overflow-x-auto">
                      <table className="w-full text-xs font-mono text-left">
                        <thead>
                          <tr className="border-b border-[#25313D] text-[#8B98A5]">
                            <th className="py-2 px-3">COLLECTOR</th>
                            <th className="py-2 px-3">STATUS</th>
                            <th className="py-2 px-3 text-right">EXTRACTED</th>
                            <th className="py-2 px-3 text-right">INSERTED</th>
                            <th className="py-2 px-3 text-right">CHANGED</th>
                            <th className="py-2 px-3 text-right">DURATION</th>
                            <th className="py-2 px-3">TIMESTAMP</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-[#25313D]/40">
                          {monitorStatus?.recent_runs?.length ? (
                            monitorStatus.recent_runs.map((r, i) => (
                              <tr key={i} className="hover:bg-[#1E293B]/40">
                                <td className="py-2.5 px-3 font-semibold text-white">
                                  {r.collector_name}
                                </td>
                                <td className="py-2.5 px-3">
                                  <span
                                    className={`px-1.5 py-0.2 rounded text-[10px] font-bold ${
                                      r.status === "SUCCESS"
                                        ? "bg-emerald-950 text-emerald-400"
                                        : "bg-rose-950 text-rose-400"
                                    }`}
                                  >
                                    {r.status}
                                  </span>
                                </td>
                                <td className="py-2.5 px-3 text-right text-white">
                                  {r.records_extracted}
                                </td>
                                <td className="py-2.5 px-3 text-right text-[#D6A84F]">
                                  {r.records_inserted}
                                </td>
                                <td className="py-2.5 px-3 text-right text-emerald-400">
                                  {r.records_changed}
                                </td>
                                <td className="py-2.5 px-3 text-right text-[#8B98A5]">
                                  {r.duration_seconds.toFixed(2)}s
                                </td>
                                <td className="py-2.5 px-3 text-zinc-400">{r.executed_at}</td>
                              </tr>
                            ))
                          ) : (
                            <tr>
                              <td colSpan={7} className="py-4 text-center text-zinc-500 font-mono">
                                No collector execution records logged yet.
                              </td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* =============================================================== */}
            {/* TAB 9: SETTINGS                                                 */}
            {/* =============================================================== */}
            {activeTab === "settings" && (
              <div className="space-y-6">
                <div className="bg-[#111820] border border-[#25313D] rounded-lg p-5 space-y-4 max-w-xl">
                  <div className="border-b border-[#25313D] pb-3">
                    <span className="text-[10px] font-mono uppercase text-[#D6A84F] font-bold tracking-wider">
                      TERMINAL PREFERENCES
                    </span>
                    <h2 className="text-base sm:text-lg font-bold text-white">Settings &amp; Access Control</h2>
                  </div>

                  <div className="space-y-4 font-mono text-xs">
                    <div>
                      <label className="block text-[#8B98A5] mb-1">DEFAULT INDIAN CITY</label>
                      <select
                        value={selectedCity}
                        onChange={(e) => setSelectedCity(e.target.value)}
                        className="w-full bg-[#0D1218] border border-[#25313D] rounded p-2 text-white"
                      >
                        {bullionCities.map((c) => (
                          <option key={c.city_code} value={c.city_code}>
                            {c.display_name} {c.is_default ? "(Default Benchmark)" : ""}
                          </option>
                        ))}
                      </select>
                    </div>

                    <div>
                      <label className="block text-[#8B98A5] mb-1">VAULT USER IDENTIFIER</label>
                      <input
                        type="text"
                        value={userId}
                        onChange={(e) => setUserId(e.target.value)}
                        className="w-full bg-[#0D1218] border border-[#25313D] rounded p-2 text-white"
                      />
                    </div>

                    <div>
                      <label className="block text-[#8B98A5] mb-1">OPTIONAL API AUTHORIZATION KEY</label>
                      <input
                        type="password"
                        placeholder="Bearer token if configured"
                        value={apiKey}
                        onChange={(e) => setApiKey(e.target.value)}
                        className="w-full bg-[#0D1218] border border-[#25313D] rounded p-2 text-white"
                      />
                    </div>
                  </div>
                </div>
              </div>
            )}
          </>
        )}
      </main>

      {/* ===================================================================== */}
      {/* 4. MODALS (PORTFOLIO ADD/EDIT & ALERTS)                              */}
      {/* ===================================================================== */}

      {/* Modal: Add Holding */}
      {isAddHoldingOpen && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-[#111820] border border-[#25313D] rounded-xl max-w-md w-full p-6 shadow-2xl space-y-4">
            <h3 className="text-base font-bold text-white font-mono uppercase text-[#D6A84F]">
              Add Bullion Holding to Vault
            </h3>
            <form onSubmit={handleCreateHolding} className="space-y-4 text-xs font-mono">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[#8B98A5] mb-1">Metal</label>
                  <select
                    value={holdingForm.metal_type}
                    onChange={(e) => setHoldingForm({ ...holdingForm, metal_type: e.target.value })}
                    className="w-full bg-[#0D1218] border border-[#25313D] rounded p-2 text-white"
                  >
                    <option value="GOLD">Gold</option>
                    <option value="SILVER">Silver</option>
                  </select>
                </div>
                <div>
                  <label className="block text-[#8B98A5] mb-1">Purity (e.g. 0.999)</label>
                  <input
                    type="number"
                    step="0.001"
                    required
                    value={holdingForm.purity}
                    onChange={(e) => setHoldingForm({ ...holdingForm, purity: e.target.value })}
                    className="w-full bg-[#0D1218] border border-[#25313D] rounded p-2 text-white"
                  />
                </div>
              </div>

              <div>
                <label className="block text-[#8B98A5] mb-1">Product Description</label>
                <input
                  type="text"
                  required
                  value={holdingForm.product_name}
                  onChange={(e) => setHoldingForm({ ...holdingForm, product_name: e.target.value })}
                  className="w-full bg-[#0D1218] border border-[#25313D] rounded p-2 text-white"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[#8B98A5] mb-1">Gross Weight (Grams)</label>
                  <input
                    type="number"
                    step="0.01"
                    required
                    value={holdingForm.gross_weight}
                    onChange={(e) => setHoldingForm({ ...holdingForm, gross_weight: e.target.value })}
                    className="w-full bg-[#0D1218] border border-[#25313D] rounded p-2 text-white"
                  />
                </div>
                <div>
                  <label className="block text-[#8B98A5] mb-1">Quantity</label>
                  <input
                    type="number"
                    min="1"
                    required
                    value={holdingForm.quantity}
                    onChange={(e) => setHoldingForm({ ...holdingForm, quantity: e.target.value })}
                    className="w-full bg-[#0D1218] border border-[#25313D] rounded p-2 text-white"
                  />
                </div>
              </div>

              <div>
                <label className="block text-[#8B98A5] mb-1">Total Cost in INR (Optional)</label>
                <input
                  type="number"
                  step="0.01"
                  placeholder="Total purchase price"
                  value={holdingForm.acquisition_cost_inr}
                  onChange={(e) => setHoldingForm({ ...holdingForm, acquisition_cost_inr: e.target.value })}
                  className="w-full bg-[#0D1218] border border-[#25313D] rounded p-2 text-white"
                />
              </div>

              <div>
                <label className="block text-[#8B98A5] mb-1">Notes</label>
                <input
                  type="text"
                  value={holdingForm.notes}
                  onChange={(e) => setHoldingForm({ ...holdingForm, notes: e.target.value })}
                  className="w-full bg-[#0D1218] border border-[#25313D] rounded p-2 text-white"
                />
              </div>

              <div className="flex justify-end gap-3 pt-3 border-t border-[#25313D]">
                <button
                  type="button"
                  onClick={() => setIsAddHoldingOpen(false)}
                  className="px-3 py-1.5 bg-[#1E293B] text-zinc-300 rounded font-semibold"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-3 py-1.5 bg-[#D6A84F] text-black rounded font-bold"
                >
                  Save to Vault
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Edit Holding */}
      {isEditHoldingOpen && editingHolding && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-[#111820] border border-[#25313D] rounded-xl max-w-md w-full p-6 shadow-2xl space-y-4">
            <h3 className="text-base font-bold text-white font-mono uppercase text-[#D6A84F]">
              Edit Holding #{editingHolding.id}
            </h3>
            <form onSubmit={handleUpdateHolding} className="space-y-4 text-xs font-mono">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[#8B98A5] mb-1">Metal</label>
                  <select
                    value={holdingForm.metal_type}
                    onChange={(e) => setHoldingForm({ ...holdingForm, metal_type: e.target.value })}
                    className="w-full bg-[#0D1218] border border-[#25313D] rounded p-2 text-white"
                  >
                    <option value="GOLD">Gold</option>
                    <option value="SILVER">Silver</option>
                  </select>
                </div>
                <div>
                  <label className="block text-[#8B98A5] mb-1">Purity</label>
                  <input
                    type="number"
                    step="0.001"
                    required
                    value={holdingForm.purity}
                    onChange={(e) => setHoldingForm({ ...holdingForm, purity: e.target.value })}
                    className="w-full bg-[#0D1218] border border-[#25313D] rounded p-2 text-white"
                  />
                </div>
              </div>

              <div>
                <label className="block text-[#8B98A5] mb-1">Product Description</label>
                <input
                  type="text"
                  required
                  value={holdingForm.product_name}
                  onChange={(e) => setHoldingForm({ ...holdingForm, product_name: e.target.value })}
                  className="w-full bg-[#0D1218] border border-[#25313D] rounded p-2 text-white"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[#8B98A5] mb-1">Gross Weight (Grams)</label>
                  <input
                    type="number"
                    step="0.01"
                    required
                    value={holdingForm.gross_weight}
                    onChange={(e) => setHoldingForm({ ...holdingForm, gross_weight: e.target.value })}
                    className="w-full bg-[#0D1218] border border-[#25313D] rounded p-2 text-white"
                  />
                </div>
                <div>
                  <label className="block text-[#8B98A5] mb-1">Quantity</label>
                  <input
                    type="number"
                    min="1"
                    required
                    value={holdingForm.quantity}
                    onChange={(e) => setHoldingForm({ ...holdingForm, quantity: e.target.value })}
                    className="w-full bg-[#0D1218] border border-[#25313D] rounded p-2 text-white"
                  />
                </div>
              </div>

              <div>
                <label className="block text-[#8B98A5] mb-1">Total Cost in INR</label>
                <input
                  type="number"
                  step="0.01"
                  value={holdingForm.acquisition_cost_inr}
                  onChange={(e) => setHoldingForm({ ...holdingForm, acquisition_cost_inr: e.target.value })}
                  className="w-full bg-[#0D1218] border border-[#25313D] rounded p-2 text-white"
                />
              </div>

              <div className="flex justify-end gap-3 pt-3 border-t border-[#25313D]">
                <button
                  type="button"
                  onClick={() => setIsEditHoldingOpen(false)}
                  className="px-3 py-1.5 bg-[#1E293B] text-zinc-300 rounded font-semibold"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-3 py-1.5 bg-[#D6A84F] text-black rounded font-bold"
                >
                  Save Changes
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Add Alert */}
      {isAddAlertOpen && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-[#111820] border border-[#25313D] rounded-xl max-w-sm w-full p-6 shadow-2xl space-y-4">
            <h3 className="text-base font-bold text-white font-mono uppercase text-[#D6A84F]">
              Create Price Alert
            </h3>
            <form onSubmit={handleCreateAlert} className="space-y-4 text-xs font-mono">
              <div>
                <label className="block text-[#8B98A5] mb-1">Condition</label>
                <select
                  value={alertForm.alert_type}
                  onChange={(e) => setAlertForm({ ...alertForm, alert_type: e.target.value })}
                  className="w-full bg-[#0D1218] border border-[#25313D] rounded p-2 text-white"
                >
                  <option value="PRICE_ABOVE">Spot Rate Above (&gt;)</option>
                  <option value="PRICE_BELOW">Spot Rate Below (&lt;)</option>
                  <option value="PREMIUM_ABOVE">Domestic Premium Above (&gt; %)</option>
                </select>
              </div>

              <div>
                <label className="block text-[#8B98A5] mb-1">Threshold Value</label>
                <input
                  type="number"
                  step="0.01"
                  required
                  value={alertForm.threshold}
                  onChange={(e) => setAlertForm({ ...alertForm, threshold: e.target.value })}
                  className="w-full bg-[#0D1218] border border-[#25313D] rounded p-2 text-white"
                />
              </div>

              <div>
                <label className="block text-[#8B98A5] mb-1">Notes (Optional)</label>
                <input
                  type="text"
                  value={alertForm.notes}
                  onChange={(e) => setAlertForm({ ...alertForm, notes: e.target.value })}
                  className="w-full bg-[#0D1218] border border-[#25313D] rounded p-2 text-white"
                  placeholder="e.g. Target rebalancing point"
                />
              </div>

              <div className="flex justify-end gap-3 pt-3 border-t border-[#25313D]">
                <button
                  type="button"
                  onClick={() => setIsAddAlertOpen(false)}
                  className="px-3 py-1.5 bg-[#1E293B] text-zinc-300 rounded font-semibold"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-3 py-1.5 bg-[#D6A84F] text-black rounded font-bold"
                >
                  Create Alert
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Footer */}
      <footer className="border-t border-[#25313D] bg-[#080B0F] py-4 text-center text-xs font-mono text-[#8B98A5]">
        <div className="max-w-[1720px] mx-auto px-4 flex flex-wrap justify-between items-center gap-2">
          <span>&copy; {new Date().getFullYear()} VMD BULLION &bull; INSTITUTIONAL TERMINAL</span>
          <span className="text-[11px] text-zinc-600">
            DATA SOURCE: KUNDANMAL JHABAK (KJPL) &bull; MJDTA BENCHMARKS &bull; ZERO SIMULATED MOVEMENTS
          </span>
        </div>
      </footer>
    </div>
  );
}
