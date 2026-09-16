"""
v3/uncertainty/quantiles.py

Statistical and empirical uncertainty estimators:
- rolling_mad (Gaussian scaled by rolling MAD / residual std)
- series_empirical (historical residual quantiles from the same series)
- category_empirical (pooled category empirical quantiles)
- hybrid_shrinkage (shrinkage between series and category quantiles)
"""
from __future__ import annotations
from typing import Dict, List, Tuple
import statistics
import numpy as np

from v3.forecasting.features import FeatureRow
from v3.uncertainty.residuals import CategoryQuantiles


def _compute_past_residuals(row: FeatureRow) -> List[float]:
    """Computes past residuals relative to rolling_mean_8 for previous observations."""
    amounts = row.history_amounts
    t = len(amounts)
    if t < 2:
        return [0.0]
    
    # For each past observation i in [1, t-1], compute baseline pred from amounts[:i]
    res_list: List[float] = []
    for i in range(1, t):
        win = amounts[max(0, i-8):i]
        pred_i = statistics.mean(win)
        res_list.append(amounts[i] - pred_i)
    return res_list


def predict_quantiles_rolling_mad(
    row: FeatureRow,
    cat_quantiles: Dict[str, CategoryQuantiles],
) -> Dict[str, float]:
    """
    Rolling MAD / residual standard deviation baseline.
    P50 = baseline
    P75 = baseline + 0.6745 * std
    P90 = baseline + 1.2816 * std
    Fixed categories use std=0.0.
    """
    base = row.features['rolling_mean_8_ratio'] * row.train_scale
    if not row.is_variable:
        return {'p50': base, 'p75': base, 'p90': base}

    past_res = _compute_past_residuals(row)
    if len(past_res) >= 2:
        res_std = statistics.stdev(past_res)
    elif row.category in cat_quantiles:
        res_std = cat_quantiles[row.category].std_rel * row.train_scale
    else:
        res_std = 0.15 * row.train_scale

    return {
        'p50': base,
        'p75': base + 0.6745 * res_std,
        'p90': base + 1.2816 * res_std,
    }


def predict_quantiles_series_empirical(
    row: FeatureRow,
    cat_quantiles: Dict[str, CategoryQuantiles],
) -> Dict[str, float]:
    """
    Series-level empirical quantile baseline.
    Uses historical residuals in the same series when len >= 4;
    otherwise falls back to category-level quantiles.
    """
    base = row.features['rolling_mean_8_ratio'] * row.train_scale
    if not row.is_variable:
        return {'p50': base, 'p75': base, 'p90': base}

    past_res = _compute_past_residuals(row)
    if len(past_res) >= 4:
        arr = np.array(past_res, dtype=np.float64)
        return {
            'p50': base + float(np.percentile(arr, 50)),
            'p75': base + float(np.percentile(arr, 75)),
            'p90': base + float(np.percentile(arr, 90)),
        }
    else:
        return predict_quantiles_category_empirical(row, cat_quantiles)


def predict_quantiles_category_empirical(
    row: FeatureRow,
    cat_quantiles: Dict[str, CategoryQuantiles],
) -> Dict[str, float]:
    """
    Category-level empirical quantile baseline.
    Uses training empirical distribution of normalized residuals by category.
    """
    base = row.features['rolling_mean_8_ratio'] * row.train_scale
    if not row.is_variable:
        return {'p50': base, 'p75': base, 'p90': base}

    cq = cat_quantiles.get(row.category)
    if cq:
        p50 = base + cq.p50_rel * row.train_scale
        p75 = base + cq.p75_rel * row.train_scale
        p90 = base + cq.p90_rel * row.train_scale
    else:
        p50 = base
        p75 = base * 1.10
        p90 = base * 1.25

    return {'p50': p50, 'p75': p75, 'p90': p90}


def predict_quantiles_hybrid_shrinkage(
    row: FeatureRow,
    cat_quantiles: Dict[str, CategoryQuantiles],
) -> Dict[str, float]:
    """
    Hybrid shrinkage quantile:
    Blends series empirical quantile with category empirical quantile
    based on the observation depth t: weight = t / (t + 5).
    """
    base = row.features['rolling_mean_8_ratio'] * row.train_scale
    if not row.is_variable:
        return {'p50': base, 'p75': base, 'p90': base}

    past_res = _compute_past_residuals(row)
    cq = cat_quantiles.get(row.category)
    if not cq:
        return predict_quantiles_rolling_mad(row, cat_quantiles)

    t = len(past_res)
    w = t / (t + 5.0)

    if t >= 3:
        arr = np.array(past_res, dtype=np.float64) / max(row.train_scale, 1e-6)
        s_p50 = float(np.percentile(arr, 50))
        s_p75 = float(np.percentile(arr, 75))
        s_p90 = float(np.percentile(arr, 90))
    else:
        s_p50 = cq.p50_rel
        s_p75 = cq.p75_rel
        s_p90 = cq.p90_rel

    blended_p50_rel = w * s_p50 + (1.0 - w) * cq.p50_rel
    blended_p75_rel = w * s_p75 + (1.0 - w) * cq.p75_rel
    blended_p90_rel = w * s_p90 + (1.0 - w) * cq.p90_rel

    return {
        'p50': base + blended_p50_rel * row.train_scale,
        'p75': base + blended_p75_rel * row.train_scale,
        'p90': base + blended_p90_rel * row.train_scale,
    }
