"""
v3/tests/test_uncertainty.py

Unit tests for uncertainty quantification modules.
"""
import sys, os, unittest
sys.path.insert(0, os.path.abspath('.'))
from datetime import date, timedelta

from v3.forecasting.dataset import Observation
from v3.forecasting.features import extract_features_at_step
from v3.uncertainty.residuals import CategoryQuantiles
from v3.uncertainty.quantiles import (
    predict_quantiles_rolling_mad,
    predict_quantiles_category_empirical,
    predict_quantiles_hybrid_shrinkage,
)
from v3.uncertainty.evaluate import compute_quantile_metrics, QuantilePredictionRecord


class TestUncertainty(unittest.TestCase):

    def _make_row(self, amounts, is_variable=True):
        start = date(2025, 1, 1)
        dates = [start + timedelta(days=7 * i) for i in range(len(amounts))]
        past_obs = [
            Observation(
                user_id="u1", category="groceries", event_id=f"e{i}", date=dates[i],
                amount=amt, currency="EUR", min_balance=500.0, flexibility="fixed",
                description="desc", is_variable=is_variable
            )
            for i, amt in enumerate(amounts)
        ]
        target_obs = Observation(
            user_id="u1", category="groceries", event_id="target", date=dates[-1] + timedelta(days=7),
            amount=100.0, currency="EUR", min_balance=500.0, flexibility="fixed",
            description="desc", is_variable=is_variable
        )
        return extract_features_at_step(past_obs, target_obs, train_scale=100.0)

    def test_monotonicity_rolling_mad(self):
        cat_q = {'groceries': CategoryQuantiles(0.0, 0.14, 0.24, 0.18, 100)}
        row = self._make_row([80.0, 100.0, 120.0, 90.0, 110.0])
        res = predict_quantiles_rolling_mad(row, cat_q)
        self.assertLessEqual(res['p50'], res['p75'])
        self.assertLessEqual(res['p75'], res['p90'])

    def test_fixed_category_zero_spread(self):
        cat_q = {}
        row = self._make_row([500.0, 500.0, 500.0], is_variable=False)
        res = predict_quantiles_rolling_mad(row, cat_q)
        self.assertEqual(res['p50'], res['p75'])
        self.assertEqual(res['p75'], res['p90'])

    def test_coverage_computation(self):
        records = [
            QuantilePredictionRecord("u1", "c", "EUR", "2025-01-01", 100.0, 90.0, 110.0, 120.0, 500.0, True),
            QuantilePredictionRecord("u1", "c", "EUR", "2025-01-02", 115.0, 90.0, 110.0, 120.0, 500.0, True),
            QuantilePredictionRecord("u1", "c", "EUR", "2025-01-03", 130.0, 90.0, 110.0, 120.0, 500.0, True),
            QuantilePredictionRecord("u1", "c", "EUR", "2025-01-04", 80.0, 90.0, 110.0, 120.0, 500.0, True),
        ]
        m = compute_quantile_metrics(records)
        # Actuals: 100, 115, 130, 80
        # P50 = 90 -> 80 <= 90 (1/4 = 25%)
        self.assertEqual(m.coverage_p50, 25.0)
        # P75 = 110 -> 100, 80 <= 110 (2/4 = 50%)
        self.assertEqual(m.coverage_p75, 50.0)
        # P90 = 120 -> 100, 115, 80 <= 120 (3/4 = 75%)
        self.assertEqual(m.coverage_p90, 75.0)
        self.assertEqual(m.underest_p90, 25.0)


if __name__ == '__main__':
    unittest.main()
