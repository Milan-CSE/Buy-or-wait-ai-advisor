"""
v3/forecasting/dataset.py

Builds reproducible forecasting datasets from historical settled transactions.
Implements strict per-series temporal train/test splitting (70% earliest / 30% latest)
with explicit history qualification (N >= 5 observations required).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
import math
import sys
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import os

# Add 'code' to path for V2 loader reuse (read-only)
sys.path.insert(0, os.path.abspath('code'))
from data_loader import load_dataset, Dataset
from currency import FXEngine
from event_lifecycle import resolve_user_events, CashType

VARIABLE_CATEGORIES = frozenset([
    'groceries', 'transport', 'dining',
    'shopping', 'entertainment', 'healthcare',
    'personal_care', 'clothing', 'fitness', 'miscellaneous',
    'travel', 'gifts', 'childcare', 'electronics',
])

FIXED_CATEGORIES = frozenset([
    'rent', 'utilities', 'debt_repayment', 'insurance', 'housing',
    'streaming', 'music_subscription', 'cloud_storage', 'delivery_membership',
    'education', 'family_support', 'gym',
])


@dataclass
class Observation:
    """A single settled debit event in a time series."""
    user_id: str
    category: str
    event_id: str
    date: date
    amount: float
    currency: str
    min_balance: float
    flexibility: str
    description: str
    is_variable: bool


@dataclass
class SeriesSplit:
    """Temporal split for a single (user_id, category) series."""
    user_id: str
    category: str
    currency: str
    min_balance: float
    is_variable: bool
    train_observations: List[Observation]
    test_observations: List[Observation]
    train_scale: float  # Median of train amounts for normalization

    @property
    def total_count(self) -> int:
        return len(self.train_observations) + len(self.test_observations)

    @property
    def train_count(self) -> int:
        return len(self.train_observations)

    @property
    def test_count(self) -> int:
        return len(self.test_observations)


@dataclass
class ForecastingDataset:
    """Complete forecasting dataset with per-series temporal splits."""
    series_splits: List[SeriesSplit]
    excluded_series: List[Tuple[str, str, int]]  # (user_id, category, count)
    min_history: int

    @property
    def num_eligible_series(self) -> int:
        return len(self.series_splits)

    @property
    def num_excluded_series(self) -> int:
        return len(self.excluded_series)

    @property
    def total_train_samples(self) -> int:
        return sum(s.train_count for s in self.series_splits)

    @property
    def total_test_samples(self) -> int:
        return sum(s.test_count for s in self.series_splits)

    def summary(self) -> Dict[str, any]:
        var_splits = [s for s in self.series_splits if s.is_variable]
        fix_splits = [s for s in self.series_splits if not s.is_variable]
        return {
            'min_history_threshold': self.min_history,
            'eligible_series_count': self.num_eligible_series,
            'excluded_series_count': self.num_excluded_series,
            'variable_series_count': len(var_splits),
            'fixed_series_count': len(fix_splits),
            'total_train_samples': self.total_train_samples,
            'total_test_samples': self.total_test_samples,
            'variable_train_samples': sum(s.train_count for s in var_splits),
            'variable_test_samples': sum(s.test_count for s in var_splits),
            'fixed_train_samples': sum(s.train_count for s in fix_splits),
            'fixed_test_samples': sum(s.test_count for s in fix_splits),
        }


def build_forecasting_dataset(
    min_history: int = 5,
    train_ratio: float = 0.70,
    dataset: Optional[Dataset] = None,
    fx: Optional[FXEngine] = None,
) -> ForecastingDataset:
    """
    Builds the forecasting dataset from resolved settled debit transactions.
    
    Splitting Rules:
    1. For each (user_id, category), gather all settled debit events.
    2. Sort chronologically by (settlement_date, event_date, event_id).
    3. If total observations N < min_history, exclude the series.
    4. For N >= min_history:
       - train_count = max(3, floor(train_ratio * N))
       - test_count = N - train_count
       - train_obs = observations[:train_count]
       - test_obs = observations[train_count:]
       - train_scale = median of train_obs amounts
    """
    if dataset is None:
        dataset = load_dataset()
    if fx is None:
        fx = FXEngine(dataset.fx_index)

    series_map = defaultdict(list)
    for uid in sorted(dataset.profiles.keys()):
        profile = dataset.profiles[uid]
        events = resolve_user_events(uid, dataset, fx)
        settled_debits = [
            e for e in events
            if e.cash_type == CashType.IMMEDIATE_DEBIT
            and e.settlement_date is not None
            and e.amount_home > Decimal('0')
        ]
        min_bal = float(profile.minimum_balance_to_keep)

        for e in settled_debits:
            is_var = e.category in VARIABLE_CATEGORIES
            obs = Observation(
                user_id=uid,
                category=e.category,
                event_id=e.event_id,
                date=e.settlement_date,
                amount=float(e.amount_home),
                currency=profile.home_currency,
                min_balance=min_bal,
                flexibility=e.flexibility,
                description=e.description,
                is_variable=is_var,
            )
            series_map[(uid, e.category)].append(obs)

    splits: List[SeriesSplit] = []
    excluded: List[Tuple[str, str, int]] = []

    for (uid, cat), observations in sorted(series_map.items()):
        observations.sort(key=lambda o: (o.date, o.event_id))
        n = len(observations)

        if n < min_history:
            excluded.append((uid, cat, n))
            continue

        n_train = max(3, math.floor(train_ratio * n))
        train_obs = observations[:n_train]
        test_obs = observations[n_train:]

        train_amounts = [o.amount for o in train_obs]
        train_amounts_sorted = sorted(train_amounts)
        mid = len(train_amounts_sorted) // 2
        if len(train_amounts_sorted) % 2 == 1:
            scale = train_amounts_sorted[mid]
        else:
            scale = (train_amounts_sorted[mid - 1] + train_amounts_sorted[mid]) / 2.0
        if scale <= 0.0:
            scale = sum(train_amounts) / len(train_amounts) if train_amounts else 1.0

        is_var = cat in VARIABLE_CATEGORIES
        ccy = train_obs[0].currency
        min_bal = train_obs[0].min_balance

        splits.append(SeriesSplit(
            user_id=uid,
            category=cat,
            currency=ccy,
            min_balance=min_bal,
            is_variable=is_var,
            train_observations=train_obs,
            test_observations=test_obs,
            train_scale=scale,
        ))

    return ForecastingDataset(
        series_splits=splits,
        excluded_series=excluded,
        min_history=min_history,
    )
