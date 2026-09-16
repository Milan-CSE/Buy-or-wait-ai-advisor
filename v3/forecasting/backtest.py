"""
v3/forecasting/backtest.py

Time-based backtesting engine.
Simulates out-of-time forecasting across all series splits.
For each test observation, predictions are made using ONLY data available
strictly before the observation date.
"""
from __future__ import annotations
from typing import Dict, List, Callable, Optional, Tuple, Any
from datetime import date
import statistics

from v3.forecasting.dataset import ForecastingDataset, SeriesSplit
from v3.forecasting.features import extract_series_features, FeatureRow
from v3.forecasting.evaluate import PredictionRecord, MetricReport, compute_metrics, evaluate_segmented
from v3.forecasting.baselines import BASELINES


class BacktestRunner:
    """Executes time-based backtests on ForecastingDataset splits."""

    def __init__(self, dataset: ForecastingDataset):
        self.dataset = dataset
        # Precompute in-sample naive error per series
        self.naive_mae_map: Dict[Tuple[str, str], float] = {}
        self._compute_naive_maes()

    def _compute_naive_maes(self) -> None:
        """Compute in-sample one-step naive MAE for each series on training data."""
        for s in self.dataset.series_splits:
            train_amts = [o.amount for o in s.train_observations]
            if len(train_amts) >= 2:
                diffs = [abs(train_amts[i] - train_amts[i-1]) for i in range(1, len(train_amts))]
                self.naive_mae_map[(s.user_id, s.category)] = float(statistics.mean(diffs))
            else:
                self.naive_mae_map[(s.user_id, s.category)] = 1.0

    def evaluate_baseline(
        self,
        baseline_name: str,
    ) -> Tuple[List[PredictionRecord], Dict[str, Dict[str, MetricReport]]]:
        """Evaluates a named statistical baseline on all test points."""
        fn = BASELINES[baseline_name]
        records: List[PredictionRecord] = []

        for s in self.dataset.series_splits:
            train_rows, test_rows = extract_series_features(s)
            naive_err = self.naive_mae_map.get((s.user_id, s.category), 1.0)

            for row in test_rows:
                pred = fn(row)
                records.append(PredictionRecord(
                    user_id=row.user_id,
                    category=row.category,
                    currency=row.currency,
                    event_id=row.event_id,
                    target_date=str(row.target_date),
                    actual=row.target_amount,
                    predicted=float(pred),
                    min_balance=row.min_balance,
                    is_variable=row.is_variable,
                    in_sample_naive_mae=naive_err,
                ))

        segmented = evaluate_segmented(records)
        return records, segmented

    def evaluate_model(
        self,
        predict_fn: Callable[[FeatureRow], float],
        model_name: str = 'ml_model',
    ) -> Tuple[List[PredictionRecord], Dict[str, Dict[str, MetricReport]]]:
        """Evaluates any custom prediction function on all test points."""
        records: List[PredictionRecord] = []

        for s in self.dataset.series_splits:
            train_rows, test_rows = extract_series_features(s)
            naive_err = self.naive_mae_map.get((s.user_id, s.category), 1.0)

            for row in test_rows:
                pred = predict_fn(row)
                records.append(PredictionRecord(
                    user_id=row.user_id,
                    category=row.category,
                    currency=row.currency,
                    event_id=row.event_id,
                    target_date=str(row.target_date),
                    actual=row.target_amount,
                    predicted=float(pred),
                    min_balance=row.min_balance,
                    is_variable=row.is_variable,
                    in_sample_naive_mae=naive_err,
                ))

        segmented = evaluate_segmented(records)
        return records, segmented
