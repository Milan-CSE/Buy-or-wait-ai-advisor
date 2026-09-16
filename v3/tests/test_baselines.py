"""
v3/tests/test_baselines.py

Unit tests for all statistical baselines.
"""
import sys, os, unittest
sys.path.insert(0, os.path.abspath('.'))
from datetime import date, timedelta
from v3.forecasting.dataset import Observation
from v3.forecasting.features import extract_features_at_step
from v3.forecasting.baselines import (
    predict_naive_last,
    predict_recent_median_3,
    predict_rolling_median_8,
    predict_rolling_mean_8,
    predict_cadence_normalized,
    predict_seasonal_monthly,
)


class TestBaselines(unittest.TestCase):

    def _make_row(self, amounts, dates, target_amount=50.0, target_date=None, is_variable=True):
        start = date(2025, 1, 1)
        if dates is None:
            dates = [start + timedelta(days=7 * i) for i in range(len(amounts))]
        if target_date is None:
            target_date = dates[-1] + timedelta(days=7)

        past_obs = [
            Observation(
                user_id="u1", category="groceries", event_id=f"e{i}", date=dates[i],
                amount=amt, currency="EUR", min_balance=500.0, flexibility="fixed",
                description="desc", is_variable=is_variable
            )
            for i, amt in enumerate(amounts)
        ]
        target_obs = Observation(
            user_id="u1", category="groceries", event_id="target", date=target_date,
            amount=target_amount, currency="EUR", min_balance=500.0, flexibility="fixed",
            description="desc", is_variable=is_variable
        )
        return extract_features_at_step(past_obs, target_obs, train_scale=100.0)

    def test_naive_last(self):
        row = self._make_row([10.0, 20.0, 30.0], None)
        self.assertEqual(predict_naive_last(row), 30.0)

    def test_recent_median_3(self):
        row = self._make_row([10.0, 40.0, 20.0], None)
        self.assertEqual(predict_recent_median_3(row), 20.0)

    def test_rolling_median_8(self):
        amounts = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0]
        row = self._make_row(amounts, None)
        self.assertEqual(predict_rolling_median_8(row), 55.0)

    def test_rolling_mean_8(self):
        amounts = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0]
        row = self._make_row(amounts, None)
        self.assertEqual(predict_rolling_mean_8(row), 45.0)

    def test_cadence_normalized(self):
        amounts = [100.0, 100.0, 100.0, 100.0]
        start = date(2025, 1, 1)
        dates = [start, start + timedelta(days=7), start + timedelta(days=14), start + timedelta(days=21)]
        target_date = dates[-1] + timedelta(days=14)
        row = self._make_row(amounts, dates, target_date=target_date, is_variable=True)
        self.assertEqual(predict_cadence_normalized(row), 200.0)

    def test_seasonal_monthly(self):
        dates = [date(2025, 1, 15), date(2025, 2, 15), date(2025, 3, 15)]
        amounts = [120.0, 130.0, 140.0]
        target_date = date(2025, 4, 15)
        row = self._make_row(amounts, dates, target_date=target_date)
        self.assertEqual(predict_seasonal_monthly(row), 130.0)


if __name__ == '__main__':
    unittest.main()
