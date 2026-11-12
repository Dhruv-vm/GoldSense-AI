from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import math
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import t as scipy_t
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.db.session as db_session
from app.models.bullion import BullionRateObservation
from app.models.research import (
    ForecastEvaluation,
    ForecastEvaluationReassessment,
    ForecastRun,
    ResearchFeatureSnapshot,
)
from app.services.prediction.protocol import (
    ProtocolIntegrityError,
    verify_runtime_protocol,
)
from app.services.prediction.mjdta_series import (
    MJDTA_SPEC,
    MjdtaObservation,
    load_and_audit_mjdta_series,
    load_mjdta_observations_from_db,
)
from app.services.prediction.news_features import (
    CutoffNewsFeatures,
    EligibleNewsRecord,
    compute_news_features_at_cutoff,
    load_eligible_news_records_from_db,
)
from app.services.sentiment.provenance import CLUSTER_VERSION, SENTIMENT_VERSION, parse_utc_iso

PROTOCOL_VERSION = "EXPERIMENT_PROTOCOL_V1"
MODEL_VERSION = "RIDGE_STD_V1"
ARMS = ("NO_CHANGE", "PRICE_ONLY", "NEWS_ONLY", "HYBRID")
HORIZONS = (1, 3)
MIN_TRAINING_ORIGINS = 10
MIN_EVALUATION_SAMPLES = 30
MIN_DM_SAMPLES = 20
FLAT_RETURN_THRESHOLD = 0.0005  # ~5 bps
RIDGE_ALPHA = 5.0


@dataclass(frozen=True)
class ShadowForecastRecord:
    forecast_id: str
    protocol_version: str
    generation_mode: str  # "BACKTEST" | "PROSPECTIVE"
    model_version: str
    arm: str
    horizon_publications: int
    generated_at: str
    cutoff_time: str
    origin_observation_id: int | None
    origin_observed_at: str
    origin_price_inr_per_g: float
    target_observation_id: int | None
    target_observed_at: str | None
    snapshot_id: str
    feature_hash: str
    predicted_log_return: float | None
    predicted_price_inr_per_g: float | None
    predicted_direction: str
    up_probability: float | None
    status: str
    coverage_ok: bool
    is_immutable: bool = True
    protocol_sha256: str | None = None
    origin_source_published_at: str | None = None


@dataclass(frozen=True)
class EvaluatedForecastRecord:
    forecast_id: str
    generation_mode: str
    arm: str
    horizon_publications: int
    origin_observed_at: str
    target_observation_id: int | None
    matured_observed_at: str
    actual_price_inr_per_g: float
    actual_log_return: float
    actual_direction: str
    abs_error_log_return: float | None
    sq_error_log_return: float | None
    abs_error_inr_per_g: float | None
    direction_correct: bool | None
    brier_score: float | None
    is_non_overlapping_origin: bool


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _classify_direction(log_ret: float) -> str:
    if log_ret > FLAT_RETURN_THRESHOLD:
        return "UP"
    if log_ret < -FLAT_RETURN_THRESHOLD:
        return "DOWN"
    return "FLAT"


def _sigmoid(x: float) -> float:
    clamped = max(-12.0, min(12.0, x))
    return 1.0 / (1.0 + math.exp(-clamped))


def _make_snapshot_id(
    generation_mode: str,
    cutoff_iso: str,
    origin_iso: str,
    feature_hash: str = "",
) -> str:
    # For PROSPECTIVE snapshots, key by (generation_mode, origin_iso, feature_hash) so
    # repeated polling cycles at the same frontier origin reuse the identical snapshot instead
    # of inserting orphan duplicate snapshot rows (NEW-7).
    anchor = feature_hash or cutoff_iso
    digest = hashlib.sha256(
        f"{PROTOCOL_VERSION}|{generation_mode}|{origin_iso}|{anchor}".encode("utf-8")
    ).hexdigest()[:16]
    return f"snap_{digest}"


def _make_forecast_id(
    generation_mode: str,
    arm: str,
    horizon: int,
    origin_iso: str,
    model_version: str = MODEL_VERSION,
) -> str:
    digest = hashlib.sha256(
        f"{PROTOCOL_VERSION}|{generation_mode}|{model_version}|{arm}|{horizon}|{origin_iso}".encode("utf-8")
    ).hexdigest()[:16]
    return f"fc_{digest}"


def build_mjdta_price_features(eligible_obs: list[MjdtaObservation], origin_idx: int) -> dict[str, float]:
    """
    Build strictly point-in-time MJDTA domestic price features using ONLY
    observations `0..origin_idx` (`available_at_utc <= cutoff`).
    """
    prices = [o.gold_mjdta_inr_per_g for o in eligible_obs[: origin_idx + 1]]
    p_curr = prices[-1]

    def _lag_ret(lag: int) -> float:
        if len(prices) <= lag or prices[-1 - lag] <= 0:
            return 0.0
        return math.log(p_curr / prices[-1 - lag])

    step_rets = [
        math.log(prices[k] / prices[k - 1])
        for k in range(max(1, len(prices) - 5), len(prices))
        if prices[k - 1] > 0
    ]
    vol_5 = float(np.std(step_rets)) if len(step_rets) >= 2 else 0.0

    return {
        "ret_1": round(_lag_ret(1), 6),
        "ret_3": round(_lag_ret(3), 6),
        "ret_5": round(_lag_ret(5), 6),
        "vol_5": round(vol_5, 6),
    }


def _fit_and_predict_standardized_ridge(
    X_train: np.ndarray,
    y_train: np.ndarray,
    x_test: np.ndarray,
    alpha: float = RIDGE_ALPHA,
) -> tuple[float, float]:
    """
    F-08: Standardize features strictly within the training split `(mu_train, sigma_train)`
    before Ridge solve so scale differences between returns, counts, and ratios do not
    distort L2 shrinkage. Returns `(pred_log_return, up_score)` where `up_score` is a raw,
    UNCALIBRATED sigmoid of the prediction over training residual scale (not a probability).
    """
    mu = np.mean(X_train, axis=0)
    sigma = np.std(X_train, axis=0, ddof=0)
    active_mask = sigma > 1e-12
    sigma_safe = np.where(active_mask, sigma, 1.0)

    X_std = np.where(active_mask, (X_train - mu) / sigma_safe, 0.0)
    x_test_std = np.where(active_mask, (x_test - mu) / sigma_safe, 0.0)

    n_samples, n_features = X_std.shape
    X_aug = np.column_stack([np.ones(n_samples), X_std])
    reg = np.eye(n_features + 1) * alpha
    reg[0, 0] = 0.0  # Keep intercept unpenalized
    weights = np.linalg.solve(X_aug.T @ X_aug + reg, X_aug.T @ y_train)

    train_preds = X_aug @ weights
    residuals = y_train - train_preds
    res_scale = max(0.004, float(np.std(residuals, ddof=1)) if n_samples > 1 else 0.008)

    raw_pred = float(weights[0] + np.dot(weights[1:], x_test_std))
    pred_lr = max(-0.10, min(0.10, raw_pred))
    up_prob = max(0.05, min(0.95, _sigmoid(pred_lr / res_scale)))
    return pred_lr, up_prob


def compute_diebold_mariano(
    loss_a: list[float],
    loss_b: list[float],
    horizon: int,
    *,
    non_overlapping: bool = False,
) -> dict[str, Any]:
    """
    F-14: Paired Diebold-Mariano test with Harvey-Leybourne-Newbold (1997) finite-sample
    modification evaluated against Student's t-distribution (`df = n - 1`).
    - Rejects non-finite (NaN / Inf) loss inputs explicitly.
    - Distinguishes identical zero differential vs constant non-zero differential.
    - When `non_overlapping=True` on stride=h origins, errors do not overlap, so sets
      `effective_horizon = 1` (preventing double correction via HAC + HLN).
    """
    if len(loss_a) != len(loss_b):
        return {
            "status": "UNPAIRED_SAMPLE_MISMATCH",
            "n": min(len(loss_a), len(loss_b)),
            "min_required": MIN_DM_SAMPLES,
            "dm_stat": None,
            "p_value_two_sided": None,
        }

    n = len(loss_a)
    if n < MIN_DM_SAMPLES:
        return {
            "status": "INSUFFICIENT_SAMPLE",
            "n": n,
            "min_required": MIN_DM_SAMPLES,
            "dm_stat": None,
            "p_value_two_sided": None,
        }

    if any((not math.isfinite(float(loss_a[i]))) or (not math.isfinite(float(loss_b[i]))) for i in range(n)):
        return {
            "status": "INVALID_NON_FINITE_LOSS",
            "n": n,
            "min_required": MIN_DM_SAMPLES,
            "dm_stat": None,
            "p_value_two_sided": None,
        }

    d = np.array([float(loss_a[i]) - float(loss_b[i]) for i in range(n)], dtype=float)
    d_mean = float(np.mean(d))
    max_abs = float(np.max(np.abs(d)))
    d_std = float(np.std(d, ddof=0))

    if max_abs < 1e-12:
        return {
            "status": "DEGENERATE_IDENTICAL_PREDICTIONS",
            "n": n,
            "min_required": MIN_DM_SAMPLES,
            "dm_stat": None,
            "p_value_two_sided": None,
        }
    if d_std < 1e-12:
        return {
            "status": "DEGENERATE_CONSTANT_DIFFERENTIAL",
            "n": n,
            "min_required": MIN_DM_SAMPLES,
            "dm_stat": None,
            "p_value_two_sided": None,
        }

    d_centered = d - d_mean
    effective_h = 1 if non_overlapping else max(1, horizon)
    max_lag = max(0, effective_h - 1)
    gamma0 = float(np.dot(d_centered, d_centered) / n)
    var_lr = gamma0
    for lag in range(1, min(max_lag + 1, n)):
        weight = 1.0 - (lag / (max_lag + 1.0))
        cov = float(np.dot(d_centered[lag:], d_centered[:-lag]) / n)
        var_lr += 2.0 * weight * cov

    if var_lr <= 1e-18:
        return {
            "status": "DEGENERATE_NON_POSITIVE_HAC_VARIANCE",
            "n": n,
            "min_required": MIN_DM_SAMPLES,
            "dm_stat": None,
            "p_value_two_sided": None,
        }

    hln_num = n + 1.0 - 2.0 * effective_h + (effective_h * (effective_h - 1.0)) / n
    if hln_num <= 0.0:
        return {
            "status": "INSUFFICIENT_SAMPLE",
            "n": n,
            "min_required": MIN_DM_SAMPLES,
            "dm_stat": None,
            "p_value_two_sided": None,
        }

    se = math.sqrt(var_lr / n)
    dm_raw = d_mean / se
    dm_hln = dm_raw * math.sqrt(hln_num / n)
    p_val = float(2.0 * scipy_t.sf(abs(dm_hln), df=n - 1))

    return {
        "status": "COMPUTED_HLN_STUDENT_T",
        "n": n,
        "min_required": MIN_DM_SAMPLES,
        "dm_stat": round(dm_hln, 4),
        "p_value_two_sided": round(max(0.0, min(1.0, p_val)), 6),
        "df": n - 1,
        "effective_horizon": effective_h,
    }


def _aggregate_arm_metrics(
    evals: list[EvaluatedForecastRecord],
    *,
    non_overlapping_only: bool = False,
    allowed_origins: set[str] | None = None,
) -> dict[str, Any]:
    subset = [
        e
        for e in evals
        if e.abs_error_log_return is not None
        and (not non_overlapping_only or e.is_non_overlapping_origin)
        and (allowed_origins is None or e.origin_observed_at in allowed_origins)
    ]
    n = len(subset)
    if n == 0:
        return {
            "status": "INSUFFICIENT_SAMPLE",
            "sample_count": 0,
            "min_required_samples": MIN_EVALUATION_SAMPLES,
            "mae_log_return": None,
            "rmse_log_return": None,
            "mae_inr_per_g": None,
            "rmse_inr_per_g": None,
            "directional_accuracy": None,
            "brier_score": None,
        }

    mae_lr = sum(float(e.abs_error_log_return) for e in subset) / n
    rmse_lr = math.sqrt(sum(float(e.sq_error_log_return or 0.0) for e in subset) / n)
    mae_inr = sum(float(e.abs_error_inr_per_g or 0.0) for e in subset) / n
    rmse_inr = math.sqrt(sum(float(e.abs_error_inr_per_g or 0.0) ** 2 for e in subset) / n)
    dir_acc = sum(1 for e in subset if e.direction_correct) / n
    brier = sum(float(e.brier_score or 0.0) for e in subset) / n

    return {
        "status": "EVALUATED" if n >= MIN_EVALUATION_SAMPLES else "INSUFFICIENT_SAMPLE",
        "sample_count": n,
        "min_required_samples": MIN_EVALUATION_SAMPLES,
        "mae_log_return": round(mae_lr, 6),
        "rmse_log_return": round(rmse_lr, 6),
        "mae_inr_per_g": round(mae_inr, 2),
        "rmse_inr_per_g": round(rmse_inr, 2),
        "directional_accuracy": round(dir_acc, 4),
        "brier_score": round(brier, 4),
    }


def _build_news_vec(nf: CutoffNewsFeatures) -> list[float] | None:
    if not nf.coverage_ok or nf.net_impact is None or nf.unknown_share is None:
        return None
    return [
        float(nf.n_clusters_relevant),
        float(nf.net_impact),
        float(nf.unknown_share),
    ]


def _price_vec(pf: dict[str, float]) -> list[float]:
    return [pf["ret_1"], pf["ret_3"], pf["ret_5"], pf["vol_5"]]


def _emit_arm_forecasts_at_origin(
    *,
    eligible_obs: list[MjdtaObservation],
    origin_idx: int,
    news_features_by_idx: list[CutoffNewsFeatures],
    price_features_by_idx: list[dict[str, float]],
    snapshot_id: str,
    generation_mode: str,
    generated_at: datetime,
    cutoff_time: datetime,
    protocol_sha256: str | None = None,
) -> list[ShadowForecastRecord]:
    """Compute paired A/B/C/NO_CHANGE predictions at a single origin without heuristic fallbacks."""
    origin = eligible_obs[origin_idx]
    p0 = origin.gold_mjdta_inr_per_g
    nf = news_features_by_idx[origin_idx]
    pf = price_features_by_idx[origin_idx]
    nv_test = _build_news_vec(nf)
    pv_test = _price_vec(pf)
    origin_iso = origin.observed_at_utc.isoformat()
    origin_src_pub_iso = origin.source_published_at_utc.isoformat() if origin.source_published_at_utc else origin_iso
    cutoff_iso = _to_utc(cutoff_time).isoformat()
    gen_iso = _to_utc(generated_at).isoformat()

    records: list[ShadowForecastRecord] = []
    for h in HORIZONS:
        # Strictly gather prior training pairs j -> j + h with j + h <= origin_idx (no lookahead).
        X_price_train: list[list[float]] = []
        y_price_train: list[float] = []
        X_news_train: list[list[float]] = []
        y_news_train: list[float] = []
        X_hyb_train: list[list[float]] = []
        y_hyb_train: list[float] = []

        for j in range(5, origin_idx - h + 1):
            p_start = eligible_obs[j].gold_mjdta_inr_per_g
            p_end = eligible_obs[j + h].gold_mjdta_inr_per_g
            if p_start <= 0 or p_end <= 0:
                continue
            target_lr = math.log(p_end / p_start)
            pv_j = _price_vec(price_features_by_idx[j])
            X_price_train.append(pv_j)
            y_price_train.append(target_lr)

            nv_j = _build_news_vec(news_features_by_idx[j])
            if nv_j is not None:
                X_news_train.append(nv_j)
                y_news_train.append(target_lr)
                X_hyb_train.append(pv_j + nv_j)
                y_hyb_train.append(target_lr)

        arm_outputs: dict[str, tuple[float | None, float | None, str]] = {}

        # 0. NO_CHANGE baseline
        arm_outputs["NO_CHANGE"] = (0.0, 0.5, "ACTIVE")

        # A. PRICE_ONLY (requires >= MIN_TRAINING_ORIGINS)
        if len(y_price_train) >= MIN_TRAINING_ORIGINS:
            pred_lr, up_prob = _fit_and_predict_standardized_ridge(
                np.array(X_price_train, dtype=float),
                np.array(y_price_train, dtype=float),
                np.array(pv_test, dtype=float),
            )
            arm_outputs["PRICE_ONLY"] = (round(pred_lr, 6), round(up_prob, 4), "ACTIVE")
        else:
            arm_outputs["PRICE_ONLY"] = (None, None, "INSUFFICIENT_SAMPLE")

        # B & C. NEWS_ONLY & HYBRID (F-08, F-10: unavailable when coverage fails OR insufficient news training origins)
        if nv_test is None:
            arm_outputs["NEWS_ONLY"] = (None, None, "UNAVAILABLE_NO_NEWS_COVERAGE")
            arm_outputs["HYBRID"] = (None, None, "UNAVAILABLE_NO_NEWS_COVERAGE")
        elif len(y_news_train) < MIN_TRAINING_ORIGINS:
            arm_outputs["NEWS_ONLY"] = (None, None, "INSUFFICIENT_SAMPLE")
            arm_outputs["HYBRID"] = (None, None, "INSUFFICIENT_SAMPLE")
        else:
            pred_n, prob_n = _fit_and_predict_standardized_ridge(
                np.array(X_news_train, dtype=float),
                np.array(y_news_train, dtype=float),
                np.array(nv_test, dtype=float),
            )
            arm_outputs["NEWS_ONLY"] = (round(pred_n, 6), round(prob_n, 4), "ACTIVE")

            pred_h, prob_h = _fit_and_predict_standardized_ridge(
                np.array(X_hyb_train, dtype=float),
                np.array(y_hyb_train, dtype=float),
                np.array(pv_test + nv_test, dtype=float),
            )
            arm_outputs["HYBRID"] = (round(pred_h, 6), round(prob_h, 4), "ACTIVE")

        for arm in ARMS:
            pred_lr, up_prob, fc_status = arm_outputs[arm]
            if pred_lr is None:
                pred_price = None
                pred_dir = "UNAVAILABLE"
            else:
                pred_price = round(p0 * math.exp(pred_lr), 2)
                pred_dir = _classify_direction(pred_lr)
                if fc_status == "ACTIVE":
                    fc_status = (
                        "PROSPECTIVE_ACTIVE" if generation_mode == "PROSPECTIVE" else "BACKTEST_EVALUATED"
                    )

            records.append(
                ShadowForecastRecord(
                    forecast_id=_make_forecast_id(generation_mode, arm, h, origin_iso, MODEL_VERSION),
                    protocol_version=PROTOCOL_VERSION,
                    generation_mode=generation_mode,
                    model_version=MODEL_VERSION,
                    arm=arm,
                    horizon_publications=h,
                    generated_at=gen_iso,
                    cutoff_time=cutoff_iso,
                    origin_observation_id=origin.observation_id,
                    origin_observed_at=origin_iso,
                    origin_price_inr_per_g=p0,
                    target_observation_id=None,
                    target_observed_at=None,
                    snapshot_id=snapshot_id,
                    feature_hash=nf.feature_hash,
                    predicted_log_return=pred_lr,
                    predicted_price_inr_per_g=pred_price,
                    predicted_direction=pred_dir,
                    up_probability=up_prob,
                    status=fc_status,
                    coverage_ok=nf.coverage_ok,
                    is_immutable=True,
                    protocol_sha256=protocol_sha256,
                    origin_source_published_at=origin_src_pub_iso,
                )
            )
    return records


def summarize_evaluations_by_horizon(
    forecasts: list[ShadowForecastRecord],
    evaluations: list[EvaluatedForecastRecord],
) -> dict[str, Any]:
    """Compute F-09 comparable-origin metrics and F-14 HLN-corrected Student-t DM tests."""
    metrics_by_horizon: dict[str, Any] = {}
    for h in HORIZONS:
        h_evals = [e for e in evaluations if e.horizon_publications == h]
        valid_origins_by_arm = {
            arm: {
                e.origin_observed_at
                for e in h_evals
                if e.arm == arm and e.sq_error_log_return is not None
            }
            for arm in ARMS
        }
        # F-09: Common origins where ALL 4 experimental arms are valid & comparable
        common_all_arms = (
            valid_origins_by_arm["NO_CHANGE"]
            & valid_origins_by_arm["PRICE_ONLY"]
            & valid_origins_by_arm["NEWS_ONLY"]
            & valid_origins_by_arm["HYBRID"]
        )

        arm_summary: dict[str, Any] = {}
        for arm in ARMS:
            arm_evals = [e for e in h_evals if e.arm == arm]
            arm_summary[arm] = {
                "all_valid_origins": _aggregate_arm_metrics(arm_evals, non_overlapping_only=False),
                "paired_comparable_origins": _aggregate_arm_metrics(
                    arm_evals, non_overlapping_only=False, allowed_origins=common_all_arms
                ),
                "non_overlapping_paired": _aggregate_arm_metrics(
                    arm_evals, non_overlapping_only=True, allowed_origins=common_all_arms
                ),
            }

        # Paired DM strictly over valid comparable origins (and non-overlapping for h > 1, F-14)
        valid_hp_origins = sorted(
            o
            for o in (valid_origins_by_arm["HYBRID"] & valid_origins_by_arm["PRICE_ONLY"])
            if h == 1
            or any(
                e.origin_observed_at == o and e.is_non_overlapping_origin
                for e in h_evals
                if e.arm == "HYBRID"
            )
        )
        valid_hn_origins = sorted(
            o
            for o in (valid_origins_by_arm["HYBRID"] & valid_origins_by_arm["NO_CHANGE"])
            if h == 1
            or any(
                e.origin_observed_at == o and e.is_non_overlapping_origin
                for e in h_evals
                if e.arm == "HYBRID"
            )
        )
        valid_pn_origins = sorted(
            o
            for o in (valid_origins_by_arm["PRICE_ONLY"] & valid_origins_by_arm["NO_CHANGE"])
            if h == 1
            or any(
                e.origin_observed_at == o and e.is_non_overlapping_origin
                for e in h_evals
                if e.arm == "PRICE_ONLY"
            )
        )

        sq_by_arm_origin = {
            arm: {
                e.origin_observed_at: float(e.sq_error_log_return)
                for e in h_evals
                if e.arm == arm and e.sq_error_log_return is not None
            }
            for arm in ARMS
        }

        metrics_by_horizon[f"h{h}"] = {
            "horizon_publications": h,
            "paired_comparable_count": len(common_all_arms),
            "arms": arm_summary,
            "diebold_mariano": {
                "hybrid_vs_price_only": compute_diebold_mariano(
                    [sq_by_arm_origin["HYBRID"][o] for o in valid_hp_origins],
                    [sq_by_arm_origin["PRICE_ONLY"][o] for o in valid_hp_origins],
                    horizon=h,
                    non_overlapping=(h > 1),
                ),
                "hybrid_vs_no_change": compute_diebold_mariano(
                    [sq_by_arm_origin["HYBRID"][o] for o in valid_hn_origins],
                    [sq_by_arm_origin["NO_CHANGE"][o] for o in valid_hn_origins],
                    horizon=h,
                    non_overlapping=(h > 1),
                ),
                "price_only_vs_no_change": compute_diebold_mariano(
                    [sq_by_arm_origin["PRICE_ONLY"][o] for o in valid_pn_origins],
                    [sq_by_arm_origin["NO_CHANGE"][o] for o in valid_pn_origins],
                    horizon=h,
                    non_overlapping=(h > 1),
                ),
            },
        }
    return metrics_by_horizon


def run_backtest_study(
    mjdta_observations: list[MjdtaObservation],
    news_records: list[EligibleNewsRecord],
    collection_runs: list[dict[str, Any]] | None = None,
    evaluation_cutoff: datetime | None = None,
    lookback_hours: int = 24,
) -> dict[str, Any]:
    """
    F-02: Explicit HISTORICAL BACKTEST replay (`generation_mode="BACKTEST"`).
    Never writes to the prospective shadow ledger. Uses standardized features without
    heuristic priors, strictly excluding origins without stored label provenance or news coverage.
    """
    eligible_obs = [o for o in mjdta_observations if o.is_eligible_publication]
    if evaluation_cutoff is not None:
        cutoff_utc = _to_utc(evaluation_cutoff)
        eligible_obs = [o for o in eligible_obs if o.available_at_utc <= cutoff_utc]

    snapshots: list[dict[str, Any]] = []
    forecasts: list[ShadowForecastRecord] = []
    evaluations: list[EvaluatedForecastRecord] = []

    if not eligible_obs:
        return {
            "protocol_version": PROTOCOL_VERSION,
            "generation_mode": "BACKTEST",
            "model_version": MODEL_VERSION,
            "target_spec": MJDTA_SPEC,
            "status": "NO_ELIGIBLE_MJDTA_OBSERVATIONS",
            "eligible_publications": 0,
            "verified_news_coverage_origins": 0,
            "min_evaluation_samples": MIN_EVALUATION_SAMPLES,
            "latest_snapshot": None,
            "latest_forecasts": [],
            "metrics_by_horizon": {},
            "snapshots": [],
            "forecasts": [],
            "evaluations": [],
        }

    news_features_by_idx: list[CutoffNewsFeatures] = []
    price_features_by_idx: list[dict[str, float]] = []
    snapshot_ids_by_idx: list[str] = []

    for i, obs in enumerate(eligible_obs):
        cutoff_i = obs.original_observed_at_utc or obs.observed_at_utc
        nf = compute_news_features_at_cutoff(
            cutoff_time=cutoff_i,
            records=news_records,
            collection_runs=collection_runs,
            lookback_hours=lookback_hours,
            require_verified_availability=True,
        )
        pf = build_mjdta_price_features(eligible_obs, i)
        snap_id = _make_snapshot_id("BACKTEST", cutoff_i.isoformat(), obs.observed_at_utc.isoformat())

        news_features_by_idx.append(nf)
        price_features_by_idx.append(pf)
        snapshot_ids_by_idx.append(snap_id)

        snapshots.append(
            {
                "snapshot_id": snap_id,
                "generation_mode": "BACKTEST",
                "cutoff_time": cutoff_i.isoformat(),
                "label_cutoff_time": cutoff_i.isoformat(),
                "target_product": MJDTA_SPEC["product_key"],
                "origin_observation_id": obs.observation_id,
                "origin_observed_at": obs.observed_at_utc.isoformat(),
                "origin_gold_price_inr_per_g": obs.gold_mjdta_inr_per_g,
                "feature_version": nf.feature_version,
                "cluster_version": CLUSTER_VERSION,
                "sentiment_version": SENTIMENT_VERSION,
                "feature_hash": nf.feature_hash,
                "n_clusters_relevant": nf.n_clusters_relevant,
                "net_impact": nf.net_impact,
                "unknown_share": nf.unknown_share,
                "coverage_ok": nf.coverage_ok,
                "features_json": {**pf, **nf.to_model_dict()},
                "is_immutable": True,
            }
        )

    try:
        bt_protocol_sha256: str | None = verify_runtime_protocol()
    except ProtocolIntegrityError:
        bt_protocol_sha256 = None

    for i in range(5, len(eligible_obs)):
        obs = eligible_obs[i]
        emitted = _emit_arm_forecasts_at_origin(
            eligible_obs=eligible_obs,
            origin_idx=i,
            news_features_by_idx=news_features_by_idx,
            price_features_by_idx=price_features_by_idx,
            snapshot_id=snapshot_ids_by_idx[i],
            generation_mode="BACKTEST",
            generated_at=obs.available_at_utc,
            cutoff_time=obs.available_at_utc,
            protocol_sha256=bt_protocol_sha256,
        )
        for fc in emitted:
            forecasts.append(fc)
            h = fc.horizon_publications
            if i + h < len(eligible_obs):
                matured_obs = eligible_obs[i + h]
                actual_p = matured_obs.gold_mjdta_inr_per_g
                actual_lr = math.log(actual_p / fc.origin_price_inr_per_g)
                actual_dir = _classify_direction(actual_lr)
                actual_up = 1.0 if actual_lr > 0.0 else 0.0

                if fc.predicted_log_return is not None and fc.predicted_price_inr_per_g is not None and fc.up_probability is not None:
                    abs_lr = round(abs(fc.predicted_log_return - actual_lr), 6)
                    sq_lr = round((fc.predicted_log_return - actual_lr) ** 2, 8)
                    abs_inr = round(abs(fc.predicted_price_inr_per_g - actual_p), 2)
                    dir_ok = fc.predicted_direction == actual_dir
                    brier = round((fc.up_probability - actual_up) ** 2, 6)
                else:
                    abs_lr = sq_lr = abs_inr = dir_ok = brier = None

                evaluations.append(
                    EvaluatedForecastRecord(
                        forecast_id=fc.forecast_id,
                        generation_mode="BACKTEST",
                        arm=fc.arm,
                        horizon_publications=h,
                        origin_observed_at=fc.origin_observed_at,
                        target_observation_id=matured_obs.observation_id,
                        matured_observed_at=matured_obs.observed_at_utc.isoformat(),
                        actual_price_inr_per_g=actual_p,
                        actual_log_return=round(actual_lr, 6),
                        actual_direction=actual_dir,
                        abs_error_log_return=abs_lr,
                        sq_error_log_return=sq_lr,
                        abs_error_inr_per_g=abs_inr,
                        direction_correct=dir_ok,
                        brier_score=brier,
                        is_non_overlapping_origin=((i - 5) % h == 0),
                    )
                )

    metrics_by_horizon = summarize_evaluations_by_horizon(forecasts, evaluations)
    latest_origin_iso = eligible_obs[-1].observed_at_utc.isoformat()
    latest_forecasts = [asdict(f) for f in forecasts if f.origin_observed_at == latest_origin_iso]
    latest_snapshot = snapshots[-1] if snapshots else None
    verified_news_origins = sum(1 for s in snapshots if s["coverage_ok"])
    paired_h1_n = metrics_by_horizon.get("h1", {}).get("paired_comparable_count", 0)

    return {
        "protocol_version": PROTOCOL_VERSION,
        "generation_mode": "BACKTEST",
        "model_version": MODEL_VERSION,
        "target_spec": MJDTA_SPEC,
        "status": "READY_FOR_COMPARATIVE_EVAL" if paired_h1_n >= MIN_EVALUATION_SAMPLES else "INSUFFICIENT_SAMPLE",
        "eligible_publications": len(eligible_obs),
        "verified_news_coverage_origins": verified_news_origins,
        "min_evaluation_samples": MIN_EVALUATION_SAMPLES,
        "latest_snapshot": latest_snapshot,
        "latest_forecasts": latest_forecasts,
        "metrics_by_horizon": metrics_by_horizon,
        "snapshots": snapshots,
        "forecasts": [asdict(f) for f in forecasts],
        "evaluations": [asdict(e) for e in evaluations],
    }


def persist_prospective_forecast_run(
    db: Session,
    *,
    snapshot: dict[str, Any],
    forecasts: list[ShadowForecastRecord],
) -> dict[str, int]:
    """
    F-02 Strict Prospective Guard: Persist immutable PROSPECTIVE forecasts ONLY if:
      1. generation_mode == "PROSPECTIVE"
      2. target_observation_id is None and target_observed_at is None
      3. generated_at >= origin_observed_at
      4. Database contains ZERO post-origin valid MJDTA observations for that origin
         (`h=1` or `h=3` hindsight targets cannot already exist in `bullion_rate_observations`).
    Rejects hindsight / backtest contamination with ValueError.
    """
    if snapshot.get("generation_mode") != "PROSPECTIVE":
        raise ValueError("Prospective ledger writer rejects non-PROSPECTIVE snapshots.")

    verified_protocol_sha256 = verify_runtime_protocol()
    if snapshot.get("protocol_sha256") and snapshot["protocol_sha256"] != verified_protocol_sha256:
        raise ProtocolIntegrityError("Snapshot protocol_sha256 does not match active verified protocol.")

    origin_dt = parse_utc_iso(snapshot["origin_observed_at"])
    origin_src_pub = parse_utc_iso(snapshot.get("origin_source_published_at") or snapshot["origin_observed_at"])
    cutoff_dt = parse_utc_iso(snapshot["cutoff_time"])
    if origin_dt is None or cutoff_dt is None:
        raise ValueError("Prospective snapshot requires valid UTC origin_observed_at and cutoff_time.")

    # Verify against DB directly that NO future MJDTA observation already exists post-origin.
    # Lock on the publication identity so concurrent writers or correction re-runs serialize cleanly.
    if db.get_bind().dialect.name == "postgresql":
        from sqlalchemy import text as sa_text
        pub_key = (origin_src_pub or origin_dt).isoformat()
        lock_key = f"vmd_prosp_{pub_key}_{forecasts[0].model_version if forecasts else MODEL_VERSION}"
        db.execute(sa_text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": lock_key})

    origin_obs_row = (
        db.get(BullionRateObservation, snapshot.get("origin_observation_id"))
        if snapshot.get("origin_observation_id") is not None
        else None
    )
    authoritative_pub_dt = (
        _to_utc(origin_obs_row.source_published_at)
        if (origin_obs_row is not None and origin_obs_row.source_published_at is not None)
        else (origin_src_pub or origin_dt)
    )

    post_obs_rows = db.execute(
        select(BullionRateObservation.id, BullionRateObservation.observed_at, BullionRateObservation.source_published_at)
        .where(
            BullionRateObservation.product_id == "MJDTA_GOLD_24K",
            BullionRateObservation.city_code == "CHENNAI",
            BullionRateObservation.source_product_id == "MJDTA_GOLD",
            BullionRateObservation.validation_status == "VALID",
            # Same target-series definition as load_mjdta_observations_from_db (A3-11 & A3-FINAL-3).
            BullionRateObservation.unit == "1g",
            BullionRateObservation.rate_type == "MJDTA_BENCHMARK",
            BullionRateObservation.source_published_at.is_not(None),
            BullionRateObservation.observation_kind == "ORIGINAL",
            BullionRateObservation.observed_at > origin_dt,
            BullionRateObservation.source_published_at > authoritative_pub_dt,
        )
        .order_by(BullionRateObservation.observed_at.asc())
    ).all()

    # Validate ALL forecasts BEFORE inserting any snapshot so invalid runs create zero orphans (NEW-7)
    candidates_to_insert: list[tuple[ShadowForecastRecord, datetime]] = []
    for fc in forecasts:
        if fc.generation_mode != "PROSPECTIVE":
            raise ValueError(f"Forecast {fc.forecast_id} must use generation_mode='PROSPECTIVE'.")
        if fc.target_observation_id is not None or fc.target_observed_at is not None:
            raise ValueError(f"Hindsight error: prospective forecast {fc.forecast_id} cannot pre-populate target.")
        if fc.protocol_version != PROTOCOL_VERSION:
            raise ProtocolIntegrityError(f"Forecast protocol_version={fc.protocol_version!r} is incompatible.")
        if fc.protocol_sha256 and fc.protocol_sha256 != verified_protocol_sha256:
            raise ProtocolIntegrityError("Forecast protocol_sha256 does not match active verified protocol.")

        gen_dt = parse_utc_iso(fc.generated_at)
        if gen_dt is None or gen_dt < origin_dt:
            raise ValueError(f"Invalid prospective timestamps on {fc.forecast_id}: generated_at < origin_observed_at.")

        if len(post_obs_rows) >= fc.horizon_publications:
            raise ValueError(
                f"Hindsight error: cannot persist PROSPECTIVE h={fc.horizon_publications} forecast at "
                f"{origin_dt.isoformat()} because {len(post_obs_rows)} post-origin MJDTA observation(s) already exist."
            )

        existing = db.execute(
            select(ForecastRun).where(
                ForecastRun.protocol_version == fc.protocol_version,
                ForecastRun.generation_mode == "PROSPECTIVE",
                ForecastRun.model_version == fc.model_version,
                ForecastRun.arm == fc.arm,
                ForecastRun.horizon_publications == fc.horizon_publications,
                ForecastRun.origin_observed_at == origin_dt,
            )
        ).scalar_one_or_none()
        if existing is None and authoritative_pub_dt is not None:
            existing = db.execute(
                select(ForecastRun).where(
                    ForecastRun.protocol_version == fc.protocol_version,
                    ForecastRun.generation_mode == "PROSPECTIVE",
                    ForecastRun.model_version == fc.model_version,
                    ForecastRun.arm == fc.arm,
                    ForecastRun.horizon_publications == fc.horizon_publications,
                    ForecastRun.origin_source_published_at == authoritative_pub_dt,
                )
            ).scalar_one_or_none()
        if existing is None:
            candidates_to_insert.append((fc, gen_dt))

    if not candidates_to_insert:
        return {"snapshots_inserted": 0, "prospective_forecasts_inserted": 0}

    sid = snapshot["snapshot_id"]
    snapshots_inserted = 0
    existing_snap = db.execute(
        select(ResearchFeatureSnapshot).where(ResearchFeatureSnapshot.snapshot_id == sid)
    ).scalar_one_or_none()
    if existing_snap is None:
        db.add(
            ResearchFeatureSnapshot(
                snapshot_id=sid,
                generation_mode="PROSPECTIVE",
                cutoff_time=cutoff_dt,
                label_cutoff_time=parse_utc_iso(snapshot.get("label_cutoff_time")) or cutoff_dt,
                target_product=snapshot["target_product"],
                origin_observation_id=snapshot.get("origin_observation_id"),
                origin_observed_at=origin_dt,
                origin_source_published_at=authoritative_pub_dt,
                origin_gold_price_inr_per_g=Decimal(str(snapshot["origin_gold_price_inr_per_g"])),
                feature_version=snapshot["feature_version"],
                cluster_version=snapshot["cluster_version"],
                sentiment_version=snapshot["sentiment_version"],
                protocol_sha256=verified_protocol_sha256,
                feature_hash=snapshot.get("feature_hash"),
                n_clusters_relevant=int(snapshot["n_clusters_relevant"]),
                net_impact=snapshot.get("net_impact"),
                unknown_share=snapshot.get("unknown_share"),
                coverage_ok=bool(snapshot["coverage_ok"]),
                features_json=snapshot["features_json"],
                is_immutable=True,
            )
        )
        db.flush()
        snapshots_inserted = 1

    inserted = 0
    for fc, gen_dt in candidates_to_insert:
        db.add(
            ForecastRun(
                forecast_id=fc.forecast_id,
                protocol_version=fc.protocol_version,
                protocol_sha256=fc.protocol_sha256 or verified_protocol_sha256,
                generation_mode="PROSPECTIVE",
                model_version=fc.model_version,
                arm=fc.arm,
                horizon_publications=fc.horizon_publications,
                generated_at=gen_dt,
                cutoff_time=cutoff_dt,
                origin_observation_id=fc.origin_observation_id,
                origin_observed_at=origin_dt,
                origin_source_published_at=authoritative_pub_dt,
                origin_price_inr_per_g=Decimal(str(fc.origin_price_inr_per_g)),
                target_observation_id=None,
                target_observed_at=None,
                snapshot_id=sid,
                feature_hash=fc.feature_hash,
                predicted_log_return=fc.predicted_log_return,
                predicted_price_inr_per_g=(
                    Decimal(str(fc.predicted_price_inr_per_g))
                    if fc.predicted_price_inr_per_g is not None
                    else None
                ),
                predicted_direction=fc.predicted_direction,
                up_probability=fc.up_probability,
                status=fc.status,
                is_immutable=True,
            )
        )
        inserted += 1

    db.commit()
    return {"snapshots_inserted": snapshots_inserted, "prospective_forecasts_inserted": inserted}


def evaluate_matured_prospective_forecasts(db: Session) -> dict[str, int]:
    """
    Evaluate previously persisted PROSPECTIVE forecasts once `h` subsequent valid
    authoritative MJDTA_GOLD_24K observations exist strictly after `origin_observed_at`.
    Preserves original `forecast_evaluations` rows untouched and records any subsequent
    target price corrections in `forecast_evaluation_reassessments` (A3-FINAL-3).
    """
    eligible_obs, _ = load_mjdta_observations_from_db(db)
    eligible_only = [o for o in eligible_obs if o.is_eligible_publication]

    evaluated_ids = {
        r[0] for r in db.query(ForecastEvaluation.forecast_id).all()
    }
    pending_runs = db.execute(
        select(ForecastRun)
        .where(ForecastRun.generation_mode == "PROSPECTIVE")
        .order_by(ForecastRun.origin_observed_at.asc(), ForecastRun.horizon_publications.asc())
    ).scalars().all()

    inserted_evals = 0
    for run in pending_runs:
        if run.forecast_id in evaluated_ids:
            continue
        origin_dt = _to_utc(run.origin_observed_at)
        origin_obs_row = (
            db.get(BullionRateObservation, run.origin_observation_id)
            if run.origin_observation_id is not None
            else None
        )
        origin_src_pub = (
            _to_utc(origin_obs_row.source_published_at)
            if (origin_obs_row is not None and origin_obs_row.source_published_at is not None)
            else (_to_utc(run.origin_source_published_at) if run.origin_source_published_at else origin_dt)
        )
        post_eligible = [
            o
            for o in eligible_only
            if o.observed_at_utc > origin_dt
            and (o.source_published_at_utc or o.observed_at_utc) > origin_src_pub
        ]
        if len(post_eligible) < run.horizon_publications:
            continue

        target_obs = post_eligible[run.horizon_publications - 1]
        # Initial evaluation strictly anchors to the ORIGINAL publication observation
        orig_tgt_row = None
        if target_obs.source_published_at_utc is not None:
            orig_tgt_row = db.execute(
                select(BullionRateObservation)
                .where(
                    BullionRateObservation.product_id == "MJDTA_GOLD_24K",
                    BullionRateObservation.city_code == "CHENNAI",
                    BullionRateObservation.source_product_id == "MJDTA_GOLD",
                    BullionRateObservation.validation_status == "VALID",
                    BullionRateObservation.unit == "1g",
                    BullionRateObservation.rate_type == "MJDTA_BENCHMARK",
                    BullionRateObservation.source_published_at == target_obs.source_published_at_utc,
                    BullionRateObservation.observation_kind == "ORIGINAL",
                )
                .order_by(BullionRateObservation.id.asc())
                .limit(1)
            ).scalar_one_or_none()
        tgt_id = orig_tgt_row.id if orig_tgt_row is not None else target_obs.observation_id
        tgt_obs_dt = _to_utc(orig_tgt_row.observed_at) if orig_tgt_row is not None else target_obs.observed_at_utc
        actual_p = (
            float(orig_tgt_row.normalized_price_per_gram or orig_tgt_row.price)
            if orig_tgt_row is not None
            else target_obs.gold_mjdta_inr_per_g
        )

        if tgt_obs_dt <= _to_utc(run.generated_at):
            # Guard: outcome cannot predate forecast generation timestamp
            continue

        p0 = float(run.origin_price_inr_per_g)
        actual_lr = math.log(actual_p / p0)
        actual_dir = _classify_direction(actual_lr)
        actual_up = 1.0 if actual_lr > 0.0 else 0.0

        if run.predicted_log_return is not None and run.predicted_price_inr_per_g is not None and run.up_probability is not None:
            abs_lr = round(abs(float(run.predicted_log_return) - actual_lr), 6)
            sq_lr = round((float(run.predicted_log_return) - actual_lr) ** 2, 8)
            abs_inr = Decimal(str(round(abs(float(run.predicted_price_inr_per_g) - actual_p), 2)))
            dir_ok = run.predicted_direction == actual_dir
            brier = round((float(run.up_probability) - actual_up) ** 2, 6)
        else:
            abs_lr = sq_lr = abs_inr = dir_ok = brier = None

        eval_ts = max(datetime.now(timezone.utc), tgt_obs_dt, _to_utc(run.generated_at))

        # Append-only evaluation: NEVER mutate the immutable ForecastRun row
        db.add(
            ForecastEvaluation(
                forecast_id=run.forecast_id,
                protocol_version=run.protocol_version,
                model_version=run.model_version,
                generation_mode="PROSPECTIVE",
                arm=run.arm,
                horizon_publications=run.horizon_publications,
                origin_observed_at=origin_dt,
                target_observation_id=tgt_id,
                matured_observed_at=tgt_obs_dt,
                actual_price_inr_per_g=Decimal(str(actual_p)),
                actual_log_return=round(actual_lr, 6),
                actual_direction=actual_dir,
                abs_error_log_return=abs_lr,
                sq_error_log_return=sq_lr,
                abs_error_inr_per_g=abs_inr,
                direction_correct=dir_ok,
                brier_score=brier,
                is_non_overlapping_origin=True,
                evaluated_at=eval_ts,
            )
        )
        evaluated_ids.add(run.forecast_id)
        inserted_evals += 1

    db.flush()

    # Part 2 (A3-FINAL-3): Record separate append-only reassessments for any evaluated target
    # publications that later received a CORRECTION observation.
    existing_reassessments = {
        (r[0], r[1])
        for r in db.query(
            ForecastEvaluationReassessment.forecast_id,
            ForecastEvaluationReassessment.corrected_target_observation_id,
        ).all()
    }
    prosp_evals = db.execute(
        select(ForecastEvaluation).where(
            ForecastEvaluation.generation_mode == "PROSPECTIVE",
            ForecastEvaluation.target_observation_id.is_not(None),
        )
    ).scalars().all()
    runs_by_id = {
        r.forecast_id: r
        for r in db.execute(select(ForecastRun).where(ForecastRun.generation_mode == "PROSPECTIVE")).scalars().all()
    }
    inserted_reassessments = 0
    for ev in prosp_evals:
        orig_obs = db.get(BullionRateObservation, ev.target_observation_id) if ev.target_observation_id is not None else None
        run = runs_by_id.get(ev.forecast_id)
        if orig_obs is None or orig_obs.source_published_at is None or run is None:
            continue
        corrections = db.execute(
            select(BullionRateObservation)
            .where(
                BullionRateObservation.product_id == "MJDTA_GOLD_24K",
                BullionRateObservation.city_code == "CHENNAI",
                BullionRateObservation.source_product_id == "MJDTA_GOLD",
                BullionRateObservation.validation_status == "VALID",
                BullionRateObservation.unit == "1g",
                BullionRateObservation.rate_type == "MJDTA_BENCHMARK",
                BullionRateObservation.source_published_at == orig_obs.source_published_at,
                BullionRateObservation.observation_kind == "CORRECTION",
            )
            .order_by(BullionRateObservation.revision_number.asc(), BullionRateObservation.id.asc())
        ).scalars().all()
        for corr in corrections:
            if (ev.forecast_id, corr.id) in existing_reassessments:
                continue
            corr_p = float(corr.normalized_price_per_gram or corr.price)
            p0 = float(run.origin_price_inr_per_g)
            corr_lr = math.log(corr_p / p0)
            corr_dir = _classify_direction(corr_lr)
            corr_up = 1.0 if corr_lr > 0.0 else 0.0
            if run.predicted_log_return is not None and run.predicted_price_inr_per_g is not None and run.up_probability is not None:
                c_abs_lr = round(abs(float(run.predicted_log_return) - corr_lr), 6)
                c_sq_lr = round((float(run.predicted_log_return) - corr_lr) ** 2, 8)
                c_abs_inr = Decimal(str(round(abs(float(run.predicted_price_inr_per_g) - corr_p), 2)))
                c_dir_ok = run.predicted_direction == corr_dir
                c_brier = round((float(run.up_probability) - corr_up) ** 2, 6)
            else:
                c_abs_lr = c_sq_lr = c_abs_inr = c_dir_ok = c_brier = None
            rid = hashlib.sha256(f"{ev.forecast_id}|{corr.id}".encode("utf-8")).hexdigest()[:32]
            db.add(
                ForecastEvaluationReassessment(
                    reassessment_id=f"reassess_{rid}",
                    forecast_id=ev.forecast_id,
                    original_target_observation_id=ev.target_observation_id,
                    corrected_target_observation_id=corr.id,
                    corrected_revision_number=int(corr.revision_number or 2),
                    matured_observed_at=_to_utc(ev.matured_observed_at),
                    corrected_observed_at=_to_utc(corr.observed_at),
                    corrected_actual_price_inr_per_g=Decimal(str(corr_p)),
                    corrected_actual_log_return=round(corr_lr, 6),
                    corrected_actual_direction=corr_dir,
                    abs_error_log_return=c_abs_lr,
                    sq_error_log_return=c_sq_lr,
                    abs_error_inr_per_g=c_abs_inr,
                    direction_correct=c_dir_ok,
                    brier_score=c_brier,
                )
            )
            existing_reassessments.add((ev.forecast_id, corr.id))
            inserted_reassessments += 1

    db.commit()
    return {
        "prospective_evaluations_inserted": inserted_evals,
        "prospective_reassessments_inserted": inserted_reassessments,
    }


def generate_prospective_forecast_for_frontier(
    db: Session,
    *,
    generated_at: datetime | None = None,
    lookback_hours: int = 24,
) -> dict[str, Any]:
    """
    F-01 / F-02 / A3-FINAL-3 / A3-FINAL-6: End-to-end prospective shadow forecast cycle
    verifying protocol integrity, reading point-in-time MJDTA + stored verified news/labels
    from DB, logging immutable PROSPECTIVE forecasts once per publication, and maturing evaluations.
    """
    verified_protocol_sha256 = verify_runtime_protocol()
    gen_utc = _to_utc(generated_at or datetime.now(timezone.utc))
    matured_stats = evaluate_matured_prospective_forecasts(db)

    all_obs, mjdta_audit = load_mjdta_observations_from_db(db, as_of=gen_utc)
    eligible_obs = [o for o in all_obs if o.is_eligible_publication]
    if len(eligible_obs) < 6:
        return {
            "status": "INSUFFICIENT_MJDTA_HISTORY",
            "protocol_version": PROTOCOL_VERSION,
            "protocol_sha256": verified_protocol_sha256,
            "eligible_publications": len(eligible_obs),
            "matured_evaluations_inserted": matured_stats["prospective_evaluations_inserted"],
            "matured_reassessments_inserted": matured_stats.get("prospective_reassessments_inserted", 0),
            "prospective_forecasts": [],
        }

    origin_idx = len(eligible_obs) - 1
    origin_obs = eligible_obs[origin_idx]
    if gen_utc < origin_obs.available_at_utc:
        raise ValueError("generated_at cannot precede the frontier MJDTA observation.")

    origin_src_pub = origin_obs.source_published_at_utc or origin_obs.observed_at_utc
    existing_for_pub = db.execute(
        select(ForecastRun).where(
            ForecastRun.protocol_version == PROTOCOL_VERSION,
            ForecastRun.generation_mode == "PROSPECTIVE",
            ForecastRun.model_version == MODEL_VERSION,
            ForecastRun.origin_source_published_at == origin_src_pub,
        )
    ).scalars().all()
    if len(existing_for_pub) >= len(ARMS) * len(HORIZONS):
        return {
            "status": "PROSPECTIVE_ALREADY_LOGGED_FOR_PUBLICATION",
            "protocol_version": PROTOCOL_VERSION,
            "protocol_sha256": verified_protocol_sha256,
            "generation_mode": "PROSPECTIVE",
            "origin_observed_at": origin_obs.observed_at_utc.isoformat(),
            "origin_source_published_at": origin_src_pub.isoformat(),
            "origin_price_inr_per_g": origin_obs.gold_mjdta_inr_per_g,
            "correction_detected": origin_obs.revision_number > 1,
            "mjdta_audit": mjdta_audit,
            "persisted": {"snapshots_inserted": 0, "prospective_forecasts_inserted": 0},
            "matured_evaluations_inserted": matured_stats["prospective_evaluations_inserted"],
            "matured_reassessments_inserted": matured_stats.get("prospective_reassessments_inserted", 0),
            "prospective_forecasts": [],
        }

    news_records, runs = load_eligible_news_records_from_db(
        db,
        cutoff_time=gen_utc,
        model_name="deterministic_rules_v2",
    )

    news_features_by_idx: list[CutoffNewsFeatures] = []
    price_features_by_idx: list[dict[str, float]] = []
    for idx, obs in enumerate(eligible_obs):
        cutoff_idx = gen_utc if idx == origin_idx else (obs.original_observed_at_utc or obs.observed_at_utc)
        news_features_by_idx.append(
            compute_news_features_at_cutoff(
                cutoff_time=cutoff_idx,
                records=news_records,
                collection_runs=runs,
                lookback_hours=lookback_hours,
                require_verified_availability=True,
            )
        )
        price_features_by_idx.append(build_mjdta_price_features(eligible_obs, idx))

    nf_frontier = news_features_by_idx[origin_idx]
    pf_frontier = price_features_by_idx[origin_idx]
    snap_id = _make_snapshot_id(
        "PROSPECTIVE",
        gen_utc.isoformat(),
        origin_obs.observed_at_utc.isoformat(),
        feature_hash=nf_frontier.feature_hash,
    )

    snapshot_dict = {
        "snapshot_id": snap_id,
        "generation_mode": "PROSPECTIVE",
        "cutoff_time": gen_utc.isoformat(),
        "label_cutoff_time": gen_utc.isoformat(),
        "target_product": MJDTA_SPEC["product_key"],
        "origin_observation_id": origin_obs.observation_id,
        "origin_observed_at": origin_obs.observed_at_utc.isoformat(),
        "origin_source_published_at": origin_src_pub.isoformat(),
        "origin_gold_price_inr_per_g": origin_obs.gold_mjdta_inr_per_g,
        "feature_version": nf_frontier.feature_version,
        "cluster_version": CLUSTER_VERSION,
        "sentiment_version": SENTIMENT_VERSION,
        "protocol_sha256": verified_protocol_sha256,
        "feature_hash": nf_frontier.feature_hash,
        "n_clusters_relevant": nf_frontier.n_clusters_relevant,
        "net_impact": nf_frontier.net_impact,
        "unknown_share": nf_frontier.unknown_share,
        "coverage_ok": nf_frontier.coverage_ok,
        "features_json": {**pf_frontier, **nf_frontier.to_model_dict()},
        "is_immutable": True,
    }

    emitted = _emit_arm_forecasts_at_origin(
        eligible_obs=eligible_obs,
        origin_idx=origin_idx,
        news_features_by_idx=news_features_by_idx,
        price_features_by_idx=price_features_by_idx,
        snapshot_id=snap_id,
        generation_mode="PROSPECTIVE",
        generated_at=gen_utc,
        cutoff_time=gen_utc,
        protocol_sha256=verified_protocol_sha256,
    )

    persisted = persist_prospective_forecast_run(db, snapshot=snapshot_dict, forecasts=emitted)
    return {
        "status": "PROSPECTIVE_FORECAST_LOGGED",
        "protocol_version": PROTOCOL_VERSION,
        "protocol_sha256": verified_protocol_sha256,
        "generation_mode": "PROSPECTIVE",
        "origin_observed_at": origin_obs.observed_at_utc.isoformat(),
        "origin_source_published_at": origin_src_pub.isoformat(),
        "origin_price_inr_per_g": origin_obs.gold_mjdta_inr_per_g,
        "mjdta_audit": mjdta_audit,
        "persisted": persisted,
        "matured_evaluations_inserted": matured_stats["prospective_evaluations_inserted"],
        "matured_reassessments_inserted": matured_stats.get("prospective_reassessments_inserted", 0),
        "prospective_forecasts": [asdict(f) for f in emitted],
    }


def _load_prospective_ledger_summary(db: Session) -> dict[str, Any]:
    """Read immutable PROSPECTIVE forecasts and matured PROSPECTIVE evaluations from DB."""
    prospective_runs = db.execute(
        select(ForecastRun)
        .where(ForecastRun.generation_mode == "PROSPECTIVE")
        .order_by(ForecastRun.origin_observed_at.desc(), ForecastRun.horizon_publications.asc())
    ).scalars().all()

    prospective_evals = db.execute(
        select(ForecastEvaluation).where(ForecastEvaluation.generation_mode == "PROSPECTIVE")
    ).scalars().all()

    eval_records = [
        EvaluatedForecastRecord(
            forecast_id=e.forecast_id,
            generation_mode="PROSPECTIVE",
            arm=e.arm,
            horizon_publications=e.horizon_publications,
            origin_observed_at=_to_utc(e.origin_observed_at).isoformat(),
            target_observation_id=e.target_observation_id,
            matured_observed_at=_to_utc(e.matured_observed_at).isoformat(),
            actual_price_inr_per_g=float(e.actual_price_inr_per_g),
            actual_log_return=float(e.actual_log_return),
            actual_direction=e.actual_direction,
            abs_error_log_return=e.abs_error_log_return,
            sq_error_log_return=e.sq_error_log_return,
            abs_error_inr_per_g=float(e.abs_error_inr_per_g) if e.abs_error_inr_per_g is not None else None,
            direction_correct=e.direction_correct,
            brier_score=e.brier_score,
            is_non_overlapping_origin=bool(e.is_non_overlapping_origin),
        )
        for e in prospective_evals
    ]
    run_records = [
        ShadowForecastRecord(
            forecast_id=r.forecast_id,
            protocol_version=r.protocol_version,
            generation_mode="PROSPECTIVE",
            model_version=r.model_version,
            arm=r.arm,
            horizon_publications=r.horizon_publications,
            generated_at=_to_utc(r.generated_at).isoformat(),
            cutoff_time=_to_utc(r.cutoff_time).isoformat(),
            origin_observation_id=r.origin_observation_id,
            origin_observed_at=_to_utc(r.origin_observed_at).isoformat(),
            origin_price_inr_per_g=float(r.origin_price_inr_per_g),
            target_observation_id=r.target_observation_id,
            target_observed_at=_to_utc(r.target_observed_at).isoformat() if r.target_observed_at else None,
            snapshot_id=r.snapshot_id,
            feature_hash=r.feature_hash or "",
            predicted_log_return=r.predicted_log_return,
            predicted_price_inr_per_g=float(r.predicted_price_inr_per_g) if r.predicted_price_inr_per_g is not None else None,
            predicted_direction=r.predicted_direction,
            up_probability=r.up_probability,
            status=r.status,
            coverage_ok=bool(r.predicted_log_return is not None or r.arm in {"NO_CHANGE", "PRICE_ONLY"}),
            is_immutable=bool(r.is_immutable),
            protocol_sha256=r.protocol_sha256,
            origin_source_published_at=_to_utc(r.origin_source_published_at).isoformat() if r.origin_source_published_at else None,
        )
        for r in prospective_runs
    ]

    latest_prosp_origin = run_records[0].origin_observed_at if run_records else None
    latest_prosp_forecasts = (
        [asdict(r) for r in run_records if r.origin_observed_at == latest_prosp_origin]
        if latest_prosp_origin
        else []
    )
    distinct_origins = {r.origin_observed_at for r in run_records}
    matured_origins = {e.origin_observed_at for e in eval_records}
    metrics = summarize_evaluations_by_horizon(run_records, eval_records)
    paired_h1 = metrics.get("h1", {}).get("paired_comparable_count", 0)

    return {
        "generation_mode": "PROSPECTIVE",
        "status": "READY_FOR_COMPARATIVE_EVAL" if paired_h1 >= MIN_EVALUATION_SAMPLES else "INSUFFICIENT_PROSPECTIVE_SAMPLES",
        "total_prospective_origins": len(distinct_origins),
        "matured_prospective_origins": len(matured_origins),
        "min_evaluation_samples": MIN_EVALUATION_SAMPLES,
        "latest_prospective_forecasts": latest_prosp_forecasts,
        "metrics_by_horizon": metrics,
    }


def persist_research_shadow_results(db: Session, pipeline_result: dict[str, Any]) -> dict[str, int]:
    """
    Idempotently persist BACKTEST feature snapshots, forecasts, and evaluations into SQLAlchemy.
    Rejects attempts to write BACKTEST items tagged as PROSPECTIVE through this bulk replay path.
    """
    if pipeline_result.get("generation_mode") == "PROSPECTIVE":
        raise ValueError("Use persist_prospective_forecast_run for PROSPECTIVE ledger writes.")

    existing_snaps = {r[0] for r in db.query(ResearchFeatureSnapshot.snapshot_id).all()}
    existing_fcs = {r[0] for r in db.query(ForecastRun.forecast_id).all()}
    existing_evals = {r[0] for r in db.query(ForecastEvaluation.forecast_id).all()}

    inserted_snaps = 0
    for snap in pipeline_result.get("snapshots", []):
        sid = snap["snapshot_id"]
        if sid in existing_snaps:
            continue
        db.add(
            ResearchFeatureSnapshot(
                snapshot_id=sid,
                generation_mode="BACKTEST",
                cutoff_time=parse_utc_iso(snap["cutoff_time"]) or datetime.now(timezone.utc),
                label_cutoff_time=parse_utc_iso(snap.get("label_cutoff_time") or snap["cutoff_time"]),
                target_product=snap["target_product"],
                origin_observation_id=snap.get("origin_observation_id"),
                origin_observed_at=parse_utc_iso(snap["origin_observed_at"]) or datetime.now(timezone.utc),
                origin_gold_price_inr_per_g=Decimal(str(snap["origin_gold_price_inr_per_g"])),
                feature_version=snap["feature_version"],
                cluster_version=snap["cluster_version"],
                sentiment_version=snap["sentiment_version"],
                feature_hash=snap.get("feature_hash"),
                n_clusters_relevant=int(snap["n_clusters_relevant"]),
                net_impact=snap.get("net_impact"),
                unknown_share=snap.get("unknown_share"),
                coverage_ok=bool(snap["coverage_ok"]),
                features_json=snap["features_json"],
                is_immutable=True,
            )
        )
        existing_snaps.add(sid)
        inserted_snaps += 1

    db.flush()

    inserted_fcs = 0
    for fc in pipeline_result.get("forecasts", []):
        fid = fc["forecast_id"]
        if fid in existing_fcs:
            continue
        db.add(
            ForecastRun(
                forecast_id=fid,
                protocol_version=fc["protocol_version"],
                protocol_sha256=fc.get("protocol_sha256"),
                generation_mode="BACKTEST",
                model_version=fc.get("model_version", MODEL_VERSION),
                arm=fc["arm"],
                horizon_publications=int(fc["horizon_publications"]),
                generated_at=parse_utc_iso(fc.get("generated_at") or fc["cutoff_time"]) or datetime.now(timezone.utc),
                cutoff_time=parse_utc_iso(fc["cutoff_time"]) or datetime.now(timezone.utc),
                origin_observation_id=fc.get("origin_observation_id"),
                origin_observed_at=parse_utc_iso(fc["origin_observed_at"]) or datetime.now(timezone.utc),
                origin_source_published_at=parse_utc_iso(fc.get("origin_source_published_at")) if fc.get("origin_source_published_at") else None,
                origin_price_inr_per_g=Decimal(str(fc["origin_price_inr_per_g"])),
                target_observation_id=None,
                target_observed_at=None,
                snapshot_id=fc["snapshot_id"],
                feature_hash=fc.get("feature_hash"),
                predicted_log_return=fc["predicted_log_return"],
                predicted_price_inr_per_g=(
                    Decimal(str(fc["predicted_price_inr_per_g"]))
                    if fc["predicted_price_inr_per_g"] is not None
                    else None
                ),
                predicted_direction=fc["predicted_direction"],
                up_probability=fc["up_probability"],
                status=fc["status"],
                is_immutable=True,
            )
        )
        existing_fcs.add(fid)
        inserted_fcs += 1

    db.flush()

    inserted_evals = 0
    for ev in pipeline_result.get("evaluations", []):
        fid = ev["forecast_id"]
        if fid in existing_evals:
            continue
        db.add(
            ForecastEvaluation(
                forecast_id=fid,
                generation_mode="BACKTEST",
                arm=ev["arm"],
                horizon_publications=int(ev["horizon_publications"]),
                origin_observed_at=parse_utc_iso(ev["origin_observed_at"]) or datetime.now(timezone.utc),
                target_observation_id=ev.get("target_observation_id"),
                matured_observed_at=parse_utc_iso(ev["matured_observed_at"]) or datetime.now(timezone.utc),
                actual_price_inr_per_g=Decimal(str(ev["actual_price_inr_per_g"])),
                actual_log_return=float(ev["actual_log_return"]),
                actual_direction=ev["actual_direction"],
                abs_error_log_return=ev["abs_error_log_return"],
                sq_error_log_return=ev["sq_error_log_return"],
                abs_error_inr_per_g=(
                    Decimal(str(ev["abs_error_inr_per_g"]))
                    if ev["abs_error_inr_per_g"] is not None
                    else None
                ),
                direction_correct=ev["direction_correct"],
                brier_score=ev["brier_score"],
                is_non_overlapping_origin=bool(ev["is_non_overlapping_origin"]),
            )
        )
        existing_evals.add(fid)
        inserted_evals += 1

    db.commit()
    return {
        "snapshots_inserted": inserted_snaps,
        "forecasts_inserted": inserted_fcs,
        "evaluations_inserted": inserted_evals,
    }


def get_latest_mjdta_research_summary(
    db: Session | None = None,
    *,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """
    F-01 / F-02: Authoritative DB-backed MJDTA research summary.
    Reads MJDTA_GOLD_24K and stored news/labels directly from the configured database,
    strictly separating the PROSPECTIVE shadow ledger from the historical BACKTEST study.
    Fails closed when DB is unavailable (never falls back to stale CSV).
    """
    own_session = False
    if db is None:
        db = db_session.SessionLocal()
        own_session = True

    try:
        mjdta_obs, mjdta_audit = load_mjdta_observations_from_db(db)
        now_utc = datetime.now(timezone.utc)
        news_records, runs = load_eligible_news_records_from_db(
            db,
            cutoff_time=now_utc,
            model_name="deterministic_rules_v2",
        )
        prospective_ledger = _load_prospective_ledger_summary(db)
        backtest_study = run_backtest_study(
            mjdta_observations=mjdta_obs,
            news_records=news_records,
            collection_runs=runs,
        )
        return {
            "protocol_version": PROTOCOL_VERSION,
            "model_version": MODEL_VERSION,
            "target_spec": MJDTA_SPEC,
            "status": prospective_ledger["status"],
            "eligible_publications": backtest_study["eligible_publications"],
            "verified_news_coverage_origins": backtest_study["verified_news_coverage_origins"],
            "min_evaluation_samples": MIN_EVALUATION_SAMPLES,
            "prospective_ledger": prospective_ledger,
            "latest_snapshot": backtest_study["latest_snapshot"],
            # F-18: NEVER silently fall back to BACKTEST forecasts inside `latest_forecasts`
            "latest_forecasts": prospective_ledger["latest_prospective_forecasts"],
            "backtest_latest_forecasts": backtest_study["latest_forecasts"],
            "metrics_by_horizon": backtest_study["metrics_by_horizon"],
            "backtest_status": backtest_study["status"],
            "mjdta_audit": mjdta_audit,
        }
    finally:
        if own_session:
            db.close()
