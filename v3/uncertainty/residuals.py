"""
v3/uncertainty/residuals.py

Builds residual datasets and precomputes category-level empirical quantiles
from training observations relative to the rolling_mean_8 baseline.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Tuple
from collections import defaultdict
import numpy as np

from v3.forecasting.dataset import ForecastingDataset
from v3.forecasting.features import extract_series_features, FeatureRow


@dataclass
class ResidualSample:
    user_id: str
    category: str
    currency: str
    target_amount: float
    baseline_pred: float
    residual: float
    rel_residual: float
    train_scale: float
    is_variable: bool


@dataclass
class CategoryQuantiles:
    """Precomputed empirical residual quantiles from training data."""
    p50_rel: float
    p75_rel: float
    p90_rel: float
    std_rel: float
    count: int


class ResidualDataset:
    """Manages residual extraction and category reference quantiles."""

    def __init__(self, dataset: ForecastingDataset):
        self.dataset = dataset
        self.train_residuals: List[ResidualSample] = []
        self.category_quantiles: Dict[str, CategoryQuantiles] = {}
        self._build_training_residuals()

    def _build_training_residuals(self) -> None:
        cat_rel_residuals = defaultdict(list)

        for s in self.dataset.series_splits:
            train_rows, _ = extract_series_features(s, min_train_history=1)
            for r in train_rows:
                pred = r.features['rolling_mean_8_ratio'] * r.train_scale
                res = r.target_amount - pred
                rel_res = res / max(r.train_scale, 1e-6)

                sample = ResidualSample(
                    user_id=r.user_id,
                    category=r.category,
                    currency=r.currency,
                    target_amount=r.target_amount,
                    baseline_pred=pred,
                    residual=res,
                    rel_residual=rel_res,
                    train_scale=r.train_scale,
                    is_variable=r.is_variable,
                )
                self.train_residuals.append(sample)
                cat_rel_residuals[r.category].append(rel_res)

        # Precompute quantiles per category
        for cat, rel_list in cat_rel_residuals.items():
            arr = np.array(rel_list, dtype=np.float64)
            self.category_quantiles[cat] = CategoryQuantiles(
                p50_rel=float(np.percentile(arr, 50)),
                p75_rel=float(np.percentile(arr, 75)),
                p90_rel=float(np.percentile(arr, 90)),
                std_rel=float(np.std(arr)),
                count=len(arr),
            )
