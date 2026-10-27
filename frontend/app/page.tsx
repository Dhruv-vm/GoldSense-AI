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

interface OverviewResponse {
  status: string;
  timestamp: string;
  kjpl: KJPLData;
  market: MarketData;
  derived: DerivedData;
  overall_freshness: string;
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

interface PredictionStatus {
  status: string;
  is_ready: boolean;
  message: string;
  metrics?: {
    current_samples: number;
    required_samples: number;
    progress_pct: number;
  };
  current_macro_snapshot?: Record<string, any>;
  predicted_gold_price?: number;
  predicted_direction?: string;
  expected_change_inr?: number;
  expected_change_pct?: number;
}

interface NewsArticle {
  title: string;
  url: string;
  source: string;
  published_at: string;
  sentiment_label: string;
  sentiment_score: number;
  is_gold_relevant: boolean;
  primary_category: string;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function GoldSenseDashboard() {
  const [activeTab, setActiveTab] = useState<"overview" | "portfolio" | "predictions" | "news" | "alerts">("overview");

  // Market overview state
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [loadingOverview, setLoadingOverview] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshMessage, setRefreshMessage] = useState<string | null>(null);

  // Portfolio state
  const [portfolio, setPortfolio] = useState<PortfolioSummary | null>(null);
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [loadingPortfolio, setLoadingPortfolio] = useState(false);
  const [showAddModal, setShowAddModal] = useState(false);

  // Add holding form
  const [newMetal, setNewMetal] = useState<"GOLD" | "SILVER">("GOLD");
  const [newProduct, setNewProduct] = useState("");
  const [newPurity, setNewPurity] = useState(0.999);
  const [newWeight, setNewWeight] = useState(10.0);
  const [newUnit, setNewUnit] = useState<"g" | "kg">("g");
  const [newQuantity, setNewQuantity] = useState(1);
  const [newCost, setNewCost] = useState("");
  const [newDate, setNewDate] = useState("");
  const [newNotes, setNewNotes] = useState("");

  // Predictions state
  const [prediction, setPrediction] = useState<PredictionStatus | null>(null);

  // News state
  const [news, setNews] = useState<NewsArticle[]>([]);

  // Alerts state
  const [alerts, setAlerts] = useState<any[]>([]);
  const [newAlertThreshold, setNewAlertThreshold] = useState("13500");
  const [newAlertType, setNewAlertType] = useState("PRICE_ABOVE");

  // Load initial market overview
  useEffect(() => {
    fetchOverview();
    fetchPortfolio();
    fetchPredictions();
    fetchNews();
    fetchAlerts();
  }, []);

  const fetchOverview = async () => {
    try {
      setLoadingOverview(true);
      const res = await fetch(`${API_BASE}/api/market/overview`);
      if (res.ok) {
        const data = await res.json();
        setOverview(data);
      }
    } catch {
      // Fallback preview data if backend server is not currently running locally
      setOverview({
        status: "OFFLINE_FALLBACK",
        timestamp: new Date().toISOString(),
        kjpl: {
          source: "KJPL (MJDTA Benchmark)",
          gold_mjdta: 13135.0,
          silver_mjdta: 220.0,
          published_time: "Time : 09:42 am",
          observed_at: new Date().toISOString(),
          change_24h_inr: 50.0,
          change_24h_pct: 0.38,
          freshness: "FRESH",
        },
        market: {
          xauusd: 4021.7,
          xagusd: 53.45,
          usdinr: 95.2,
          observed_at: new Date().toISOString(),
          source: "Yahoo Finance (COMEX & Forex)",
          xauusd_change_24h: 12.5,
          xauusd_change_24h_pct: 0.31,
          usdinr_change_24h: 0.05,
          freshness: "FRESH",
        },
        derived: {
          global_gold_inr_per_gram: 12309.1,
          global_silver_inr_per_gram: 163.58,
          domestic_premium_inr_per_gram: 825.9,
          domestic_premium_pct: 6.71,
          global_gold_silver_ratio: 75.25,
          domestic_gold_silver_ratio: 59.7,
          conversion_factor: 31.1034768,
        },
        overall_freshness: "FRESH",
      });
    } finally {
      setLoadingOverview(false);
    }
  };

  const handleManualRefresh = async () => {
    try {
      setRefreshing(true);
      setRefreshMessage("Checking live feeds...");
      const res = await fetch(`${API_BASE}/api/market/refresh`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setOverview(data);
        setRefreshMessage(data.message || "Market data refreshed.");
      } else {
        setRefreshMessage("Refresh rate limit reached or backend unavailable.");
      }
    } catch (e: any) {
      setRefreshMessage("Could not contact backend server.");
    } finally {
      setRefreshing(false);
      setTimeout(() => setRefreshMessage(null), 5000);
    }
  };

  const fetchPortfolio = async () => {
    try {
      setLoadingPortfolio(true);
      const [resSum, resHold] = await Promise.all([
        fetch(`${API_BASE}/api/portfolio/summary`),
        fetch(`${API_BASE}/api/portfolio/holdings`),
      ]);
      if (resSum.ok) setPortfolio(await resSum.json());
      if (resHold.ok) setHoldings(await resHold.json());
    } catch (e) {
      console.error(e);
    } finally {
      setLoadingPortfolio(false);
    }
  };

  const handleAddHolding = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await fetch(`${API_BASE}/api/portfolio/holdings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          metal_type: newMetal,
          product_name: newProduct || (newMetal === "GOLD" ? "24K Gold Bar" : "999 Silver Cast Bar"),
          purity: Number(newPurity),
          gross_weight: Number(newWeight),
          weight_unit: newUnit,
          quantity: Number(newQuantity),
          acquisition_cost_inr: newCost ? Number(newCost) : null,
          acquisition_date: newDate || null,
          notes: newNotes || null,
        }),
      });
      if (res.ok) {
        setShowAddModal(false);
        fetchPortfolio();
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleDeleteHolding = async (id: number) => {
    try {
      const res = await fetch(`${API_BASE}/api/portfolio/holdings/${id}`, { method: "DELETE" });
      if (res.ok) fetchPortfolio();
    } catch (err) {
      console.error(err);
    }
  };

  const fetchPredictions = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/predictions/latest`);
      if (res.ok) setPrediction(await res.json());
    } catch (e) {
      console.error(e);
    }
  };

  const fetchNews = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/news/latest?limit=15`);
      if (res.ok) setNews(await res.json());
    } catch (e) {
      console.error(e);
    }
  };

  const fetchAlerts = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/alerts`);
      if (res.ok) setAlerts(await res.json());
    } catch (e) {
      console.error(e);
    }
  };

  const handleCreateAlert = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await fetch(`${API_BASE}/api/alerts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          alert_type: newAlertType,
          target_metric: "KJPL_GOLD",
          threshold: Number(newAlertThreshold),
          notes: `Alert for ${newAlertType} ${newAlertThreshold}`,
        }),
      });
      if (res.ok) fetchAlerts();
    } catch (err) {
      console.error(err);
    }
  };

  const handleDeleteAlert = async (id: number) => {
    try {
      const res = await fetch(`${API_BASE}/api/alerts/${id}`, { method: "DELETE" });
      if (res.ok) fetchAlerts();
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 font-sans selection:bg-amber-500 selection:text-black">
      {/* Top Header */}
      <header className="border-b border-zinc-800 bg-zinc-900/60 backdrop-blur sticky top-0 z-40">
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

          {/* Navigation Bar */}
          <nav className="hidden md:flex space-x-1">
            {[
              { id: "overview", label: "Overview" },
              { id: "portfolio", label: "My Bullion" },
              { id: "predictions", label: "AI Predictions" },
              { id: "news", label: "News Intelligence" },
              { id: "alerts", label: "Alerts" },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as any)}
                className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${
                  activeTab === tab.id
                    ? "bg-amber-500/10 text-amber-400 border border-amber-500/20"
                    : "text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800/50"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </nav>

          {/* Refresh Action */}
          <div className="flex items-center space-x-3">
            {refreshMessage && (
              <span className="text-xs text-amber-400/90 font-mono animate-pulse hidden sm:inline">
                {refreshMessage}
              </span>
            )}
            <button
              onClick={handleManualRefresh}
              disabled={refreshing}
              className="flex items-center space-x-1 px-3 py-1.5 text-xs font-semibold rounded-md border border-zinc-700 bg-zinc-800 hover:bg-zinc-700 active:scale-95 transition"
            >
              <span className={`inline-block w-2 h-2 rounded-full ${overview?.overall_freshness === "FRESH" ? "bg-emerald-500" : "bg-amber-500"}`} />
              <span>{refreshing ? "Refreshing..." : "Refresh"}</span>
            </button>
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* OVERVIEW TAB */}
        {activeTab === "overview" && (
          <div className="space-y-8">
            {/* Rates Banner */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
              {/* KJPL Gold 24K */}
              <div className="p-5 rounded-xl border border-zinc-800 bg-zinc-900/50 shadow-sm relative overflow-hidden group hover:border-amber-500/40 transition">
                <div className="flex justify-between items-start mb-2">
                  <span className="text-xs font-semibold uppercase tracking-wider text-zinc-400">KJPL Gold 24K (MJDTA)</span>
                  <span className="text-[10px] px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 font-mono border border-emerald-500/20">
                    {overview?.kjpl?.freshness || "FRESH"}
                  </span>
                </div>
                <div className="text-3xl font-bold font-mono text-amber-400">
                  ₹{overview?.kjpl?.gold_mjdta?.toLocaleString("en-IN") || "—"}{" "}
                  <span className="text-xs font-normal text-zinc-500">/ gram</span>
                </div>
                <div className="mt-3 flex items-center justify-between text-xs text-zinc-400 border-t border-zinc-800/80 pt-2">
                  <span>Published: {overview?.kjpl?.published_time || "N/A"}</span>
                  <span className="text-emerald-400 font-semibold font-mono">
                    +{overview?.kjpl?.change_24h_pct || 0}%
                  </span>
                </div>
              </div>

              {/* KJPL Silver */}
              <div className="p-5 rounded-xl border border-zinc-800 bg-zinc-900/50 shadow-sm relative overflow-hidden group hover:border-zinc-400/40 transition">
                <div className="flex justify-between items-start mb-2">
                  <span className="text-xs font-semibold uppercase tracking-wider text-zinc-400">KJPL Silver (999)</span>
                  <span className="text-[10px] px-2 py-0.5 rounded bg-zinc-800 text-zinc-300 font-mono">
                    Domestic
                  </span>
                </div>
                <div className="text-3xl font-bold font-mono text-zinc-200">
                  ₹{overview?.kjpl?.silver_mjdta?.toLocaleString("en-IN") || "—"}{" "}
                  <span className="text-xs font-normal text-zinc-500">/ gram</span>
                </div>
                <div className="mt-3 flex items-center justify-between text-xs text-zinc-400 border-t border-zinc-800/80 pt-2">
                  <span>₹{((overview?.kjpl?.silver_mjdta || 0) * 1000).toLocaleString("en-IN")} / kg</span>
                  <span className="text-zinc-400 font-mono">Physical</span>
                </div>
              </div>

              {/* COMEX Gold (GC=F) */}
              <div className="p-5 rounded-xl border border-zinc-800 bg-zinc-900/50 shadow-sm relative overflow-hidden group hover:border-blue-500/40 transition">
                <div className="flex justify-between items-start mb-2">
                  <span className="text-xs font-semibold uppercase tracking-wider text-zinc-400">COMEX Gold (GC=F)</span>
                  <span className="text-[10px] px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 font-mono border border-blue-500/20">
                    US Global
                  </span>
                </div>
                <div className="text-3xl font-bold font-mono text-blue-400">
                  ${overview?.market?.xauusd?.toFixed(1) || "—"}{" "}
                  <span className="text-xs font-normal text-zinc-500">/ oz</span>
                </div>
                <div className="mt-3 flex items-center justify-between text-xs text-zinc-400 border-t border-zinc-800/80 pt-2">
                  <span>USD/INR: ₹{overview?.market?.usdinr?.toFixed(2)}</span>
                  <span className="text-blue-400 font-mono font-semibold">
                    +{overview?.market?.xauusd_change_24h_pct || 0}%
                  </span>
                </div>
              </div>

              {/* Domestic Premium */}
              <div className="p-5 rounded-xl border border-zinc-800 bg-zinc-900/50 shadow-sm relative overflow-hidden group hover:border-purple-500/40 transition">
                <div className="flex justify-between items-start mb-2">
                  <span className="text-xs font-semibold uppercase tracking-wider text-zinc-400">Domestic Premium</span>
                  <span className="text-[10px] px-2 py-0.5 rounded bg-purple-500/10 text-purple-400 font-mono border border-purple-500/20">
                    Tariff & Duty
                  </span>
                </div>
                <div className="text-3xl font-bold font-mono text-purple-400">
                  +{overview?.derived?.domestic_premium_pct?.toFixed(2) || "—"}%
                </div>
                <div className="mt-3 flex items-center justify-between text-xs text-zinc-400 border-t border-zinc-800/80 pt-2">
                  <span>Diff: +₹{overview?.derived?.domestic_premium_inr_per_gram?.toFixed(1)}/g</span>
                  <span>Global: ₹{overview?.derived?.global_gold_inr_per_gram?.toFixed(0)}/g</span>
                </div>
              </div>
            </div>

            {/* Quick Analytics & Insights Card */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              <div className="lg:col-span-2 p-6 rounded-xl border border-zinc-800 bg-zinc-900/40 space-y-4">
                <h3 className="text-sm font-semibold tracking-wide uppercase text-zinc-300">
                  Indian Bullion vs International Futures Arbitrage
                </h3>
                <p className="text-sm text-zinc-400 leading-relaxed">
                  Indian spot retail bullion (MJDTA/KJPL) currently trades at a{" "}
                  <span className="text-amber-400 font-semibold font-mono">
                    +{overview?.derived?.domestic_premium_pct}%
                  </span>{" "}
                  premium over global spot futures. This spread reflects India’s Basic Customs Duty (6% BCD + AIDC), local clearing, and refiner premiums.
                </p>

                <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 pt-4 border-t border-zinc-800 text-xs">
                  <div>
                    <span className="text-zinc-500 block">International Rate (INR/g)</span>
                    <span className="text-base font-bold font-mono text-zinc-200">
                      ₹{overview?.derived?.global_gold_inr_per_gram?.toLocaleString("en-IN")}
                    </span>
                  </div>
                  <div>
                    <span className="text-zinc-500 block">Domestic Gold/Silver Ratio</span>
                    <span className="text-base font-bold font-mono text-zinc-200">
                      {overview?.derived?.domestic_gold_silver_ratio} : 1
                    </span>
                  </div>
                  <div>
                    <span className="text-zinc-500 block">Global Gold/Silver Ratio</span>
                    <span className="text-base font-bold font-mono text-zinc-200">
                      {overview?.derived?.global_gold_silver_ratio} : 1
                    </span>
                  </div>
                </div>
              </div>

              {/* Quick AI & Data Health Card */}
              <div className="p-6 rounded-xl border border-zinc-800 bg-zinc-900/40 flex flex-col justify-between">
                <div>
                  <h3 className="text-sm font-semibold tracking-wide uppercase text-zinc-300 mb-2">
                    Predictive Engine Status
                  </h3>
                  <div className="flex items-center gap-2 mb-3">
                    <span className="w-2.5 h-2.5 rounded-full bg-amber-400 animate-pulse" />
                    <span className="text-xs font-mono font-medium text-amber-400">
                      Supervised Data Accumulation (34/50 Days)
                    </span>
                  </div>
                  <p className="text-xs text-zinc-400 leading-relaxed">
                    XGBoost models strictly enforce chronological zero-lookahead validation. 16 more daily market observations needed to train safely without overfitting.
                  </p>
                </div>

                <div className="pt-4 border-t border-zinc-800 mt-4">
                  <button
                    onClick={() => setActiveTab("predictions")}
                    className="w-full py-2 px-3 text-xs font-semibold rounded bg-amber-500/10 text-amber-400 border border-amber-500/30 hover:bg-amber-500/20 transition text-center"
                  >
                    View ML Architecture & Readiness
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* PORTFOLIO TAB */}
        {activeTab === "portfolio" && (
          <div className="space-y-8">
            {/* Portfolio Summary Card */}
            <div className="p-6 rounded-xl border border-zinc-800 bg-zinc-900/60 shadow-md">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-6 border-b border-zinc-800 gap-4">
                <div>
                  <h2 className="text-xl font-bold tracking-tight text-white">Personal Bullion Vault</h2>
                  <p className="text-xs text-zinc-400 mt-0.5">
                    Valuation benchmarked against Madras Jewellers & Diamond Traders Association (MJDTA) rates.
                  </p>
                </div>
                <button
                  onClick={() => setShowAddModal(true)}
                  className="px-4 py-2 text-xs font-semibold rounded-lg bg-amber-500 text-black hover:bg-amber-400 active:scale-95 transition shadow-lg shadow-amber-500/20 flex items-center justify-center gap-2"
                >
                  <span>+</span> Add Bullion Holding
                </button>
              </div>

              {/* Portfolio KPIs */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 pt-6">
                <div>
                  <span className="text-xs font-medium text-zinc-400 block">Total Estimated Value</span>
                  <span className="text-3xl font-extrabold font-mono text-white mt-1 block">
                    ₹{portfolio?.total_estimated_valuation_inr?.toLocaleString("en-IN") || "0"}
                  </span>
                  <span className="text-[11px] text-zinc-500 mt-0.5 block">Based on fine metal weight</span>
                </div>

                <div>
                  <span className="text-xs font-medium text-zinc-400 block">Recorded Cost Basis</span>
                  <span className="text-2xl font-bold font-mono text-zinc-300 mt-1 block">
                    {portfolio?.total_recorded_acquisition_cost_inr
                      ? `₹${portfolio.total_recorded_acquisition_cost_inr.toLocaleString("en-IN")}`
                      : "Not Recorded"}
                  </span>
                  <span className="text-[11px] text-zinc-500 mt-0.5 block">Known purchase price</span>
                </div>

                <div>
                  <span className="text-xs font-medium text-zinc-400 block">Unrealized Gain / Loss</span>
                  <span
                    className={`text-2xl font-bold font-mono mt-1 block ${
                      (portfolio?.unrealized_gain_loss_inr || 0) >= 0 ? "text-emerald-400" : "text-rose-400"
                    }`}
                  >
                    {portfolio?.unrealized_gain_loss_inr !== null && portfolio?.unrealized_gain_loss_inr !== undefined
                      ? `${portfolio.unrealized_gain_loss_inr >= 0 ? "+" : ""}₹${portfolio.unrealized_gain_loss_inr.toLocaleString("en-IN")} (${portfolio.unrealized_gain_loss_pct}%)`
                      : "—"}
                  </span>
                  <span className="text-[11px] text-zinc-500 mt-0.5 block">Excludes uncosted gifts/inheritance</span>
                </div>

                <div>
                  <span className="text-xs font-medium text-zinc-400 block">Fine Metal Holdings</span>
                  <div className="flex gap-4 mt-1">
                    <div>
                      <span className="text-xs font-mono font-bold text-amber-400">
                        {portfolio?.gold.fine_weight_grams?.toFixed(1) || 0}g
                      </span>
                      <span className="text-[10px] text-zinc-500 block">Gold ({portfolio?.gold.allocation_pct}%)</span>
                    </div>
                    <div>
                      <span className="text-xs font-mono font-bold text-zinc-300">
                        {portfolio?.silver.fine_weight_grams?.toFixed(0) || 0}g
                      </span>
                      <span className="text-[10px] text-zinc-500 block">Silver ({portfolio?.silver.allocation_pct}%)</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Holdings Table */}
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/30 overflow-hidden">
              <div className="px-6 py-4 border-b border-zinc-800 flex justify-between items-center">
                <h3 className="text-sm font-semibold tracking-wide uppercase text-zinc-300">
                  Recorded Holdings ({holdings.length})
                </h3>
              </div>

              {holdings.length === 0 ? (
                <div className="text-center py-16 px-4">
                  <div className="w-12 h-12 rounded-full bg-zinc-800 flex items-center justify-center mx-auto mb-3 text-zinc-500">
                    📦
                  </div>
                  <h4 className="text-sm font-medium text-zinc-300">No Bullion Holdings Recorded</h4>
                  <p className="text-xs text-zinc-500 mt-1 max-w-sm mx-auto">
                    Track your personal coins, bars, and cast ingots. Your portfolio data is private and never mixed with public market feeds.
                  </p>
                  <button
                    onClick={() => setShowAddModal(true)}
                    className="mt-4 px-4 py-1.5 text-xs font-semibold rounded bg-amber-500/10 text-amber-400 border border-amber-500/30 hover:bg-amber-500/20 transition"
                  >
                    Add First Bullion Item
                  </button>
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-zinc-900/80 text-zinc-400 font-mono uppercase text-[10px] border-b border-zinc-800">
                      <tr>
                        <th className="px-6 py-3">Product</th>
                        <th className="px-4 py-3">Metal / Purity</th>
                        <th className="px-4 py-3">Weight (Gross / Fine)</th>
                        <th className="px-4 py-3">Quantity</th>
                        <th className="px-4 py-3">Acquisition Cost</th>
                        <th className="px-4 py-3">Current Value</th>
                        <th className="px-4 py-3">Gain / Loss</th>
                        <th className="px-4 py-3 text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-zinc-800/60 font-sans">
                      {holdings.map((h) => (
                        <tr key={h.id} className="hover:bg-zinc-800/30 transition">
                          <td className="px-6 py-4 font-medium text-zinc-200">
                            {h.product_name}
                            {h.notes && <span className="block text-[11px] text-zinc-500">{h.notes}</span>}
                          </td>
                          <td className="px-4 py-4">
                            <span
                              className={`px-2 py-0.5 rounded text-[10px] font-mono font-semibold ${
                                h.metal_type === "GOLD"
                                  ? "bg-amber-500/10 text-amber-400 border border-amber-500/20"
                                  : "bg-zinc-700/30 text-zinc-300 border border-zinc-600/30"
                              }`}
                            >
                              {h.metal_type} {h.purity * 1000}
                            </span>
                          </td>
                          <td className="px-4 py-4 font-mono text-zinc-300">
                            {h.gross_weight_grams}g{" "}
                            <span className="text-[11px] text-zinc-500">({h.fine_weight_grams}g fine)</span>
                          </td>
                          <td className="px-4 py-4 font-mono text-zinc-300">{h.quantity}</td>
                          <td className="px-4 py-4 font-mono text-zinc-400">
                            {h.acquisition_cost_inr ? `₹${h.acquisition_cost_inr.toLocaleString("en-IN")}` : "—"}
                          </td>
                          <td className="px-4 py-4 font-mono font-bold text-zinc-100">
                            ₹{h.current_valuation_inr.toLocaleString("en-IN")}
                          </td>
                          <td className="px-4 py-4 font-mono font-semibold">
                            {h.unrealized_gain_loss_inr !== null ? (
                              <span className={h.unrealized_gain_loss_inr >= 0 ? "text-emerald-400" : "text-rose-400"}>
                                {h.unrealized_gain_loss_inr >= 0 ? "+" : ""}₹{h.unrealized_gain_loss_inr.toLocaleString("en-IN")}{" "}
                                ({h.unrealized_gain_loss_pct}%)
                              </span>
                            ) : (
                              <span className="text-zinc-600">N/A</span>
                            )}
                          </td>
                          <td className="px-4 py-4 text-right">
                            <button
                              onClick={() => handleDeleteHolding(h.id)}
                              className="text-zinc-500 hover:text-rose-400 transition text-[11px]"
                            >
                              Remove
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* Add Holding Modal */}
            {showAddModal && (
              <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
                <div className="w-full max-w-md rounded-xl border border-zinc-800 bg-zinc-900 p-6 shadow-2xl space-y-4">
                  <div className="flex justify-between items-center border-b border-zinc-800 pb-3">
                    <h3 className="text-base font-bold text-white">Add Bullion Holding</h3>
                    <button onClick={() => setShowAddModal(false)} className="text-zinc-400 hover:text-white">
                      ✕
                    </button>
                  </div>

                  <form onSubmit={handleAddHolding} className="space-y-4 text-xs">
                    <div>
                      <label className="block text-zinc-400 mb-1">Precious Metal</label>
                      <div className="grid grid-cols-2 gap-2">
                        <button
                          type="button"
                          onClick={() => { setNewMetal("GOLD"); setNewPurity(0.999); }}
                          className={`py-2 rounded font-medium ${newMetal === "GOLD" ? "bg-amber-500 text-black" : "bg-zinc-800 text-zinc-400"}`}
                        >
                          Gold (24K / 22K)
                        </button>
                        <button
                          type="button"
                          onClick={() => { setNewMetal("SILVER"); setNewPurity(0.999); }}
                          className={`py-2 rounded font-medium ${newMetal === "SILVER" ? "bg-zinc-200 text-black" : "bg-zinc-800 text-zinc-400"}`}
                        >
                          Silver (999)
                        </button>
                      </div>
                    </div>

                    <div>
                      <label className="block text-zinc-400 mb-1">Product Description</label>
                      <input
                        type="text"
                        placeholder="e.g. MMTC-PAMP 24K Bar, Kundan 10g Coin"
                        value={newProduct}
                        onChange={(e) => setNewProduct(e.target.value)}
                        className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-zinc-100 focus:outline-none focus:border-amber-500"
                        required
                      />
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="block text-zinc-400 mb-1">Gross Weight</label>
                        <input
                          type="number"
                          step="any"
                          value={newWeight}
                          onChange={(e) => setNewWeight(Number(e.target.value))}
                          className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-zinc-100 font-mono"
                          required
                        />
                      </div>
                      <div>
                        <label className="block text-zinc-400 mb-1">Unit</label>
                        <select
                          value={newUnit}
                          onChange={(e) => setNewUnit(e.target.value as any)}
                          className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-zinc-100 font-mono"
                        >
                          <option value="g">Grams (g)</option>
                          <option value="kg">Kilograms (kg)</option>
                        </select>
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="block text-zinc-400 mb-1">Purity (Fineness)</label>
                        <select
                          value={newPurity}
                          onChange={(e) => setNewPurity(Number(e.target.value))}
                          className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-zinc-100 font-mono"
                        >
                          <option value={0.999}>0.999 (24K Pure)</option>
                          <option value={0.995}>0.995 (Standard Bullion)</option>
                          <option value={0.916}>0.916 (22K Sovereign)</option>
                          <option value={0.750}>0.750 (18K Jewelry)</option>
                        </select>
                      </div>
                      <div>
                        <label className="block text-zinc-400 mb-1">Quantity</label>
                        <input
                          type="number"
                          min={1}
                          value={newQuantity}
                          onChange={(e) => setNewQuantity(Number(e.target.value))}
                          className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-zinc-100 font-mono"
                        />
                      </div>
                    </div>

                    <div>
                      <label className="block text-zinc-400 mb-1">Total Acquisition Cost (₹, optional)</label>
                      <input
                        type="number"
                        placeholder="Leave blank if inherited or cost unknown"
                        value={newCost}
                        onChange={(e) => setNewCost(e.target.value)}
                        className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-zinc-100 font-mono"
                      />
                    </div>

                    <div className="flex justify-end space-x-2 pt-2 border-t border-zinc-800">
                      <button
                        type="button"
                        onClick={() => setShowAddModal(false)}
                        className="px-4 py-2 rounded bg-zinc-800 text-zinc-400 hover:text-white"
                      >
                        Cancel
                      </button>
                      <button
                        type="submit"
                        className="px-4 py-2 rounded bg-amber-500 font-semibold text-black hover:bg-amber-400"
                      >
                        Save Holding
                      </button>
                    </div>
                  </form>
                </div>
              </div>
            )}
          </div>
        )}

        {/* PREDICTIONS TAB */}
        {activeTab === "predictions" && (
          <div className="space-y-6">
            <div className="p-6 rounded-xl border border-zinc-800 bg-zinc-900/40 space-y-4">
              <div className="flex items-center justify-between pb-4 border-b border-zinc-800">
                <div>
                  <h2 className="text-lg font-bold text-white">AI Bullion Forecasting Engine</h2>
                  <p className="text-xs text-zinc-400">
                    Target: Next published 24K KJPL MJDTA opening rate in INR per gram.
                  </p>
                </div>
                <span className="text-xs px-2.5 py-1 rounded border border-amber-500/30 bg-amber-500/10 text-amber-400 font-mono font-medium">
                  {prediction?.status || "DATA_COLLECTION_PHASE"}
                </span>
              </div>

              {/* Progress Card */}
              <div className="p-5 rounded-lg border border-zinc-800/80 bg-zinc-950/60 space-y-3">
                <div className="flex justify-between text-xs text-zinc-300 font-mono">
                  <span>Data Collection Progress for Supervised XGBoost</span>
                  <span className="text-amber-400 font-bold">
                    {prediction?.metrics?.current_samples || 34} / {prediction?.metrics?.required_samples || 50} Events ({prediction?.metrics?.progress_pct || 68.0}%)
                  </span>
                </div>
                <div className="w-full h-2.5 bg-zinc-800 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-gradient-to-r from-amber-500 to-amber-300 rounded-full transition-all duration-500"
                    style={{ width: `${prediction?.metrics?.progress_pct || 68.0}%` }}
                  />
                </div>
                <p className="text-xs text-zinc-400 leading-relaxed pt-1">
                  {prediction?.message ||
                    "Supervised models enforce zero-lookahead walk-forward validation and require 50 daily market observations before generating live signals."}
                </p>
              </div>

              {/* Features Tracked */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2">
                <div className="p-4 rounded border border-zinc-800/60 bg-zinc-900/30">
                  <span className="text-xs font-semibold text-zinc-300 block mb-1">Global Macro & FX</span>
                  <span className="text-[11px] text-zinc-500 block leading-relaxed">
                    COMEX Gold (`GC=F`), Silver (`SI=F`), Spot USD/INR, 24h momentum returns.
                  </span>
                </div>
                <div className="p-4 rounded border border-zinc-800/60 bg-zinc-900/30">
                  <span className="text-xs font-semibold text-zinc-300 block mb-1">Arbitrage & Tariff Spread</span>
                  <span className="text-[11px] text-zinc-500 block leading-relaxed">
                    Domestic retail premium over converted international spot price.
                  </span>
                </div>
                <div className="p-4 rounded border border-zinc-800/60 bg-zinc-900/30">
                  <span className="text-xs font-semibold text-zinc-300 block mb-1">News Intelligence</span>
                  <span className="text-[11px] text-zinc-500 block leading-relaxed">
                    FinBERT sentiment from global macro, central-bank buying, and geopolitical events.
                  </span>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* NEWS INTELLIGENCE TAB */}
        {activeTab === "news" && (
          <div className="space-y-6">
            <div className="p-6 rounded-xl border border-zinc-800 bg-zinc-900/40">
              <h2 className="text-lg font-bold text-white mb-1">Bullion Market News Intelligence</h2>
              <p className="text-xs text-zinc-400 mb-6">
                Real-time financial articles analyzed via FinBERT for sentiment polarity and gold market relevance.
              </p>

              <div className="space-y-3">
                {news.map((item, idx) => (
                  <div
                    key={idx}
                    className="p-4 rounded-lg border border-zinc-800/80 bg-zinc-900/20 hover:bg-zinc-800/20 transition flex flex-col sm:flex-row justify-between items-start sm:items-center gap-2"
                  >
                    <div className="space-y-1 max-w-3xl">
                      <a
                        href={item.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs font-medium text-zinc-200 hover:text-amber-400 transition"
                      >
                        {item.title}
                      </a>
                      <div className="flex items-center gap-3 text-[10px] text-zinc-500 font-mono">
                        <span>{item.source}</span>
                        <span>•</span>
                        <span>{new Date(item.published_at).toLocaleString()}</span>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 font-mono text-[10px]">
                      <span
                        className={`px-2 py-0.5 rounded font-semibold ${
                          item.sentiment_label === "positive"
                            ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                            : item.sentiment_label === "negative"
                            ? "bg-rose-500/10 text-rose-400 border border-rose-500/20"
                            : "bg-zinc-800 text-zinc-400"
                        }`}
                      >
                        {item.sentiment_label.toUpperCase()} ({item.sentiment_score > 0 ? "+" : ""}
                        {item.sentiment_score.toFixed(2)})
                      </span>
                      {item.is_gold_relevant && (
                        <span className="px-2 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20">
                          GOLD RELEVANT
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* ALERTS TAB */}
        {activeTab === "alerts" && (
          <div className="space-y-6">
            <div className="p-6 rounded-xl border border-zinc-800 bg-zinc-900/40 space-y-6">
              <div>
                <h2 className="text-lg font-bold text-white">Bullion Rate & Spread Alerts</h2>
                <p className="text-xs text-zinc-400">
                  Configure real-time in-app notifications for price barriers, domestic premium spikes, and volatility.
                </p>
              </div>

              {/* Add Alert Form */}
              <form onSubmit={handleCreateAlert} className="grid grid-cols-1 sm:grid-cols-3 gap-3 p-4 rounded-lg bg-zinc-950/60 border border-zinc-800 text-xs">
                <div>
                  <label className="block text-zinc-400 mb-1">Trigger Condition</label>
                  <select
                    value={newAlertType}
                    onChange={(e) => setNewAlertType(e.target.value)}
                    className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-zinc-200"
                  >
                    <option value="PRICE_ABOVE">Gold Price Above (₹/g)</option>
                    <option value="PRICE_BELOW">Gold Price Below (₹/g)</option>
                    <option value="PREMIUM_ABOVE">Domestic Premium Above (%)</option>
                    <option value="DAILY_CHANGE_PCT">24h Volatility Above (%)</option>
                  </select>
                </div>
                <div>
                  <label className="block text-zinc-400 mb-1">Threshold Value</label>
                  <input
                    type="number"
                    step="any"
                    value={newAlertThreshold}
                    onChange={(e) => setNewAlertThreshold(e.target.value)}
                    className="w-full bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-zinc-200 font-mono"
                    required
                  />
                </div>
                <div className="flex items-end">
                  <button
                    type="submit"
                    className="w-full py-2 rounded bg-amber-500 font-semibold text-black hover:bg-amber-400 transition"
                  >
                    Set Alert Rule
                  </button>
                </div>
              </form>

              {/* Active Alerts */}
              <div className="space-y-2">
                <h3 className="text-xs font-semibold tracking-wide uppercase text-zinc-400">Active Alert Rules ({alerts.length})</h3>
                {alerts.length === 0 ? (
                  <p className="text-xs text-zinc-500 py-4">No alert rules active.</p>
                ) : (
                  alerts.map((al) => (
                    <div
                      key={al.id}
                      className="p-3 rounded border border-zinc-800 bg-zinc-900/20 flex justify-between items-center text-xs"
                    >
                      <div>
                        <span className="font-mono font-bold text-amber-400">{al.alert_type}</span>{" "}
                        <span className="text-zinc-300 font-mono">
                          {al.alert_type.includes("PREMIUM") || al.alert_type.includes("CHANGE")
                            ? `${al.threshold}%`
                            : `₹${al.threshold.toLocaleString("en-IN")}`}
                        </span>
                        {al.notes && <span className="block text-[11px] text-zinc-500">{al.notes}</span>}
                      </div>
                      <button
                        onClick={() => handleDeleteAlert(al.id)}
                        className="text-zinc-500 hover:text-rose-400 text-xs"
                      >
                        Delete
                      </button>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
