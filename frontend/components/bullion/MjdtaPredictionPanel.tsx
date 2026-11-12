"use client";

import React, { useEffect, useState } from "react";
import { apiUrl } from "../../lib/api";

interface ShadowForecastItem {
  forecast_id: string;
  generation_mode?: string;
  model_version?: string;
  arm: string;
  horizon_publications: number;
  origin_observed_at: string;
  origin_price_inr_per_g: number;
  predicted_log_return: number | null;
  predicted_price_inr_per_g: number | null;
  predicted_direction: string;
  up_probability: number | null;
  status: string;
  coverage_ok: boolean;
}

interface ArmMetricBucket {
  status: string;
  sample_count: number;
  min_required_samples: number;
  mae_inr_per_g: number | null;
  rmse_inr_per_g: number | null;
  directional_accuracy: number | null;
  brier_score: number | null;
}

interface DieboldMarianoResult {
  status: string;
  n: number;
  min_required: number;
  dm_stat: number | null;
  p_value_two_sided: number | null;
  df?: number;
}

interface HorizonEvaluation {
  horizon_publications: number;
  paired_comparable_count: number;
  arms: Record<
    string,
    {
      all_valid_origins: ArmMetricBucket;
      paired_comparable_origins: ArmMetricBucket;
      non_overlapping_paired: ArmMetricBucket;
    }
  >;
  diebold_mariano: {
    hybrid_vs_price_only: DieboldMarianoResult;
    hybrid_vs_no_change: DieboldMarianoResult;
    price_only_vs_no_change?: DieboldMarianoResult;
  };
}

interface MjdtaShadowPayload {
  protocol_version: string;
  model_version?: string;
  status: string;
  backtest_status?: string;
  target_spec?: {
    product_key: string;
    tax_basis: string;
    purity: number;
    unit: string;
  };
  eligible_publications: number;
  verified_news_coverage_origins: number;
  min_evaluation_samples: number;
  prospective_ledger?: {
    generation_mode: string;
    status: string;
    total_prospective_origins: number;
    matured_prospective_origins: number;
    min_evaluation_samples: number;
    latest_prospective_forecasts: ShadowForecastItem[];
  };
  latest_snapshot?: {
    snapshot_id: string;
    cutoff_time: string;
    origin_observed_at: string;
    origin_gold_price_inr_per_g: number;
    n_clusters_relevant: number;
    net_impact: number | null;
    unknown_share: number | null;
    coverage_ok: boolean;
  } | null;
  latest_forecasts: ShadowForecastItem[];
  backtest_latest_forecasts?: ShadowForecastItem[];
  metrics_by_horizon: Record<string, HorizonEvaluation>;
  mjdta_audit?: {
    total_raw_rows: number;
    eligible_publications: number;
    excluded_observations: number;
    source_backend?: string;
  };
}

export function MjdtaPredictionPanel() {
  const [payload, setPayload] = useState<MjdtaShadowPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    fetch(apiUrl("/api/predictions/research-shadow"), { cache: "no-store" })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((json: MjdtaShadowPayload) => {
        if (active) setPayload(json);
      })
      .catch((err) => {
        if (active) setError(String(err));
      });
    return () => {
      active = false;
    };
  }, []);

  if (error) {
    return (
      <div className="bg-[#111820] border border-red-500/30 rounded-lg p-5 font-mono text-xs text-red-400">
        MJDTA Research Endpoint Unavailable (fail-closed): {error}
      </div>
    );
  }

  if (!payload) {
    return (
      <div className="bg-[#111820] border border-[#25313D] rounded-lg p-5 font-mono text-xs text-[#8B98A5]">
        Loading MJDTA Research Engine (`EXPERIMENT_PROTOCOL_V1`)...
      </div>
    );
  }

  const snap = payload.latest_snapshot;
  const prosp = payload.prospective_ledger;
  const isProspectiveReady = prosp?.status === "READY_FOR_COMPARATIVE_EVAL";
  const hasProspectiveForecasts = (payload.latest_forecasts?.length ?? 0) > 0;
  const activeModeLabel = hasProspectiveForecasts ? "PROSPECTIVE LEDGER" : "NO PROSPECTIVE FORECASTS YET";

  return (
    <div className="bg-[#111820] border border-[#25313D] rounded-lg p-5 space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-[#25313D] pb-3">
        <div>
          <span className="text-[10px] font-mono uppercase text-[#D6A84F] font-bold tracking-wider">
            SYSTEM B — MJDTA RESEARCH TERMINAL ({payload.protocol_version} / {payload.model_version || "RIDGE_STD_V1"})
          </span>
          <h2 className="text-base sm:text-lg font-bold text-white mt-0.5">
            MJDTA 24K Research: Prospective Ledger vs Historical Backtest
          </h2>
          <p className="text-xs text-[#8B98A5] mt-1">
            Target: <span className="text-white font-mono">{payload.target_spec?.product_key || "MJDTA_GOLD_24K"}</span>{" "}
            ({payload.target_spec?.tax_basis || "EXCL_GST"}, purity {payload.target_spec?.purity ?? 0.999}, INR/1g) via{" "}
            <span className="font-mono text-white">{payload.mjdta_audit?.source_backend || "database"}</span>. Strictly isolated
            from 5-city live retail rates and external spot feeds.
          </p>
        </div>

        <div className="flex flex-col items-end gap-1">
          <span
            className={`px-2.5 py-1 rounded text-[11px] font-mono font-bold border ${
              !isProspectiveReady
                ? "bg-amber-500/10 text-amber-300 border-amber-500/30"
                : "bg-emerald-500/10 text-emerald-300 border-emerald-500/30"
            }`}
          >
            PROSPECTIVE: {prosp?.status || payload.status}
          </span>
          <span className="text-[10px] font-mono text-[#8B98A5]">
            Active Table Mode: {activeModeLabel}
          </span>
        </div>
      </div>

      {!isProspectiveReady && (
        <div className="p-3.5 rounded bg-amber-950/30 border border-amber-500/30 text-xs text-amber-200 space-y-1">
          <div className="font-mono font-bold text-amber-300">
            PROSPECTIVE EVALUATION GATE ACTIVE ({prosp?.matured_prospective_origins ?? 0} / {payload.min_evaluation_samples} Matured Prospective Origins)
          </div>
          <p className="text-[#CBD5E1]">
            DB Eligible MJDTA Publications: <span className="font-mono text-white">{payload.eligible_publications}</span>{" "}
            | Prospective Origins Logged: <span className="font-mono text-white">{prosp?.total_prospective_origins ?? 0}</span>.
            No statistically valid prospective claims are issued until at least {payload.min_evaluation_samples} matured
            prospective forecast pairs exist with verified stored news labels.
          </p>
        </div>
      )}

      {snap && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 font-mono text-xs">
          <div className="p-3 rounded bg-[#0D1218] border border-[#25313D]">
            <span className="text-[10px] text-[#8B98A5] block">ORIGIN MJDTA 24K (EXCL. GST)</span>
            <span className="text-lg font-bold text-white">₹{snap.origin_gold_price_inr_per_g.toFixed(2)}/g</span>
            <span className="text-[10px] text-zinc-500 block truncate">{snap.origin_observed_at}</span>
          </div>
          <div className="p-3 rounded bg-[#0D1218] border border-[#25313D]">
            <span className="text-[10px] text-[#8B98A5] block">VERIFIED NEWS COVERAGE</span>
            <span className="text-lg font-bold text-white">{snap.n_clusters_relevant} clusters</span>
            <span className="text-[10px] text-zinc-500 block">
              Status: {snap.coverage_ok ? "COVERAGE_OK" : "UNAVAILABLE (MISSING/FAILED)"}
            </span>
          </div>
          <div className="p-3 rounded bg-[#0D1218] border border-[#25313D]">
            <span className="text-[10px] text-[#8B98A5] block">STORED-LABEL NET IMPACT</span>
            <span className="text-lg font-bold text-[#D6A84F]">
              {snap.net_impact !== null && snap.net_impact !== undefined
                ? `${snap.net_impact >= 0 ? "+" : ""}${snap.net_impact.toFixed(4)}`
                : "UNAVAILABLE"}
            </span>
            <span className="text-[10px] text-zinc-500 block">Point-in-time `label_created_at &lt;= T`</span>
          </div>
          <div className="p-3 rounded bg-[#0D1218] border border-[#25313D]">
            <span className="text-[10px] text-[#8B98A5] block">AMBIGUOUS / UNKNOWN SHARE</span>
            <span className="text-lg font-bold text-white">
              {snap.unknown_share !== null && snap.unknown_share !== undefined
                ? `${(snap.unknown_share * 100).toFixed(1)}%`
                : "UNAVAILABLE"}
            </span>
            <span className="text-[10px] text-zinc-500 block">Never defaults missing news to 0.0</span>
          </div>
        </div>
      )}

      <div className="space-y-2">
        <h3 className="text-xs font-mono uppercase text-[#8B98A5] font-bold">
          Latest Frontier Arm Outputs ({activeModeLabel})
        </h3>
        {payload.latest_forecasts.length === 0 ? (
          <div className="text-xs font-mono text-[#8B98A5] p-3 bg-[#0D1218] rounded border border-[#25313D]">
            No frontier forecasts available yet from database observations.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse font-mono text-xs">
              <thead>
                <tr className="border-b border-[#25313D] text-[#8B98A5] text-[10px]">
                  <th className="py-2 pr-3">MODE</th>
                  <th className="py-2 pr-3">HORIZON</th>
                  <th className="py-2 pr-3">ARM</th>
                  <th className="py-2 pr-3">PRED LOG RET</th>
                  <th className="py-2 pr-3">PRED MJDTA (INR/g)</th>
                  <th className="py-2 pr-3">DIRECTION</th>
                  <th className="py-2 pr-3">RAW SCORE (UNCALIBRATED)</th>
                  <th className="py-2">ARM STATUS</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#1E293B]">
                {payload.latest_forecasts.map((fc) => (
                  <tr key={fc.forecast_id} className="hover:bg-[#0D1218]">
                    <td className="py-2 pr-3 text-[10px] text-[#8B98A5]">{fc.generation_mode || "BACKTEST"}</td>
                    <td className="py-2 pr-3 text-white">h={fc.horizon_publications} pub</td>
                    <td className="py-2 pr-3 font-bold text-[#D6A84F]">{fc.arm}</td>
                    <td className="py-2 pr-3 text-white">
                      {fc.predicted_log_return !== null
                        ? `${fc.predicted_log_return >= 0 ? "+" : ""}${(fc.predicted_log_return * 100).toFixed(3)}%`
                        : "N/A"}
                    </td>
                    <td className="py-2 pr-3 text-white">
                      {fc.predicted_price_inr_per_g !== null ? `₹${fc.predicted_price_inr_per_g.toFixed(2)}` : "N/A"}
                    </td>
                    <td className="py-2 pr-3">
                      <span
                        className={`px-1.5 py-0.5 rounded text-[10px] ${
                          fc.predicted_direction === "UP"
                            ? "bg-emerald-500/15 text-emerald-300"
                            : fc.predicted_direction === "DOWN"
                              ? "bg-rose-500/15 text-rose-300"
                              : "bg-zinc-700/40 text-zinc-300"
                        }`}
                      >
                        {fc.predicted_direction}
                      </span>
                    </td>
                    <td className="py-2 pr-3 text-[#CBD5E1]">
                      {fc.up_probability !== null ? `${(fc.up_probability * 100).toFixed(1)}%` : "N/A"}
                    </td>
                    <td className="py-2 text-[10px] text-[#8B98A5]">{fc.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {payload.metrics_by_horizon?.h1 && (
        <div className="space-y-2 border-t border-[#25313D] pt-4">
          <h3 className="text-xs font-mono uppercase text-[#8B98A5] font-bold">
            Comparable-Origin Evaluation ({payload.backtest_status || "BACKTEST"} — h=1 Common Origins N={payload.metrics_by_horizon.h1.paired_comparable_count})
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse font-mono text-xs">
              <thead>
                <tr className="border-b border-[#25313D] text-[#8B98A5] text-[10px]">
                  <th className="py-2 pr-3">ARM</th>
                  <th className="py-2 pr-3">PAIRED N</th>
                  <th className="py-2 pr-3">ALL VALID N</th>
                  <th className="py-2 pr-3">PAIRED MAE (INR/g)</th>
                  <th className="py-2 pr-3">PAIRED RMSE (INR/g)</th>
                  <th className="py-2 pr-3">DIR ACC</th>
                  <th className="py-2">BRIER</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#1E293B]">
                {Object.entries(payload.metrics_by_horizon.h1.arms).map(([arm, splits]) => {
                  const paired = splits.paired_comparable_origins;
                  const allv = splits.all_valid_origins;
                  return (
                    <tr key={arm}>
                      <td className="py-1.5 pr-3 font-bold text-white">{arm}</td>
                      <td className="py-1.5 pr-3 text-[#CBD5E1]">{paired.sample_count}</td>
                      <td className="py-1.5 pr-3 text-[#8B98A5]">{allv.sample_count}</td>
                      <td className="py-1.5 pr-3 text-[#CBD5E1]">
                        {paired.mae_inr_per_g !== null ? `₹${paired.mae_inr_per_g.toFixed(2)}` : "N/A"}
                      </td>
                      <td className="py-1.5 pr-3 text-[#CBD5E1]">
                        {paired.rmse_inr_per_g !== null ? `₹${paired.rmse_inr_per_g.toFixed(2)}` : "N/A"}
                      </td>
                      <td className="py-1.5 pr-3 text-[#CBD5E1]">
                        {paired.directional_accuracy !== null ? `${(paired.directional_accuracy * 100).toFixed(1)}%` : "N/A"}
                      </td>
                      <td className="py-1.5 text-[#CBD5E1]">
                        {paired.brier_score !== null ? paired.brier_score.toFixed(4) : "N/A"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="text-[11px] font-mono text-[#8B98A5]">
            DM HLN Student-t (HYBRID vs PRICE_ONLY):{" "}
            <span className="text-white">
              {payload.metrics_by_horizon.h1.diebold_mariano.hybrid_vs_price_only.status}
            </span>{" "}
            (n={payload.metrics_by_horizon.h1.diebold_mariano.hybrid_vs_price_only.n} / min{" "}
            {payload.metrics_by_horizon.h1.diebold_mariano.hybrid_vs_price_only.min_required})
          </p>
        </div>
      )}
    </div>
  );
}
