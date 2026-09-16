"""
v3/tests/test_leakage.py

Verification of zero future data leakage.
"""
import sys, os, unittest, copy
sys.path.insert(0, os.path.abspath('.'))
from datetime import date, timedelta
from v3.forecasting.dataset import Observation, SeriesSplit
from v3.forecasting.features import extract_series_features


class TestLeakage(unittest.TestCase):

    def _make_sample_series(self, n: int = 10, base_amount: float = 100.0) -> SeriesSplit:
        start_date = date(2025, 1, 1)
        obs_list = []
        for i in range(n):
            obs = Observation(
                user_id="user_test",
                category="groceries",
                event_id=f"evt_{i}",
                date=start_date + timedelta(days=7 * i),
                amount=base_amount + float(i * 10),
                currency="USD",
                min_balance=1000.0,
                flexibility="fixed",
                description="Grocery store",
                is_variable=True,
            )
            obs_list.append(obs)

        n_train = 7
        return SeriesSplit(
            user_id="user_test",
            category="groceries",
            currency="USD",
            min_balance=1000.0,
            is_variable=True,
            train_observations=obs_list[:n_train],
            test_observations=obs_list[n_train:],
            train_scale=base_amount,
        )

    def test_no_future_leakage_on_mutation(self):
        """Mutating future events must not change feature row at step t."""
        split = self._make_sample_series(n=10)
        train_rows, test_rows = extract_series_features(split)
        original_row0_features = copy.deepcopy(test_rows[0].features)

        # Now mutate subsequent test observations (index 1, 2)
        split_mutated = self._make_sample_series(n=10)
        split_mutated.test_observations[1].amount = 999999.0
        split_mutated.test_observations[2].amount = 888888.0

        _, test_rows_mutated = extract_series_features(split_mutated)
        mutated_row0_features = test_rows_mutated[0].features

        self.assertEqual(original_row0_features, mutated_row0_features, "Future mutation leaked into current features!")

    def test_strict_temporal_ordering(self):
        """Dates in train must be strictly before or equal to the earliest test date."""
        split = self._make_sample_series(n=10)
        last_train_date = split.train_observations[-1].date
        first_test_date = split.test_observations[0].date
        self.assertLessEqual(last_train_date, first_test_date, "Train and test dates are inverted!")

    def test_history_length_matches_past_count(self):
        """Features history_length must equal exact number of past observations."""
        split = self._make_sample_series(n=10)
        train_rows, test_rows = extract_series_features(split)

        for idx, row in enumerate(test_rows):
            expected_len = len(split.train_observations) + idx
            self.assertEqual(row.features['history_length'], expected_len)


if __name__ == '__main__':
    unittest.main()
