"""
currency.py
Exact dated foreign-exchange lookup using (settlement_date, from_currency, to_currency).
No silent fallback. Raises an explicit error if a rate is missing.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Dict, Optional, Tuple


class FXRateMissingError(Exception):
    """Raised when an exact rate record is not found."""


class FXEngine:
    """
    Looks up rates strictly by (rate_date, from_currency, to_currency).
    Home-currency-to-home-currency conversions return 1.
    """

    def __init__(self, fx_index: Dict[Tuple[date, str, str], Decimal]):
        self._index = fx_index
        # Build per-pair sorted date lists for diagnostic purposes
        self._pairs: Dict[Tuple[str, str], list] = {}
        for (d, frm, to), rate in fx_index.items():
            self._pairs.setdefault((frm, to), []).append(d)
        for k in self._pairs:
            self._pairs[k].sort()

    def convert(
        self,
        amount: Decimal,
        from_currency: str,
        to_currency: str,
        settlement_dt: date,
    ) -> Decimal:
        """
        Convert *amount* from from_currency to to_currency using the rate
        on *exactly* settlement_dt.

        Returns amount unchanged when from_currency == to_currency.
        Raises FXRateMissingError when the exact (date, pair) is absent.
        """
        if from_currency == to_currency:
            return amount

        key = (settlement_dt, from_currency, to_currency)
        rate = self._index.get(key)
        if rate is None:
            available = self._pairs.get((from_currency, to_currency), [])
            raise FXRateMissingError(
                f"FX rate missing: {from_currency} -> {to_currency} on {settlement_dt}. "
                f"Available dates for this pair: {available}"
            )
        return (amount * rate).quantize(Decimal('0.01'))

    def available_dates(self, from_currency: str, to_currency: str) -> list:
        return list(self._pairs.get((from_currency, to_currency), []))

    def to_home(
        self,
        amount: Decimal,
        event_currency: str,
        home_currency: str,
        settlement_dt: date,
    ) -> Decimal:
        """
        Convert event amount to home currency.
        Handles indirect pairs by going through USD if needed (EUR->ZAR, etc.).
        Direct pairs are checked first.
        """
        if event_currency == home_currency:
            return amount

        # Try direct
        try:
            return self.convert(amount, event_currency, home_currency, settlement_dt)
        except FXRateMissingError:
            pass

        # Try via USD intermediary
        # event_currency -> USD -> home_currency
        # or USD -> event_currency -> home_currency (inverse)
        # The dataset only provides one-way rates, so we try the paths present.

        # Path 1: event_currency -> USD, then USD -> home_currency
        try:
            to_usd = self.convert(amount, event_currency, 'USD', settlement_dt)
            return self.convert(to_usd, 'USD', home_currency, settlement_dt)
        except FXRateMissingError:
            pass

        # Path 2: home_currency -> USD then event_currency -> home via home->USD inverse
        # Not attempted - we raise informative error
        raise FXRateMissingError(
            f"Cannot convert {event_currency} -> {home_currency} on {settlement_dt} "
            f"(no direct or USD-bridged rate found)"
        )
