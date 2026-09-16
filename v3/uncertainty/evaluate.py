"""
v3/uncertainty/evaluate.py

Evaluation metrics for uncertainty and quantile forecasts:
- Empirical coverage (P50, P75, P90)
- Underprediction / Overprediction rates
- Average interval width & relative interval width
- Pinball loss (quantile loss)
- Cumulative horizon spend coverage
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Any
import numpy as np


@dataclass
class QuantilePredictionRecord:
    user_id: str
    category: str
    currency: str
    target_date: str
    actual: float
    p50: float
    p75: float
    p90: float
    min_balance: float
    is_variable: bool


@dataclass
class QuantileMetricReport:
    sample_count: int
    coverage_p50: float
    coverage_p75: float
    coverage_p90: float
    underest_p90: float
    mean_width_p90_p50: float
    rel_width_p90_p50_pct: float
    pinball_p90: float
    norm_pinball_p90: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            'count': self.sample_count,
            'Cov_P50%': round(self.coverage_p50, 1),
            'Cov_P75%': round(self.coverage_p75, 1),
            'Cov_P90%': round(self.coverage_p90, 1),
            'Underest_P90%': round(self.underest_p90, 1),
            'MeanWidth': round(self.mean_width_p90_p50, 2),
            'RelWidth%': round(self.rel_width_p90_p50_pct, 2),
            'NormPinball': round(self.norm_pinball_p90, 4),
        }


def compute_pinball_loss(y_true: np.ndarray, y_pred: np.ndarray, q: float) -> np.ndarray:
    diff = y_true - y_pred
    return np.maximum(q * diff, (q - 1.0) * diff)


def compute_quantile_metrics(records: List[QuantilePredictionRecord]) -> QuantileMetricReport:
    if not records:
        return QuantileMetricReport(0, 0, 0, 0, 0, 0, 0, 0, 0)

    actuals = np.array([r.actual for r in records], dtype=np.float64)
    p50s = np.array([r.p50 for r in records], dtype=np.float64)
    p75s = np.array([r.p75 for r in records], dtype=np.float64)
    p90s = np.array([r.p90 for r in records], dtype=np.float64)
    min_bals = np.array([max(r.min_balance, 1.0) for r in records], dtype=np.float64)

    cov_50 = float(np.mean(actuals <= p50s) * 100.0)
    cov_75 = float(np.mean(actuals <= p75s) * 100.0)
    cov_90 = float(np.mean(actuals <= p90s) * 100.0)
    under_90 = float(np.mean(actuals > p90s) * 100.0)

    widths = p90s - p50s
    mean_width = float(np.mean(widths))
    rel_widths = widths / np.maximum(p50s, 1e-4) * 100.0
    mean_rel_width = float(np.mean(rel_widths))

    pinball_90 = float(np.mean(compute_pinball_loss(actuals, p90s, 0.90)))
    norm_pinball_90 = float(np.mean(compute_pinball_loss(actuals, p90s, 0.90) / min_bals))

    return QuantileMetricReport(
        sample_count=len(records),
        coverage_p50=cov_50,
        coverage_p75=cov_75,
        coverage_p90=cov_90,
        underest_p90=under_90,
        mean_width_p90_p50=mean_width,
        rel_width_p90_p50_pct=mean_rel_width,
        pinball_p90=pinball_90,
        norm_pinball_p90=norm_pinball_90,
    )
