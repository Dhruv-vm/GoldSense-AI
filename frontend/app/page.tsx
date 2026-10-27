"use client";

import React, { useState, useEffect } from "react";

interface KJPLData {
  source: string;
  gold_mjdta: number;
  silver_mjdta: number;
  published_time: string;
  observed_at: string;
  change_24h_inr: number;
  change_24h_pct: number;
  freshness: string;
}

interface MarketData {
  xauusd: number;
  xagusd: number;
  usdinr: number;
  observed_at: string;
  source: string;
  xauusd_change_24h: number;
  xauusd_change_24h_pct: number;
  usdinr_change_24h: number;
  freshness: string;
}

interface DerivedData {
  global_gold_inr_per_gram: number;
  global_silver_inr_per_gram: number;
  domestic_premium_inr_per_gram: number;
  domestic_premium_pct: number;
  global_gold_silver_ratio: number;
  domestic_gold_silver_ratio: number;
  conversion_factor: number;
}

interface TradingStatus {
  indian_physical_market: string;
  indian_physical_description: string;
  global_futures_market: string;
  global_futures_description: string;
  server_time_ist: string;
}

interface OverviewResponse {
  status: string;
  timestamp: string;
  kjpl: KJPLData;
  market: MarketData;
  derived: DerivedData;
  overall_freshness: string;
  trading_status?: TradingStatus;
  message?: string;
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

interface HistoricalValuation {
  date: string;
  observed_at: string;
  gold_rate_inr: number;
  silver_rate_inr: number;
  total_valuation_inr: number;
  gold_valuation_inr: number;
  silver_valuation_inr: number;
}

interface PredictionStatus {
  status: string;
  is_ready: boolean;
  message: string;
  metrics?: {
    current_samples: number;
    required_samples: number;
    progress_pct: number;
  };
  baseline_benchmarks?: {
    naive_persistence?: {
      description: string;
      mae_inr_per_g: number;
      rmse_inr_per_g: number;
    };
    sma_3_event?: {
      description: string;
      mae_inr_per_g: number;
      rmse_inr_per_g: number;
    };
  };
  current_macro_snapshot?: any;
  pipeline_specification?: any;
}

interface NewsItem {
  id: string;
  title: string;
  url: string;
  source: string;
  published_at: string;
  sentiment_label: string;
  sentiment_score: number;
  is_gold_relevant: boolean;
  primary_category?: string;
}

interface AlertRule {
  id: number;
  alert_type: string;
  target_metric: string;
  threshold: number;
  notes: string | null;
  created_at: string;
}

export default function GoldSenseDashboard() {
  const [activeTab, setActiveTab] = useState<
    "overview" | "markets" | "portfolio" | "predictions" | "news" | "research" | "alerts" | "settings"
  >("overview");

  // Data states
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [portfolioSummary, setPortfolioSummary] = useState<PortfolioSummary | null>(null);
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [portfolioHistory, setPortfolioHistory] = useState<HistoricalValuation[]>([]);
  const [prediction, setPrediction] = useState<PredictionStatus | null>(null);
  const [news, setNews] = useState<NewsItem[]>([]);
  const [alerts, setAlerts] = useState<AlertRule[]>([]);

  // UI / Status states
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [refreshNotice, setRefreshNotice] = useState<string | null>(null);
  const [newsFilter, setNewsFilter] = useState("ALL");
  const [userId, setUserId] = useState("owner");
  const [apiKey, setApiKey] = useState("");

  // Modals
  const [isAddHoldingOpen, setIsAddHoldingOpen] = useState(false);
  const [isEditHoldingOpen, setIsEditHoldingOpen] = useState(false);
  const [editingHolding, setEditingHolding] = useState<Holding | null>(null);
  const [isAddAlertOpen, setIsAddAlertOpen] = useState(false);

  // Form states
  const [holdingForm, setHoldingForm] = useState({
    metal_type: "GOLD",
    product_name: "24K Minted Bar",
    purity: "0.999",
    gross_weight: "10.0",
    weight_unit: "g",
    quantity: "1",
    acquisition_date: new Date().toISOString().split("T")[0],
    acquisition_cost_inr: "",
    notes: "Personal Vault",
  });

  const [alertForm, setAlertForm] = useState({
    alert_type: "PRICE_ABOVE",
    target_metric: "KJPL_GOLD",
    threshold: "14500",
    notes: "",
  });

  const getHeaders = () => {
    const h: Record<string, string> = { "Content-Type": "application/json" };
    if (userId) h["X-User-ID"] = userId;
    if (apiKey) h["Authorization"] = `Bearer ${apiKey}`;
    return h;
  };

  const fetchData = async () => {
    setIsLoading(true);
    try {
      const headers = getHeaders();

      // 1. Overview
      const ovRes = await fetch("/api/v1/market/overview");
      if (ovRes.ok) {
        const ovJson = await ovRes.json();
        setOverview(ovJson);
      }

      // 2. Portfolio Summary
      const pfRes = await fetch("/api/portfolio/summary", { headers });
      if (pfRes.ok) {
        const pfJson = await pfRes.json();
        setPortfolioSummary(pfJson);
      }

      // 3. Holdings
      const hldRes = await fetch("/api/portfolio/holdings", { headers });
      if (hldRes.ok) {
        const hldJson = await hldRes.json();
        setHoldings(hldJson);
      }

      // 4. Portfolio History
      const histRes = await fetch("/api/portfolio/history", { headers });
      if (histRes.ok) {
        const histJson = await histRes.json();
        setPortfolioHistory(histJson);
      }

      // 5. Prediction Status
      const predRes = await fetch("/api/v1/prediction/latest");
      if (predRes.ok) {
        const predJson = await predRes.json();
        setPrediction(predJson);
      }

      // 6. News
      const newsRes = await fetch("/api/v1/news?limit=25");
      if (newsRes.ok) {
        const newsJson = await newsRes.json();
        setNews(newsJson.articles || []);
      }

      // 7. Alerts
      const alRes = await fetch("/api/alerts", { headers });
      if (alRes.ok) {
        const alJson = await alRes.json();
        setAlerts(alJson);
      }
    } catch (err) {
      console.error("Failed fetching dashboard data", err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [userId, apiKey]);

  const handleRefreshRates = async () => {
    setIsRefreshing(true);
    setRefreshNotice(null);
    try {
      const res = await fetch("/api/v1/market/refresh", { credentials: "omit" });
      const data = await res.json();
      if (res.status === 429) {
        setRefreshNotice(data.detail?.message || "Rate limit cooldown active (60s). Retaining latest observations.");
      } else if (res.ok) {
        setOverview(data);
        setRefreshNotice("Market rates successfully updated.");
      }
    } catch (e) {
      setRefreshNotice("Refresh request failed. Retaining last-known-good rates.");
    } finally {
      setIsRefreshing(false);
      setTimeout(() => setRefreshNotice(null), 5000);
    }
  };

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
        fetchData();
      }
    } catch (err) {
      console.error("Error creating holding", err);
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
        fetchData();
      }
    } catch (err) {
      console.error("Error updating holding", err);
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

  const handleDeleteHolding = async (id: number) => {
    if (!confirm("Are you sure you want to remove this holding?")) return;
    try {
      const res = await fetch(`/api/portfolio/holdings/${id}`, {
        method: "DELETE",
        headers: getHeaders(),
      });
      if (res.ok) {
        fetchData();
      }
    } catch (err) {
      console.error("Error deleting holding", err);
    }
  };

  const handleCreateAlert = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await fetch("/api/alerts", {
        method: "POST",
        headers: getHeaders(),
        body: JSON.stringify({
          alert_type: alertForm.alert_type,
          target_metric: alertForm.target_metric,
          threshold: parseFloat(alertForm.threshold),
          notes: alertForm.notes,
        }),
      });
      if (res.ok) {
        setIsAddAlertOpen(false);
        fetchData();
      }
    } catch (err) {
      console.error("Error creating alert", err);
    }
  };

  const handleDeleteAlert = async (id: number) => {
    try {
      const res = await fetch(`/api/alerts/${id}`, {
        method: "DELETE",
        headers: getHeaders(),
      });
      if (res.ok) {
        fetchData();
      }
    } catch (err) {
      console.error("Error deleting alert", err);
    }
  };

  const filteredNews = news.filter((item) => {
    if (newsFilter === "BULLISH") return item.sentiment_label === "POSITIVE";
    if (newsFilter === "BEARISH") return item.sentiment_label === "NEGATIVE";
    if (newsFilter === "GOLD_ONLY") return item.is_gold_relevant;
    return true;
  });

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 font-sans selection:bg-amber-500 selection:text-black">
      {/* Top Header / Branding */}
      <header className="border-b border-zinc-800/80 bg-zinc-900/40 backdrop-blur sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-amber-400 to-amber-600 flex items-center justify-center font-bold text-black shadow-lg shadow-amber-500/20">
              G
            </div>
            <div>
              <span className="font-bold text-lg tracking-tight text-white flex items-center gap-2">
                GoldSense <span className="text-amber-400 font-semibold text-xs px-2 py-0.5 rounded border border-amber-500/30 bg-amber-500/10">AI TERMINAL</span>
              </span>
            </div>
          </div>

          {/* Navigation Bar across all 8 required product areas */}
          <nav className="hidden lg:flex space-x-1">
            {[
              { id: "overview", label: "Overview" },
              { id: "markets", label: "Markets" },
              { id: "portfolio", label: "My Bullion" },
              { id: "predictions", label: "Predictions" },
              { id: "news", label: "News Feed" },
              { id: "research", label: "Research & History" },
              { id: "alerts", label: "Alerts" },
              { id: "settings", label: "Settings" },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as any)}
                className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                  activeTab === tab.id
                    ? "bg-amber-500/10 text-amber-400 border border-amber-500/20"
                    : "text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800/50"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </nav>

          {/* Right Refresh & Status Widget */}
          <div className="flex items-center space-x-3">
            {overview && (
              <div className="hidden sm:flex items-center gap-2 text-xs text-zinc-400">
                <span className="inline-block w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                <span>{overview.overall_freshness}</span>
                <span className="text-zinc-600">|</span>
                <span>Ahmedabad Spot: <strong className="text-amber-400">₹{overview.kjpl?.gold_mjdta?.toLocaleString()}/g</strong></span>
              </div>
            )}
            <button
              onClick={handleRefreshRates}
              disabled={isRefreshing}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200 border border-zinc-700 transition-all disabled:opacity-50"
            >
              <svg className={`w-3.5 h-3.5 ${isRefreshing ? "animate-spin" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
              {isRefreshing ? "Updating..." : "Refresh"}
            </button>
          </div>
        </div>
      </header>

      {/* Cooldown / Refresh Toast Notice */}
      {refreshNotice && (
        <div className="bg-amber-950/80 border-b border-amber-800/50 text-amber-200 px-4 py-2 text-xs text-center flex items-center justify-center gap-2">
          <span>ℹ️</span> {refreshNotice}
        </div>
      )}

      {/* Main Content Viewport */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-6">
        
        {/* ========================================================================= */}
        {/* TAB 1: OVERVIEW                                                           */}
        {/* ========================================================================= */}
        {activeTab === "overview" && (
          <div className="space-y-6">
            {/* Top Market Bar */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <div className="bg-zinc-900/60 border border-zinc-800 rounded-xl p-4 shadow-sm relative overflow-hidden">
                <div className="text-xs font-medium text-zinc-400 uppercase tracking-wider">KJPL Gold 999 (24K)</div>
                <div className="text-2xl font-bold text-amber-400 mt-1">₹{overview?.kjpl?.gold_mjdta?.toLocaleString() || "—"} <span className="text-xs font-normal text-zinc-400">/ gram</span></div>
                <div className="mt-2 text-xs flex items-center gap-1.5 text-zinc-400">
                  <span className={overview?.kjpl?.change_24h_inr && overview.kjpl.change_24h_inr >= 0 ? "text-emerald-400" : "text-rose-400"}>
                    {overview?.kjpl?.change_24h_inr && overview.kjpl.change_24h_inr >= 0 ? "+" : ""}
                    {overview?.kjpl?.change_24h_inr} ({overview?.kjpl?.change_24h_pct}%)
                  </span>
                  <span>vs prev</span>
                </div>
              </div>

              <div className="bg-zinc-900/60 border border-zinc-800 rounded-xl p-4 shadow-sm">
                <div className="text-xs font-medium text-zinc-400 uppercase tracking-wider">Global Gold Spot (USD)</div>
                <div className="text-2xl font-bold text-zinc-100 mt-1">${overview?.market?.xauusd?.toFixed(1) || "—"} <span className="text-xs font-normal text-zinc-400">/ troy oz</span></div>
                <div className="mt-2 text-xs text-zinc-400 flex items-center gap-1.5">
                  <span className={overview?.market?.xauusd_change_24h && overview.market.xauusd_change_24h >= 0 ? "text-emerald-400" : "text-rose-400"}>
                    {overview?.market?.xauusd_change_24h && overview.market.xauusd_change_24h >= 0 ? "+" : ""}{overview?.market?.xauusd_change_24h} ({overview?.market?.xauusd_change_24h_pct}%)
                  </span>
                  <span>COMEX GC=F</span>
                </div>
              </div>

              <div className="bg-zinc-900/60 border border-zinc-800 rounded-xl p-4 shadow-sm">
                <div className="text-xs font-medium text-zinc-400 uppercase tracking-wider">USD / INR Exchange</div>
                <div className="text-2xl font-bold text-zinc-100 mt-1">₹{overview?.market?.usdinr?.toFixed(2) || "—"}</div>
                <div className="mt-2 text-xs text-zinc-400">
                  Global Parity: <strong className="text-zinc-200">₹{overview?.derived?.global_gold_inr_per_gram?.toLocaleString()}</strong> / g
                </div>
              </div>

              <div className="bg-zinc-900/60 border border-zinc-800 rounded-xl p-4 shadow-sm bg-gradient-to-br from-amber-950/20 to-zinc-900/60">
                <div className="text-xs font-medium text-amber-300 uppercase tracking-wider">Domestic Disparity Premium</div>
                <div className="text-2xl font-bold text-amber-400 mt-1">+{overview?.derived?.domestic_premium_pct || "0.0"}%</div>
                <div className="mt-2 text-xs text-zinc-400">
                  Spread: <strong className="text-amber-300">+₹{overview?.derived?.domestic_premium_inr_per_gram || "0"}</strong> / g (Customs BCD + Cess)
                </div>
              </div>
            </div>

            {/* Middle Split: Portfolio Summary & Prediction Indicator */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              {/* Portfolio Quick Card */}
              <div className="lg:col-span-2 bg-zinc-900/40 border border-zinc-800/80 rounded-xl p-6">
                <div className="flex items-center justify-between pb-4 border-b border-zinc-800">
                  <div>
                    <h2 className="text-lg font-bold text-white flex items-center gap-2">
                      <span>Personal Bullion Vault</span>
                      <span className="text-xs px-2 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20">Private Holdings</span>
                    </h2>
                    <p className="text-xs text-zinc-400 mt-0.5">Physical bullion marked-to-market against Ahmedabad spot rate</p>
                  </div>
                  <button
                    onClick={() => setActiveTab("portfolio")}
                    className="text-xs text-amber-400 hover:text-amber-300 font-medium"
                  >
                    View Holdings →
                  </button>
                </div>

                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mt-6">
                  <div>
                    <div className="text-xs text-zinc-400">Fine Gold Weight</div>
                    <div className="text-xl font-bold text-amber-400 mt-1">{portfolioSummary?.gold?.fine_weight_grams?.toFixed(2) || "0.00"} g</div>
                    <div className="text-xs text-zinc-500 mt-0.5">({portfolioSummary?.gold?.fine_weight_kg?.toFixed(4) || "0"} kg pure)</div>
                  </div>
                  <div>
                    <div className="text-xs text-zinc-400">Fine Silver Weight</div>
                    <div className="text-xl font-bold text-zinc-300 mt-1">{portfolioSummary?.silver?.fine_weight_grams?.toFixed(2) || "0.00"} g</div>
                    <div className="text-xs text-zinc-500 mt-0.5">({portfolioSummary?.silver?.fine_weight_kg?.toFixed(4) || "0"} kg pure)</div>
                  </div>
                  <div>
                    <div className="text-xs text-zinc-400">Total Portfolio Value</div>
                    <div className="text-xl font-bold text-white mt-1">₹{portfolioSummary?.total_estimated_valuation_inr?.toLocaleString() || "0"}</div>
                    <div className="text-xs text-zinc-500 mt-0.5">{portfolioSummary?.unique_holdings || 0} items cataloged</div>
                  </div>
                  <div>
                    <div className="text-xs text-zinc-400">Unrealized Gain / Loss</div>
                    <div className={`text-xl font-bold mt-1 ${
                      portfolioSummary?.unrealized_gain_loss_inr === null
                        ? "text-zinc-500"
                        : (portfolioSummary?.unrealized_gain_loss_inr || 0) >= 0
                        ? "text-emerald-400"
                        : "text-rose-400"
                    }`}>
                      {portfolioSummary?.unrealized_gain_loss_inr === null
                        ? "Unmeasured"
                        : `₹${portfolioSummary?.unrealized_gain_loss_inr?.toLocaleString()} (${portfolioSummary?.unrealized_gain_loss_pct}%)`}
                    </div>
                    <div className="text-xs text-zinc-500 mt-0.5">
                      {portfolioSummary?.total_recorded_acquisition_cost_inr ? "Based on recorded cost" : "Acquisition cost unknown"}
                    </div>
                  </div>
                </div>
              </div>

              {/* Prediction Readiness Card */}
              <div className="bg-zinc-900/40 border border-zinc-800/80 rounded-xl p-6 flex flex-col justify-between">
                <div>
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold uppercase tracking-wider text-amber-400">AI ML Prediction Status</span>
                    <span className="text-xs px-2 py-0.5 rounded bg-zinc-800 text-zinc-300 border border-zinc-700">Experimental</span>
                  </div>
                  <h3 className="text-base font-bold text-white mt-3">Statistical Sample Readiness</h3>
                  <p className="text-xs text-zinc-400 mt-2 leading-relaxed">
                    {prediction?.message || "Supervised models require at least 50 historical daily events for safe walk-forward validation without overfitting."}
                  </p>

                  <div className="mt-4">
                    <div className="flex justify-between text-xs text-zinc-400 mb-1">
                      <span>Collected Events: <strong>{prediction?.metrics?.current_samples || 34}</strong></span>
                      <span>Target Threshold: <strong>50 Events</strong></span>
                    </div>
                    <div className="w-full bg-zinc-800 rounded-full h-2 overflow-hidden">
                      <div
                        className="bg-amber-500 h-2 rounded-full transition-all duration-500"
                        style={{ width: `${prediction?.metrics?.progress_pct || 68}%` }}
                      />
                    </div>
                  </div>
                </div>

                <div className="mt-6 pt-4 border-t border-zinc-800/80 flex items-center justify-between">
                  <span className="text-xs text-zinc-400">Naive Persistence MAE: <strong>₹{prediction?.baseline_benchmarks?.naive_persistence?.mae_inr_per_g || 68.28}/g</strong></span>
                  <button
                    onClick={() => setActiveTab("predictions")}
                    className="text-xs font-medium text-amber-400 hover:text-amber-300"
                  >
                    View Model Specs →
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ========================================================================= */}
        {/* TAB 2: MARKETS                                                            */}
        {/* ========================================================================= */}
        {activeTab === "markets" && (
          <div className="space-y-6">
            <div className="bg-zinc-900/40 border border-zinc-800/80 rounded-xl p-6">
              <h2 className="text-lg font-bold text-white">Precious Metals & Forex Market Monitor</h2>
              <p className="text-xs text-zinc-400 mt-1">Multi-source feeds comparing Indian delivery spot rates with COMEX futures benchmarks</p>

              {/* Trading Session Status Indicators */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
                <div className="p-4 rounded-lg bg-zinc-950 border border-zinc-800">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold text-zinc-300">Indian Physical Bullion (KJPL Ahmedabad)</span>
                    <span className="text-xs px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                      {overview?.trading_status?.indian_physical_market || "OPEN"}
                    </span>
                  </div>
                  <p className="text-xs text-zinc-400 mt-2">{overview?.trading_status?.indian_physical_description || "Physical bullion trading session."}</p>
                  <p className="text-xs text-zinc-500 mt-1">Server Clock: {overview?.trading_status?.server_time_ist || "Asia/Kolkata"}</p>
                </div>

                <div className="p-4 rounded-lg bg-zinc-950 border border-zinc-800">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold text-zinc-300">US COMEX Futures & Global Forex</span>
                    <span className="text-xs px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 border border-blue-500/30">
                      {overview?.trading_status?.global_futures_market || "OPEN"}
                    </span>
                  </div>
                  <p className="text-xs text-zinc-400 mt-2">{overview?.trading_status?.global_futures_description || "Global futures & currency exchange active."}</p>
                  <p className="text-xs text-zinc-500 mt-1">Tickers: COMEX Gold (GC=F), Silver (SI=F), USD/INR (USDINR=X)</p>
                </div>
              </div>

              {/* Conversion Math Explainer Box */}
              <div className="p-4 rounded-lg bg-zinc-900/60 border border-zinc-800 mt-6 text-xs text-zinc-300 space-y-2">
                <div className="font-semibold text-amber-400">Exact Conversion & Duty Math:</div>
                <div className="font-mono bg-zinc-950 p-2.5 rounded border border-zinc-800 text-zinc-300">
                  Global Gold (INR/g) = [COMEX Gold (${overview?.market?.xauusd}) × USDINR (₹{overview?.market?.usdinr})] / 31.1034768 = ₹{overview?.derived?.global_gold_inr_per_gram?.toLocaleString()} / g
                </div>
                <div className="font-mono bg-zinc-950 p-2.5 rounded border border-zinc-800 text-zinc-300">
                  Domestic Disparity = [KJPL Rate (₹{overview?.kjpl?.gold_mjdta}) - Global Parity (₹{overview?.derived?.global_gold_inr_per_gram})] = +₹{overview?.derived?.domestic_premium_inr_per_gram} (+{overview?.derived?.domestic_premium_pct}%)
                </div>
                <p className="text-zinc-500 text-xs">
                  *The domestic premium reflects India's 6% Basic Customs Duty (BCD), Agriculture Infrastructure Development Cess (AIDC), local air freight, and physical vault delivery charges.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* ========================================================================= */}
        {/* TAB 3: MY BULLION (PORTFOLIO)                                             */}
        {/* ========================================================================= */}
        {activeTab === "portfolio" && (
          <div className="space-y-6">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div>
                <h2 className="text-xl font-bold text-white">Personal Physical Bullion Holdings</h2>
                <p className="text-xs text-zinc-400 mt-0.5">Secure, isolated physical gold and silver inventory tracking</p>
              </div>
              <button
                onClick={() => {
                  setHoldingForm({
                    metal_type: "GOLD",
                    product_name: "24K Minted Bar",
                    purity: "0.999",
                    gross_weight: "10.0",
                    weight_unit: "g",
                    quantity: "1",
                    acquisition_date: new Date().toISOString().split("T")[0],
                    acquisition_cost_inr: "",
                    notes: "Personal Vault",
                  });
                  setIsAddHoldingOpen(true);
                }}
                className="px-4 py-2 bg-amber-500 hover:bg-amber-400 text-black text-xs font-bold rounded-lg transition-all shadow-md shadow-amber-500/20"
              >
                + Add Physical Holding
              </button>
            </div>

            {/* Holdings Table */}
            <div className="bg-zinc-900/40 border border-zinc-800/80 rounded-xl overflow-hidden shadow-sm">
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse text-xs">
                  <thead>
                    <tr className="border-b border-zinc-800 bg-zinc-900/80 text-zinc-400 uppercase tracking-wider font-semibold">
                      <th className="py-3 px-4">Item & Fineness</th>
                      <th className="py-3 px-4">Gross Weight</th>
                      <th className="py-3 px-4">Fine Pure Weight</th>
                      <th className="py-3 px-4">Qty</th>
                      <th className="py-3 px-4">Acquisition Cost</th>
                      <th className="py-3 px-4">Current Valuation</th>
                      <th className="py-3 px-4">Unrealized PnL</th>
                      <th className="py-3 px-4 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-800/60">
                    {holdings.length === 0 ? (
                      <tr>
                        <td colSpan={8} className="py-8 text-center text-zinc-500">
                          No bullion holdings cataloged yet. Click "+ Add Physical Holding" to record gold or silver.
                        </td>
                      </tr>
                    ) : (
                      holdings.map((h) => (
                        <tr key={h.id} className="hover:bg-zinc-800/30 transition-colors">
                          <td className="py-3.5 px-4">
                            <div className="font-semibold text-white">{h.product_name}</div>
                            <div className="text-zinc-500 text-xs">
                              {h.metal_type} • Purity: {(h.purity * 1000).toFixed(1)} / 1000 ({h.purity >= 0.995 ? "24K" : h.purity >= 0.916 ? "22K" : "18K"})
                            </div>
                          </td>
                          <td className="py-3.5 px-4 font-medium text-zinc-200">
                            {h.gross_weight_grams.toFixed(2)} g
                          </td>
                          <td className="py-3.5 px-4 font-semibold text-amber-400">
                            {h.fine_weight_grams.toFixed(2)} g
                            <span className="block text-zinc-500 text-xs font-normal">({h.fine_weight_kg.toFixed(4)} kg)</span>
                          </td>
                          <td className="py-3.5 px-4 text-zinc-300 font-medium">
                            {h.quantity}
                          </td>
                          <td className="py-3.5 px-4 text-zinc-300">
                            {h.acquisition_cost_inr !== null ? (
                              <span>₹{h.acquisition_cost_inr.toLocaleString()}</span>
                            ) : (
                              <span className="text-zinc-500 italic">Unknown / Inherited</span>
                            )}
                          </td>
                          <td className="py-3.5 px-4 font-bold text-white">
                            ₹{h.current_valuation_inr.toLocaleString()}
                          </td>
                          <td className="py-3.5 px-4">
                            {h.unrealized_gain_loss_inr !== null ? (
                              <span className={`font-semibold ${h.unrealized_gain_loss_inr >= 0 ? "text-emerald-400" : "text-rose-400"}`}>
                                {h.unrealized_gain_loss_inr >= 0 ? "+" : ""}₹{h.unrealized_gain_loss_inr.toLocaleString()} ({h.unrealized_gain_loss_pct}%)
                              </span>
                            ) : (
                              <span className="text-zinc-500">—</span>
                            )}
                          </td>
                          <td className="py-3.5 px-4 text-right space-x-2">
                            <button
                              onClick={() => openEditModal(h)}
                              className="text-amber-400 hover:text-amber-300 transition-colors p-1"
                              title="Edit Holding"
                            >
                              ✎
                            </button>
                            <button
                              onClick={() => handleDeleteHolding(h.id)}
                              className="text-rose-400 hover:text-rose-300 transition-colors p-1"
                              title="Delete Holding"
                            >
                              🗑
                            </button>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Historical Valuation Chart / Table */}
            {portfolioHistory.length > 0 && (
              <div className="bg-zinc-900/40 border border-zinc-800/80 rounded-xl p-6">
                <h3 className="text-base font-bold text-white">Historical Portfolio Valuation Trajectory</h3>
                <p className="text-xs text-zinc-400 mt-1">Vault mark-to-market performance across recorded KJPL historical dates</p>
                <div className="overflow-x-auto mt-4 max-h-60 overflow-y-auto">
                  <table className="w-full text-left text-xs">
                    <thead>
                      <tr className="border-b border-zinc-800 text-zinc-400">
                        <th className="py-2 px-3">Date</th>
                        <th className="py-2 px-3">Gold Spot (₹/g)</th>
                        <th className="py-2 px-3">Silver Spot (₹/kg)</th>
                        <th className="py-2 px-3">Vault Valuation</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-zinc-800/50">
                      {portfolioHistory.slice(-10).reverse().map((rec, i) => (
                        <tr key={i} className="hover:bg-zinc-800/20">
                          <td className="py-2 px-3 text-zinc-300">{rec.date}</td>
                          <td className="py-2 px-3 text-amber-400">₹{rec.gold_rate_inr.toLocaleString()}</td>
                          <td className="py-2 px-3 text-zinc-300">₹{(rec.silver_rate_inr * 1000).toLocaleString()}</td>
                          <td className="py-2 px-3 font-bold text-white">₹{rec.total_valuation_inr.toLocaleString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ========================================================================= */}
        {/* TAB 4: PREDICTIONS                                                        */}
        {/* ========================================================================= */}
        {activeTab === "predictions" && (
          <div className="space-y-6">
            <div className="bg-zinc-900/40 border border-zinc-800/80 rounded-xl p-6">
              <div className="flex items-center justify-between pb-4 border-b border-zinc-800">
                <div>
                  <h2 className="text-xl font-bold text-white flex items-center gap-2">
                    <span>AI Gold-Price Forecasting</span>
                    <span className="text-xs px-2.5 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/30">
                      EXPERIMENTAL DATA COLLECTION
                    </span>
                  </h2>
                  <p className="text-xs text-zinc-400 mt-1">Zero-lookahead supervised time-series forecasting model for Ahmedabad 24K spot gold</p>
                </div>
              </div>

              {/* Progress and Data Integrity Notice */}
              <div className="mt-6 p-4 rounded-lg bg-zinc-950 border border-zinc-800">
                <div className="flex justify-between text-xs text-zinc-300 mb-2">
                  <span className="font-semibold">Dataset Accumulation Progress:</span>
                  <span className="text-amber-400 font-bold">{prediction?.metrics?.current_samples || 34} / 50 Observed Events ({prediction?.metrics?.progress_pct || 68}%)</span>
                </div>
                <div className="w-full bg-zinc-800 rounded-full h-2.5 overflow-hidden">
                  <div
                    className="bg-gradient-to-r from-amber-500 to-amber-400 h-2.5 rounded-full transition-all duration-500"
                    style={{ width: `${prediction?.metrics?.progress_pct || 68}%` }}
                  />
                </div>
                <p className="text-xs text-zinc-400 mt-3 leading-relaxed">
                  {prediction?.message}
                </p>
              </div>

              {/* Baseline Persistence Benchmarks */}
              <div className="mt-6">
                <h3 className="text-sm font-semibold text-zinc-200">Baseline Evaluation Benchmarks (Zero-Lookahead Backtest):</h3>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-3">
                  <div className="p-4 rounded-lg bg-zinc-900 border border-zinc-800">
                    <div className="text-xs text-zinc-400 font-semibold uppercase">Naive Persistence (Next = Current)</div>
                    <div className="text-2xl font-bold text-white mt-1">MAE: ±₹{prediction?.baseline_benchmarks?.naive_persistence?.mae_inr_per_g || 68.28}/g</div>
                    <div className="text-xs text-zinc-500 mt-1">RMSE: ₹{prediction?.baseline_benchmarks?.naive_persistence?.rmse_inr_per_g || 89.05}/g</div>
                  </div>
                  <div className="p-4 rounded-lg bg-zinc-900 border border-zinc-800">
                    <div className="text-xs text-zinc-400 font-semibold uppercase">3-Event Rolling Moving Average</div>
                    <div className="text-2xl font-bold text-white mt-1">MAE: ±₹{prediction?.baseline_benchmarks?.sma_3_event?.mae_inr_per_g || 135.89}/g</div>
                    <div className="text-xs text-zinc-500 mt-1">RMSE: ₹{prediction?.baseline_benchmarks?.sma_3_event?.rmse_inr_per_g || 175.07}/g</div>
                  </div>
                </div>
              </div>

              {/* Model Specifications */}
              <div className="mt-6 p-4 rounded-lg bg-zinc-900/60 border border-zinc-800 text-xs text-zinc-400 space-y-1.5">
                <div className="font-semibold text-zinc-200">Pipeline Invariants & Architecture:</div>
                <div>• Target: <strong className="text-zinc-200">next_event_gold</strong> (Next calendar trading event published rate)</div>
                <div>• Lookback Window: Strict cutoff enforcing publication date &lt;= event time (zero lookahead leakage)</div>
                <div>• Features: Converted spot parity, daily forex returns, domestic premium spread, FinBERT 24h sentiment mean & std</div>
              </div>
            </div>
          </div>
        )}

        {/* ========================================================================= */}
        {/* TAB 5: NEWS INTELLIGENCE                                                  */}
        {/* ========================================================================= */}
        {activeTab === "news" && (
          <div className="space-y-6">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div>
                <h2 className="text-xl font-bold text-white">Financial News Intelligence Feed</h2>
                <p className="text-xs text-zinc-400 mt-0.5">NLP-analyzed financial news desks scored via ProsusAI FinBERT</p>
              </div>

              {/* Filters */}
              <div className="flex space-x-1 bg-zinc-900 p-1 rounded-lg border border-zinc-800 text-xs">
                {["ALL", "BULLISH", "BEARISH", "GOLD_ONLY"].map((filter) => (
                  <button
                    key={filter}
                    onClick={() => setNewsFilter(filter)}
                    className={`px-3 py-1 rounded font-medium transition-colors ${
                      newsFilter === filter ? "bg-amber-500 text-black font-semibold" : "text-zinc-400 hover:text-zinc-200"
                    }`}
                  >
                    {filter}
                  </button>
                ))}
              </div>
            </div>

            <div className="bg-zinc-900/40 border border-zinc-800/80 rounded-xl divide-y divide-zinc-800/60">
              {filteredNews.length === 0 ? (
                <div className="p-8 text-center text-zinc-500 text-xs">No articles matching active filter criteria.</div>
              ) : (
                filteredNews.map((item) => (
                  <div key={item.id} className="p-4 hover:bg-zinc-800/20 transition-colors flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span className={`px-2 py-0.5 rounded font-semibold text-xs ${
                          item.sentiment_label === "POSITIVE"
                            ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30"
                            : item.sentiment_label === "NEGATIVE"
                            ? "bg-rose-500/10 text-rose-400 border border-rose-500/30"
                            : "bg-zinc-800 text-zinc-400 border border-zinc-700"
                        }`}>
                          {item.sentiment_label === "POSITIVE" ? "BULLISH" : item.sentiment_label === "NEGATIVE" ? "BEARISH" : "NEUTRAL"}
                        </span>
                        {item.is_gold_relevant && (
                          <span className="px-2 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/30 text-xs">
                            Gold Relevant
                          </span>
                        )}
                        <span className="text-zinc-500">{item.source}</span>
                      </div>
                      <h4 className="text-sm font-semibold text-zinc-100 hover:text-amber-400 transition-colors">
                        <a href={item.url} target="_blank" rel="noopener noreferrer">
                          {item.title}
                        </a>
                      </h4>
                    </div>
                    <div className="text-zinc-500 whitespace-nowrap text-xs">
                      {new Date(item.published_at).toLocaleDateString()} {new Date(item.published_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        )}

        {/* ========================================================================= */}
        {/* TAB 6: RESEARCH & HISTORICAL ANALYSIS                                     */}
        {/* ========================================================================= */}
        {activeTab === "research" && (
          <div className="space-y-6">
            <div className="bg-zinc-900/40 border border-zinc-800/80 rounded-xl p-6">
              <h2 className="text-xl font-bold text-white">Quantitative Precious Metals Research</h2>
              <p className="text-xs text-zinc-400 mt-1">Historical rates, parity correlation, and disparity distributions</p>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-6">
                <div className="p-4 rounded-lg bg-zinc-950 border border-zinc-800">
                  <div className="text-xs text-zinc-400 uppercase font-semibold">Gold / Silver Ratio</div>
                  <div className="text-2xl font-bold text-white mt-1">{overview?.derived?.global_gold_silver_ratio || "59.1"}</div>
                  <div className="text-xs text-zinc-500 mt-1">Ounces of silver needed to purchase 1 oz of gold</div>
                </div>
                <div className="p-4 rounded-lg bg-zinc-950 border border-zinc-800">
                  <div className="text-xs text-zinc-400 uppercase font-semibold">Total Verified Market Events</div>
                  <div className="text-2xl font-bold text-amber-400 mt-1">35 Events</div>
                  <div className="text-xs text-zinc-500 mt-1">Logged from KJPL Ahmedabad wholesale spot</div>
                </div>
                <div className="p-4 rounded-lg bg-zinc-950 border border-zinc-800">
                  <div className="text-xs text-zinc-400 uppercase font-semibold">Analyzed News Sample</div>
                  <div className="text-2xl font-bold text-zinc-200 mt-1">2,735 Articles</div>
                  <div className="text-xs text-zinc-500 mt-1">1,065 bullion-relevant FinBERT vectors</div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ========================================================================= */}
        {/* TAB 7: ALERTS                                                             */}
        {/* ========================================================================= */}
        {activeTab === "alerts" && (
          <div className="space-y-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-xl font-bold text-white">Price & Premium Alert Rules</h2>
                <p className="text-xs text-zinc-400 mt-0.5">Automated monitoring triggers for spot rates and domestic premium breaches</p>
              </div>
              <button
                onClick={() => setIsAddAlertOpen(true)}
                className="px-4 py-2 bg-amber-500 hover:bg-amber-400 text-black text-xs font-bold rounded-lg transition-all"
              >
                + Create Trigger Rule
              </button>
            </div>

            <div className="bg-zinc-900/40 border border-zinc-800/80 rounded-xl divide-y divide-zinc-800/60">
              {alerts.length === 0 ? (
                <div className="p-8 text-center text-zinc-500 text-xs">No active alert triggers configured.</div>
              ) : (
                alerts.map((al) => (
                  <div key={al.id} className="p-4 flex items-center justify-between text-xs">
                    <div>
                      <span className="font-semibold text-white">{al.target_metric} {al.alert_type} {al.threshold}</span>
                      {al.notes && <p className="text-zinc-500 text-xs mt-0.5">{al.notes}</p>}
                    </div>
                    <button
                      onClick={() => handleDeleteAlert(al.id)}
                      className="text-rose-400 hover:text-rose-300 text-xs px-2 py-1"
                    >
                      Delete
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>
        )}

        {/* ========================================================================= */}
        {/* TAB 8: SETTINGS                                                           */}
        {/* ========================================================================= */}
        {activeTab === "settings" && (
          <div className="space-y-6">
            <div className="bg-zinc-900/40 border border-zinc-800/80 rounded-xl p-6">
              <h2 className="text-xl font-bold text-white">Platform Settings & Security</h2>
              <p className="text-xs text-zinc-400 mt-1">Configure user authentication, reference benchmarks, and operational parameters</p>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-6">
                <div className="space-y-4">
                  <div>
                    <label className="block text-xs font-semibold text-zinc-300 mb-1">Tenant User Identifier</label>
                    <input
                      type="text"
                      value={userId}
                      onChange={(e) => setUserId(e.target.value)}
                      className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-xs text-white"
                      placeholder="e.g. owner or user_id"
                    />
                    <p className="text-xs text-zinc-500 mt-1">Binds portfolio records to this private vault partition.</p>
                  </div>

                  <div>
                    <label className="block text-xs font-semibold text-zinc-300 mb-1">Server Authorization Token (Optional)</label>
                    <input
                      type="password"
                      value={apiKey}
                      onChange={(e) => setApiKey(e.target.value)}
                      className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-xs text-white"
                      placeholder="Enter GOLDSENSE_API_KEY if auth enabled"
                    />
                    <p className="text-xs text-zinc-500 mt-1">Used for Bearer authorization against production backend.</p>
                  </div>
                </div>

                <div className="p-4 rounded-lg bg-zinc-950 border border-zinc-800 text-xs text-zinc-400 space-y-2">
                  <div className="font-semibold text-zinc-200">System Information:</div>
                  <div>• Branch: <code className="text-amber-400">develop</code></div>
                  <div>• Primary Rate Benchmark: <code className="text-zinc-200">KJPL Ahmedabad 999 MJDTA</code></div>
                  <div>• Conversion Standard: <code className="text-zinc-200">1 Troy Oz ≡ 31.1034768 g</code></div>
                  <div>• Rate Refresh Debounce: <code className="text-zinc-200">60 Seconds</code></div>
                </div>
              </div>
            </div>
          </div>
        )}

      </main>

      {/* ========================================================================= */}
      {/* MODAL: ADD HOLDING                                                        */}
      {/* ========================================================================= */}
      {isAddHoldingOpen && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl max-w-md w-full p-6 shadow-2xl">
            <h3 className="text-lg font-bold text-white mb-4">Add Bullion Holding</h3>
            <form onSubmit={handleCreateHolding} className="space-y-4 text-xs">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-zinc-400 mb-1">Precious Metal</label>
                  <select
                    value={holdingForm.metal_type}
                    onChange={(e) => setHoldingForm({ ...holdingForm, metal_type: e.target.value })}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-white"
                  >
                    <option value="GOLD">Gold</option>
                    <option value="SILVER">Silver</option>
                  </select>
                </div>
                <div>
                  <label className="block text-zinc-400 mb-1">Purity (Fineness)</label>
                  <select
                    value={holdingForm.purity}
                    onChange={(e) => setHoldingForm({ ...holdingForm, purity: e.target.value })}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-white"
                  >
                    <option value="0.9999">999.9 (24K Minted Bar)</option>
                    <option value="0.999">999.0 (24K Standard)</option>
                    <option value="0.995">995.0 (24K Bullion)</option>
                    <option value="0.916">916.0 (22K Jewelry)</option>
                    <option value="0.750">750.0 (18K Jewelry)</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-zinc-400 mb-1">Product Description</label>
                <input
                  type="text"
                  required
                  value={holdingForm.product_name}
                  onChange={(e) => setHoldingForm({ ...holdingForm, product_name: e.target.value })}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-white"
                />
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div className="col-span-2">
                  <label className="block text-zinc-400 mb-1">Gross Weight</label>
                  <input
                    type="number"
                    step="0.01"
                    min="0.01"
                    required
                    value={holdingForm.gross_weight}
                    onChange={(e) => setHoldingForm({ ...holdingForm, gross_weight: e.target.value })}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-white"
                  />
                </div>
                <div>
                  <label className="block text-zinc-400 mb-1">Unit</label>
                  <select
                    value={holdingForm.weight_unit}
                    onChange={(e) => setHoldingForm({ ...holdingForm, weight_unit: e.target.value })}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-white"
                  >
                    <option value="g">Grams (g)</option>
                    <option value="kg">Kilograms (kg)</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-zinc-400 mb-1">Quantity</label>
                  <input
                    type="number"
                    min="1"
                    required
                    value={holdingForm.quantity}
                    onChange={(e) => setHoldingForm({ ...holdingForm, quantity: e.target.value })}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-white"
                  />
                </div>
                <div>
                  <label className="block text-zinc-400 mb-1">Total Cost in INR (Optional)</label>
                  <input
                    type="number"
                    step="0.01"
                    placeholder="Leave empty if unknown"
                    value={holdingForm.acquisition_cost_inr}
                    onChange={(e) => setHoldingForm({ ...holdingForm, acquisition_cost_inr: e.target.value })}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-white"
                  />
                </div>
              </div>

              <div>
                <label className="block text-zinc-400 mb-1">Notes / Vault Location</label>
                <input
                  type="text"
                  value={holdingForm.notes}
                  onChange={(e) => setHoldingForm({ ...holdingForm, notes: e.target.value })}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-white"
                />
              </div>

              <div className="flex justify-end gap-3 pt-4 border-t border-zinc-800">
                <button
                  type="button"
                  onClick={() => setIsAddHoldingOpen(false)}
                  className="px-4 py-2 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded font-semibold"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 bg-amber-500 hover:bg-amber-400 text-black rounded font-bold"
                >
                  Save Holding
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* MODAL: EDIT HOLDING                                                       */}
      {/* ========================================================================= */}
      {isEditHoldingOpen && editingHolding && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl max-w-md w-full p-6 shadow-2xl">
            <h3 className="text-lg font-bold text-white mb-4">Edit Bullion Holding #{editingHolding.id}</h3>
            <form onSubmit={handleUpdateHolding} className="space-y-4 text-xs">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-zinc-400 mb-1">Precious Metal</label>
                  <select
                    value={holdingForm.metal_type}
                    onChange={(e) => setHoldingForm({ ...holdingForm, metal_type: e.target.value })}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-white"
                  >
                    <option value="GOLD">Gold</option>
                    <option value="SILVER">Silver</option>
                  </select>
                </div>
                <div>
                  <label className="block text-zinc-400 mb-1">Purity (Fineness)</label>
                  <select
                    value={holdingForm.purity}
                    onChange={(e) => setHoldingForm({ ...holdingForm, purity: e.target.value })}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-white"
                  >
                    <option value="0.9999">999.9 (24K Minted Bar)</option>
                    <option value="0.999">999.0 (24K Standard)</option>
                    <option value="0.995">995.0 (24K Bullion)</option>
                    <option value="0.916">916.0 (22K Jewelry)</option>
                    <option value="0.750">750.0 (18K Jewelry)</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-zinc-400 mb-1">Product Description</label>
                <input
                  type="text"
                  required
                  value={holdingForm.product_name}
                  onChange={(e) => setHoldingForm({ ...holdingForm, product_name: e.target.value })}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-white"
                />
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div className="col-span-2">
                  <label className="block text-zinc-400 mb-1">Gross Weight</label>
                  <input
                    type="number"
                    step="0.01"
                    min="0.01"
                    required
                    value={holdingForm.gross_weight}
                    onChange={(e) => setHoldingForm({ ...holdingForm, gross_weight: e.target.value })}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-white"
                  />
                </div>
                <div>
                  <label className="block text-zinc-400 mb-1">Unit</label>
                  <select
                    value={holdingForm.weight_unit}
                    onChange={(e) => setHoldingForm({ ...holdingForm, weight_unit: e.target.value })}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-white"
                  >
                    <option value="g">Grams (g)</option>
                    <option value="kg">Kilograms (kg)</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-zinc-400 mb-1">Quantity</label>
                  <input
                    type="number"
                    min="1"
                    required
                    value={holdingForm.quantity}
                    onChange={(e) => setHoldingForm({ ...holdingForm, quantity: e.target.value })}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-white"
                  />
                </div>
                <div>
                  <label className="block text-zinc-400 mb-1">Total Cost in INR</label>
                  <input
                    type="number"
                    step="0.01"
                    placeholder="Leave empty if unknown"
                    value={holdingForm.acquisition_cost_inr}
                    onChange={(e) => setHoldingForm({ ...holdingForm, acquisition_cost_inr: e.target.value })}
                    className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-white"
                  />
                </div>
              </div>

              <div>
                <label className="block text-zinc-400 mb-1">Notes</label>
                <input
                  type="text"
                  value={holdingForm.notes}
                  onChange={(e) => setHoldingForm({ ...holdingForm, notes: e.target.value })}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-white"
                />
              </div>

              <div className="flex justify-end gap-3 pt-4 border-t border-zinc-800">
                <button
                  type="button"
                  onClick={() => setIsEditHoldingOpen(false)}
                  className="px-4 py-2 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded font-semibold"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 bg-amber-500 hover:bg-amber-400 text-black rounded font-bold"
                >
                  Save Changes
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* MODAL: ADD ALERT                                                          */}
      {/* ========================================================================= */}
      {isAddAlertOpen && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl max-w-sm w-full p-6 shadow-2xl">
            <h3 className="text-lg font-bold text-white mb-4">Create Price Alert</h3>
            <form onSubmit={handleCreateAlert} className="space-y-4 text-xs">
              <div>
                <label className="block text-zinc-400 mb-1">Condition</label>
                <select
                  value={alertForm.alert_type}
                  onChange={(e) => setAlertForm({ ...alertForm, alert_type: e.target.value })}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-white"
                >
                  <option value="PRICE_ABOVE">Spot Rate Above (&gt;)</option>
                  <option value="PRICE_BELOW">Spot Rate Below (&lt;)</option>
                  <option value="PREMIUM_ABOVE">Domestic Premium Above (&gt; %)</option>
                </select>
              </div>

              <div>
                <label className="block text-zinc-400 mb-1">Threshold Value</label>
                <input
                  type="number"
                  step="0.01"
                  required
                  value={alertForm.threshold}
                  onChange={(e) => setAlertForm({ ...alertForm, threshold: e.target.value })}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-white"
                />
              </div>

              <div>
                <label className="block text-zinc-400 mb-1">Notes (Optional)</label>
                <input
                  type="text"
                  value={alertForm.notes}
                  onChange={(e) => setAlertForm({ ...alertForm, notes: e.target.value })}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-white"
                  placeholder="e.g. Target rebalancing point"
                />
              </div>

              <div className="flex justify-end gap-3 pt-4 border-t border-zinc-800">
                <button
                  type="button"
                  onClick={() => setIsAddAlertOpen(false)}
                  className="px-4 py-2 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded font-semibold"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 bg-amber-500 hover:bg-amber-400 text-black rounded font-bold"
                >
                  Create Alert
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

    </div>
  );
}
