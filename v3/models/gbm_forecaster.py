"""
v3/models/gbm_forecaster.py

Interpretable Gradient Boosting Forecaster for transaction amounts.
Uses HistGradientBoostingRegressor from scikit-learn.
Trains on normalized targets (target_ratio = amount / train_scale) to ensure
scale-invariance across currencies, then predicts in original currency units.
"""
from __future__ import annotations
from typing import Dict, List, Optional, Tuple, Any
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance

from v3.forecasting.features import FeatureRow, FEATURE_NAMES


class GBMForecaster:
    """Gradient Boosting Regressor for normalized transaction amount forecasting."""

    def __init__(
        self,
        max_iter: int = 150,
        max_depth: int = 5,
        learning_rate: float = 0.05,
        min_samples_leaf: int = 20,
        l2_regularization: float = 1.0,
        random_state: int = 42,
    ):
        self.feature_names = list(FEATURE_NAMES)
        self.model = HistGradientBoostingRegressor(
            max_iter=max_iter,
            max_depth=max_depth,
            learning_rate=learning_rate,
            min_samples_leaf=min_samples_leaf,
            l2_regularization=l2_regularization,
            random_state=random_state,
            early_stopping=True,
            validation_fraction=0.15,
            n_iter_no_change=10,
        )
        self.is_fitted = False
        self.importances_: Optional[Dict[str, float]] = None

    def _row_to_x(self, row: FeatureRow) -> np.ndarray:
        return np.array([row.features[fn] for fn in self.feature_names], dtype=np.float64)

    def fit(self, train_rows: List[FeatureRow]) -> GBMForecaster:
        """Fits model on normalized targets (target_ratio)."""
        X = np.array([self._row_to_x(r) for r in train_rows], dtype=np.float64)
        y = np.array([r.target_ratio for r in train_rows], dtype=np.float64)

        # Clip extreme outliers in training target ratio for robustness
        y = np.clip(y, 0.05, 20.0)

        self.model.fit(X, y)
        self.is_fitted = True
        return self

    def predict_ratio(self, row: FeatureRow) -> float:
        """Predicts normalized target ratio."""
        if not self.is_fitted:
            raise RuntimeError("Model not fitted")
        x = self._row_to_x(row).reshape(1, -1)
        pred_ratio = float(self.model.predict(x)[0])
        # Amounts cannot be negative
        return max(0.01, pred_ratio)

    def predict(self, row: FeatureRow) -> float:
        """Predicts actual amount in home currency by multiplying predicted ratio by train_scale."""
        pred_ratio = self.predict_ratio(row)
        return float(pred_ratio * row.train_scale)

    def compute_feature_importance(self, val_rows: List[FeatureRow]) -> Dict[str, float]:
        """Computes permutation feature importance on validation rows."""
        if not self.is_fitted:
            raise RuntimeError("Model not fitted")
        X = np.array([self._row_to_x(r) for r in val_rows], dtype=np.float64)
        y = np.array([r.target_ratio for r in val_rows], dtype=np.float64)
        y = np.clip(y, 0.05, 20.0)

        perm = permutation_importance(self.model, X, y, n_repeats=5, random_state=42)
        importances = {}
        for name, imp in zip(self.feature_names, perm.importances_mean):
            importances[name] = float(imp)
        self.importances_ = dict(sorted(importances.items(), key=lambda x: -x[1]))
        return self.importances_
