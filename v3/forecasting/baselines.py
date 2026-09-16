"""
v3/forecasting/baselines.py

Statistical and deterministic forecasting baselines.
All baselines predict the next transaction amount using strictly past history.
"""
from __future__ import annotations
from typing import Dict, List, Callable, Any
from datetime import date
import statistics

from v3.forecasting.features import FeatureRow


def predict_naive_last(row: FeatureRow) -> float:
    """Predict the amount of the most recent historical observation."""
    return row.history_amounts[-1]


def predict_recent_median_3(row: FeatureRow) -> float:
    """Predict median of the last 3 historical observations."""
    amounts = row.history_amounts
    win = amounts[-3:] if len(amounts) >= 3 else amounts
    return float(statistics.median(win))


def predict_rolling_median_8(row: FeatureRow) -> float:
    """
    Predict median of the last 8 historical observations.
    Matches V2's _project_variable_category heuristic.
    """
    amounts = row.history_amounts
    win = amounts[-8:] if len(amounts) >= 8 else amounts
    return float(statistics.median(win))


def predict_rolling_mean_8(row: FeatureRow) -> float:
    """Predict mean of the last 8 historical observations."""
    amounts = row.history_amounts
    win = amounts[-8:] if len(amounts) >= 8 else amounts
    return float(statistics.mean(win))


def predict_cadence_normalized(row: FeatureRow) -> float:
    """
    Cadence-normalized prediction:
    Scales the rolling median by the ratio of elapsed days to typical cadence
    for variable categories, clamped to [0.5, 2.0].
    Fixed categories return rolling median.
    """
    base = predict_rolling_median_8(row)
    if not row.is_variable:
        return base
    ratio = row.features.get('cadence_ratio', 1.0)
    clamped_ratio = max(0.5, min(2.0, ratio))
    return float(base * clamped_ratio)


def predict_seasonal_monthly(row: FeatureRow) -> float:
    """
    Seasonal/monthly baseline:
    If historical observations exist around the same day of month (+/- 3 days)
    or in the same calendar month, uses their median; otherwise falls back to rolling median.
    """
    target_dom = row.target_date.day
    target_m = row.target_date.month
    dates = row.history_dates
    amounts = row.history_amounts

    same_dom_amounts = [
        amt for dt, amt in zip(dates, amounts)
        if abs(dt.day - target_dom) <= 3
    ]
    if len(same_dom_amounts) >= 2:
        return float(statistics.median(same_dom_amounts))

    same_m_amounts = [
        amt for dt, amt in zip(dates, amounts)
        if dt.month == target_m
    ]
    if len(same_m_amounts) >= 2:
        return float(statistics.median(same_m_amounts))

    return predict_rolling_median_8(row)


BASELINES: Dict[str, Callable[[FeatureRow], float]] = {
    'naive_last': predict_naive_last,
    'recent_median_3': predict_recent_median_3,
    'rolling_median_8': predict_rolling_median_8,
    'rolling_mean_8': predict_rolling_mean_8,
    'cadence_normalized': predict_cadence_normalized,
    'seasonal_monthly': predict_seasonal_monthly,
}
