"""
v3/models/quantile_gbm.py

Machine Learning Quantile Regression Model.
Uses HistGradientBoostingRegressor with loss='quantile'
trained separately for q=0.50, q=0.75, and q=0.90.
Trains on normalized targets (amount / train_scale) for currency invariance.
"""
from __future__ import annotations
from typing import Dict, List
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor

from v3.forecasting.features import FeatureRow, FEATURE_NAMES


class QuantileGBM:
    """Multi-quantile Gradient Boosting Regressor."""

    def __init__(
        self,
        max_iter: int = 120,
        max_depth: int = 4,
        learning_rate: float = 0.05,
        min_samples_leaf: int = 25,
        random_state: int = 42,
    ):
        self.feature_names = list(FEATURE_NAMES)
        self.models: Dict[float, HistGradientBoostingRegressor] = {
            0.50: HistGradientBoostingRegressor(
                loss='quantile', quantile=0.50, max_iter=max_iter, max_depth=max_depth,
                learning_rate=learning_rate, min_samples_leaf=min_samples_leaf, random_state=random_state
            ),
            0.75: HistGradientBoostingRegressor(
                loss='quantile', quantile=0.75, max_iter=max_iter, max_depth=max_depth,
                learning_rate=learning_rate, min_samples_leaf=min_samples_leaf, random_state=random_state
            ),
            0.90: HistGradientBoostingRegressor(
                loss='quantile', quantile=0.90, max_iter=max_iter, max_depth=max_depth,
                learning_rate=learning_rate, min_samples_leaf=min_samples_leaf, random_state=random_state
            ),
        }
        self.is_fitted = False

    def _row_to_x(self, row: FeatureRow) -> np.ndarray:
        return np.array([row.features[fn] for fn in self.feature_names], dtype=np.float64)

    def fit(self, train_rows: List[FeatureRow]) -> QuantileGBM:
        X = np.array([self._row_to_x(r) for r in train_rows], dtype=np.float64)
        y = np.array([r.target_ratio for r in train_rows], dtype=np.float64)
        y = np.clip(y, 0.05, 20.0)

        for q, model in self.models.items():
            model.fit(X, y)

        self.is_fitted = True
        return self

    def predict_quantiles(self, row: FeatureRow) -> Dict[str, float]:
        if not self.is_fitted:
            raise RuntimeError("Model not fitted")
        x = self._row_to_x(row).reshape(1, -1)
        p50_ratio = float(self.models[0.50].predict(x)[0])
        p75_ratio = float(self.models[0.75].predict(x)[0])
        p90_ratio = float(self.models[0.90].predict(x)[0])

        # Enforce monotonicity: P50 <= P75 <= P90
        p50_ratio = max(0.01, p50_ratio)
        p75_ratio = max(p50_ratio, p75_ratio)
        p90_ratio = max(p75_ratio, p90_ratio)

        scale = row.train_scale
        return {
            'p50': p50_ratio * scale,
            'p75': p75_ratio * scale,
            'p90': p90_ratio * scale,
        }
