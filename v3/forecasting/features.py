"""
v3/forecasting/features.py

Feature extraction for transaction amount forecasting.
Strictly time-aware: computes features for observation at index t using ONLY
prior observations [0, ..., t-1] in the chronological sequence.
Zero future leakage.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Tuple, Any
import statistics

from v3.forecasting.dataset import Observation, SeriesSplit


FEATURE_NAMES = [
    # Normalized amount history (scale-invariant)
    'lag1_ratio',
    'lag2_ratio',
    'lag3_ratio',
    'rolling_mean_3_ratio',
    'rolling_median_3_ratio',
    'rolling_mean_8_ratio',
    'rolling_median_8_ratio',
    'rolling_min_ratio',
    'rolling_max_ratio',
    # Variability
    'rolling_cv',
    'recent_trend',
    # Cadence & Recency
    'days_since_last',
    'mean_cadence',
    'median_cadence',
    'cadence_ratio',
    # Calendar position
    'target_day_of_week',
    'target_day_of_month',
    'target_month',
    'is_weekend',
    # Context
    'history_length',
    'is_variable',
]

CATEGORICAL_FEATURES = ['category', 'currency']


@dataclass
class FeatureRow:
    """Extracted feature vector for a single target observation."""
    user_id: str
    category: str
    currency: str
    event_id: str
    target_date: date
    target_amount: float
    target_ratio: float
    train_scale: float
    min_balance: float
    is_variable: bool
    features: Dict[str, float]
    history_amounts: List[float]
    history_dates: List[date]

    def to_dict(self) -> Dict[str, Any]:
        d = dict(self.features)
        d['target_amount'] = self.target_amount
        d['target_ratio'] = self.target_ratio
        d['train_scale'] = self.train_scale
        d['category'] = self.category
        d['currency'] = self.currency
        d['user_id'] = self.user_id
        d['event_id'] = self.event_id
        d['target_date'] = self.target_date
        return d


def extract_features_at_step(
    past_obs: List[Observation],
    target_obs: Observation,
    train_scale: float,
) -> FeatureRow:
    """
    Extracts features for target_obs using ONLY past_obs.
    Guaranteed: past_obs contains only strictly preceding observations.
    """
    assert len(past_obs) >= 1, "At least 1 past observation required for feature extraction"
    
    amounts = [o.amount for o in past_obs]
    dates = [o.date for o in past_obs]
    t = len(past_obs)
    scale = max(train_scale, 1e-6)

    # Lags
    lag1 = amounts[-1]
    lag2 = amounts[-2] if t >= 2 else amounts[-1]
    lag3 = amounts[-3] if t >= 3 else amounts[-2] if t >= 2 else amounts[-1]

    # Rolling windows
    win3 = amounts[-3:] if t >= 3 else amounts
    mean3 = statistics.mean(win3)
    med3 = statistics.median(win3)

    win8 = amounts[-8:] if t >= 8 else amounts
    mean8 = statistics.mean(win8)
    med8 = statistics.median(win8)

    min_val = min(amounts)
    max_val = max(amounts)

    # Variability (all past)
    if t >= 2:
        std_val = statistics.stdev(amounts)
        mean_all = statistics.mean(amounts)
        cv = std_val / mean_all if mean_all > 0 else 0.0
    else:
        cv = 0.0

    # Trend: (lag1 - lag3) / lag3
    if t >= 3 and lag3 > 0:
        trend = (lag1 - lag3) / lag3
    else:
        trend = 0.0

    # Cadence
    days_since_last = (target_obs.date - dates[-1]).days
    if t >= 2:
        gaps = [(dates[i] - dates[i-1]).days for i in range(1, t)]
        mean_cad = statistics.mean(gaps)
        med_cad = statistics.median(gaps)
    else:
        mean_cad = float(days_since_last)
        med_cad = float(days_since_last)

    cad_ratio = days_since_last / med_cad if med_cad > 0 else 1.0

    # Calendar
    td = target_obs.date
    dow = td.weekday()
    dom = td.day
    month = td.month
    is_wknd = 1.0 if dow >= 5 else 0.0

    feat_dict: Dict[str, float] = {
        'lag1_ratio': lag1 / scale,
        'lag2_ratio': lag2 / scale,
        'lag3_ratio': lag3 / scale,
        'rolling_mean_3_ratio': mean3 / scale,
        'rolling_median_3_ratio': med3 / scale,
        'rolling_mean_8_ratio': mean8 / scale,
        'rolling_median_8_ratio': med8 / scale,
        'rolling_min_ratio': min_val / scale,
        'rolling_max_ratio': max_val / scale,
        'rolling_cv': cv,
        'recent_trend': trend,
        'days_since_last': float(days_since_last),
        'mean_cadence': float(mean_cad),
        'median_cadence': float(med_cad),
        'cadence_ratio': float(cad_ratio),
        'target_day_of_week': float(dow),
        'target_day_of_month': float(dom),
        'target_month': float(month),
        'is_weekend': is_wknd,
        'history_length': float(t),
        'is_variable': 1.0 if target_obs.is_variable else 0.0,
    }

    target_ratio = target_obs.amount / scale

    return FeatureRow(
        user_id=target_obs.user_id,
        category=target_obs.category,
        currency=target_obs.currency,
        event_id=target_obs.event_id,
        target_date=target_obs.date,
        target_amount=target_obs.amount,
        target_ratio=target_ratio,
        train_scale=scale,
        min_balance=target_obs.min_balance,
        is_variable=target_obs.is_variable,
        features=feat_dict,
        history_amounts=amounts,
        history_dates=dates,
    )


def extract_series_features(
    split: SeriesSplit,
    min_train_history: int = 1,
) -> Tuple[List[FeatureRow], List[FeatureRow]]:
    """
    Extracts chronological features for a series split.
    
    Training rows:
      For t in [min_train_history, len(train_obs) - 1]:
        features using train_obs[:t], predicting train_obs[t]
        
    Test rows:
      For t in [0, len(test_obs) - 1]:
        all past = train_obs + test_obs[:t]
        features using all past, predicting test_obs[t]
        
    Guarantees: Every row only sees observations strictly prior to it!
    """
    train_rows: List[FeatureRow] = []
    test_rows: List[FeatureRow] = []

    # Training set features
    train_obs = split.train_observations
    for t in range(min_train_history, len(train_obs)):
        row = extract_features_at_step(
            past_obs=train_obs[:t],
            target_obs=train_obs[t],
            train_scale=split.train_scale,
        )
        train_rows.append(row)

    # Test set features (expanding window across test points)
    test_obs = split.test_observations
    for t in range(len(test_obs)):
        full_past = train_obs + test_obs[:t]
        row = extract_features_at_step(
            past_obs=full_past,
            target_obs=test_obs[t],
            train_scale=split.train_scale,
        )
        test_rows.append(row)

    return train_rows, test_rows
