"""
v3/forecasting/evaluate.py

Evaluation metrics for financial forecasting.
Computes raw (MAE, RMSE, MedAE), scale-aware (MAPE, sMAPE, MASE, Norm-MAE),
and risk metrics (underestimate/overestimate rates), overall and segmented.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict
import math
import statistics
import numpy as np


@dataclass
class PredictionRecord:
    """A single evaluation prediction record."""
    user_id: str
    category: str
    currency: str
    event_id: str
    target_date: str
    actual: float
    predicted: float
    min_balance: float
    is_variable: bool
    in_sample_naive_mae: float  # For MASE computation


@dataclass
class MetricReport:
    """Aggregated evaluation metrics."""
    sample_count: int
    mae: float
    rmse: float
    med_ae: float
    mape: float  # percentage
    smape: float  # percentage
    mase: float
    norm_mae: float  # MAE / min_balance_to_keep
    underestimate_rate: float  # percentage predicted < actual (safety risk)
    overestimate_rate: float  # percentage predicted > actual (conservative)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'count': self.sample_count,
            'MAE': round(self.mae, 2),
            'RMSE': round(self.rmse, 2),
            'MedAE': round(self.med_ae, 2),
            'MAPE%': round(self.mape, 2),
            'sMAPE%': round(self.smape, 2),
            'MASE': round(self.mase, 4),
            'NormMAE%': round(self.norm_mae * 100, 4),
            'Underest%': round(self.underestimate_rate, 1),
            'Overest%': round(self.overestimate_rate, 1),
        }


def compute_metrics(records: List[PredictionRecord]) -> MetricReport:
    """Compute all evaluation metrics across a list of prediction records."""
    if not records:
        return MetricReport(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    n = len(records)
    actuals = np.array([r.actual for r in records], dtype=np.float64)
    preds = np.array([r.predicted for r in records], dtype=np.float64)
    min_bals = np.array([max(r.min_balance, 1.0) for r in records], dtype=np.float64)
    naive_maes = np.array([r.in_sample_naive_mae for r in records], dtype=np.float64)

    errors = np.abs(actuals - preds)
    mae = float(np.mean(errors))
    rmse = float(np.sqrt(np.mean(errors ** 2)))
    med_ae = float(np.median(errors))

    # MAPE (safely avoid div by zero)
    safe_actuals = np.maximum(actuals, 1e-4)
    mape = float(np.mean(errors / safe_actuals) * 100.0)

    # sMAPE
    denom = (np.abs(actuals) + np.abs(preds)) / 2.0
    safe_denom = np.maximum(denom, 1e-4)
    smape = float(np.mean(errors / safe_denom) * 100.0)

    # MASE: scale by in-sample naive error where available (>0)
    valid_naive = naive_maes > 1e-6
    if np.any(valid_naive):
        mase = float(np.mean(errors[valid_naive] / naive_maes[valid_naive]))
    else:
        mase = 1.0

    # Norm-MAE: error relative to user's minimum balance
    norm_mae = float(np.mean(errors / min_bals))

    # Risk metrics
    under = float(np.mean(preds < actuals) * 100.0)
    over = float(np.mean(preds > actuals) * 100.0)

    return MetricReport(
        sample_count=n,
        mae=mae,
        rmse=rmse,
        med_ae=med_ae,
        mape=mape,
        smape=smape,
        mase=mase,
        norm_mae=norm_mae,
        underestimate_rate=under,
        overestimate_rate=over,
    )


def evaluate_segmented(
    records: List[PredictionRecord],
) -> Dict[str, Dict[str, MetricReport]]:
    """
    Computes metrics segmented by:
    - 'overall': all records
    - 'category_type': variable vs fixed
    - 'category': top categories
    - 'currency': INR, IDR, ZAR, USD, EUR
    """
    res: Dict[str, Dict[str, MetricReport]] = {}

    # Overall
    res['overall'] = {'all': compute_metrics(records)}

    # Category Type
    res['category_type'] = {
        'variable': compute_metrics([r for r in records if r.is_variable]),
        'fixed': compute_metrics([r for r in records if not r.is_variable]),
    }

    # Currency
    by_ccy = defaultdict(list)
    for r in records:
        by_ccy[r.currency].append(r)
    res['currency'] = {ccy: compute_metrics(rec_list) for ccy, rec_list in sorted(by_ccy.items())}

    # Category
    by_cat = defaultdict(list)
    for r in records:
        by_cat[r.category].append(r)
    res['category'] = {cat: compute_metrics(rec_list) for cat, rec_list in sorted(by_cat.items())}

    return res
