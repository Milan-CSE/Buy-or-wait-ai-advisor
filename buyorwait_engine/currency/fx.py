"""
buyorwait_engine/currency/fx.py

Dated foreign exchange rate engine supporting direct and USD-bridged conversions.
Uses Decimal arithmetic throughout and enforces exact dated rate availability.
"""
from __future__ import annotations
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional, Tuple


class FXRateMissingError(Exception):
    """Raised when an exact dated exchange rate is absent."""
    pass


class FXEngine:
    """
    Looks up rates strictly by (rate_date, from_currency, to_currency).
    Home-currency-to-home-currency conversions return amount unchanged.
    """

    def __init__(self, fx_index: Optional[Dict[Tuple[date, str, str], Decimal]] = None):
        self._index: Dict[Tuple[date, str, str], Decimal] = fx_index or {}
        self._pairs: Dict[Tuple[str, str], List[date]] = {}
        for (d, frm, to), rate in self._index.items():
            self._pairs.setdefault((frm, to), []).append(d)
        for k in self._pairs:
            self._pairs[k].sort()

    def add_rate(self, rate_date: date, from_currency: str, to_currency: str, rate: Decimal) -> None:
        """Dynamically add an exchange rate in memory."""
        self._index[(rate_date, from_currency, to_currency)] = rate
        pair = (from_currency, to_currency)
        if pair not in self._pairs:
            self._pairs[pair] = []
        if rate_date not in self._pairs[pair]:
            self._pairs[pair].append(rate_date)
            self._pairs[pair].sort()

    def convert(
        self,
        amount: Decimal,
        from_currency: str,
        to_currency: str,
        settlement_dt: date,
    ) -> Decimal:
        """
        Convert amount from from_currency to to_currency using the rate
        on exactly settlement_dt.
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

    def to_home(
        self,
        amount: Decimal,
        event_currency: str,
        home_currency: str,
        settlement_dt: date,
    ) -> Decimal:
        """
        Convert event amount to home currency.
        Tries direct pair first, then bridges through USD if necessary.
        """
        if event_currency == home_currency:
            return amount

        # 1. Try direct conversion
        try:
            return self.convert(amount, event_currency, home_currency, settlement_dt)
        except FXRateMissingError:
            pass

        # 2. Try via USD bridge: event_currency -> USD -> home_currency
        try:
            to_usd = self.convert(amount, event_currency, 'USD', settlement_dt)
            return self.convert(to_usd, 'USD', home_currency, settlement_dt)
        except FXRateMissingError:
            pass

        raise FXRateMissingError(
            f"Cannot convert {event_currency} -> {home_currency} on {settlement_dt} "
            f"(no direct or USD-bridged rate found)"
        )
