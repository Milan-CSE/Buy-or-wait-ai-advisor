"""
buyorwait_engine/currency/fx.py

Dated foreign exchange rate engine supporting direct and USD-bridged conversions.
Uses Decimal arithmetic throughout and enforces exact dated rate availability.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple


class FXRateMissingError(Exception):
    """Raised when an exchange rate is absent or unsupported."""
    pass


@dataclass(frozen=True)
class FXRateMetadata:
    """Audit metadata describing an applied exchange rate conversion."""
    from_currency: str
    to_currency: str
    rate: Decimal
    effective_date: date
    is_estimated: bool
    source: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "from_currency": self.from_currency,
            "to_currency": self.to_currency,
            "rate": str(self.rate),
            "effective_date": self.effective_date.isoformat(),
            "is_estimated": self.is_estimated,
            "source": self.source,
        }


class FXEngine:
    """
    Looks up rates by (rate_date, from_currency, to_currency) supporting
    direct, reciprocal, and bridged (USD / EUR) conversions with strict audit metadata.
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
        frm = from_currency.strip().upper()
        to = to_currency.strip().upper()
        self._index[(rate_date, frm, to)] = rate
        pair = (frm, to)
        if pair not in self._pairs:
            self._pairs[pair] = []
        if rate_date not in self._pairs[pair]:
            self._pairs[pair].append(rate_date)
            self._pairs[pair].sort()

    def _resolve_single_pair(self, from_curr: str, to_curr: str, eval_date: date) -> Optional[FXRateMetadata]:
        """Resolves a direct pair on or before eval_date, or None if unavailable."""
        exact_key = (eval_date, from_curr, to_curr)
        is_future = eval_date > date.today()

        if exact_key in self._index:
            rate = self._index[exact_key]
            src = "dataset/exchange_rates.csv (exact date)" if not is_future else "dataset/exchange_rates.csv (estimated future rate)"
            return FXRateMetadata(
                from_currency=from_curr,
                to_currency=to_curr,
                rate=rate,
                effective_date=eval_date,
                is_estimated=is_future,
                source=src,
            )

        pair = (from_curr, to_curr)
        available_dates = self._pairs.get(pair, [])
        past_dates = [d for d in available_dates if d <= eval_date]
        if past_dates:
            eff_date = max(past_dates)
            rate = self._index[(eff_date, from_curr, to_curr)]
            src = (
                f"dataset/exchange_rates.csv (prevailing {eff_date})"
                if not is_future
                else f"dataset/exchange_rates.csv (projected from {eff_date})"
            )
            return FXRateMetadata(
                from_currency=from_curr,
                to_currency=to_curr,
                rate=rate,
                effective_date=eff_date,
                is_estimated=is_future,
                source=src,
            )

        return None

    def _resolve_direct_or_reciprocal(self, frm: str, to: str, eval_date: date) -> Optional[FXRateMetadata]:
        """Resolves direct or reciprocal rate without recursive bridging."""
        direct = self._resolve_single_pair(frm, to, eval_date)
        if direct is not None:
            return direct

        inv = self._resolve_single_pair(to, frm, eval_date)
        if inv is not None and inv.rate != Decimal("0"):
            reciprocal_rate = (Decimal("1") / inv.rate).quantize(Decimal("0.00000001"))
            return FXRateMetadata(
                from_currency=frm,
                to_currency=to,
                rate=reciprocal_rate,
                effective_date=inv.effective_date,
                is_estimated=inv.is_estimated,
                source=f"reciprocal of {to}->{frm} ({inv.source})",
            )
        return None

    def resolve_rate(
        self,
        from_currency: str,
        to_currency: str,
        eval_date: date,
    ) -> FXRateMetadata:
        """
        Resolves the exchange rate and audit metadata between two currencies on eval_date:
        1. Identity (same currency): rate 1.0000, not estimated.
        2. Direct or reciprocal rate on or before eval_date.
        3. Cross-currency bridge via USD or EUR using direct/reciprocal legs.
        4. Fails strictly with FXRateMissingError if unsupported without guessing.
        """
        frm = from_currency.strip().upper()
        to = to_currency.strip().upper()

        # 1. Identity
        if frm == to:
            return FXRateMetadata(
                from_currency=frm,
                to_currency=to,
                rate=Decimal("1.0000"),
                effective_date=eval_date,
                is_estimated=False,
                source="identity",
            )

        # 2. Direct or Reciprocal lookup
        direct_or_inv = self._resolve_direct_or_reciprocal(frm, to, eval_date)
        if direct_or_inv is not None:
            return direct_or_inv

        # 3. Bridge via USD (requires both legs to resolve directly/reciprocally)
        if frm != "USD" and to != "USD":
            leg1 = self._resolve_direct_or_reciprocal(frm, "USD", eval_date)
            leg2 = self._resolve_direct_or_reciprocal("USD", to, eval_date)
            if leg1 is not None and leg2 is not None:
                bridge_rate = (leg1.rate * leg2.rate).quantize(Decimal("0.00000001"))
                eff_dt = min(leg1.effective_date, leg2.effective_date)
                is_est = leg1.is_estimated or leg2.is_estimated
                return FXRateMetadata(
                    from_currency=frm,
                    to_currency=to,
                    rate=bridge_rate,
                    effective_date=eff_dt,
                    is_estimated=is_est,
                    source=f"USD bridge: ({frm}->USD @ {leg1.rate}) * (USD->{to} @ {leg2.rate})",
                )

        # 4. Bridge via EUR
        if frm != "EUR" and to != "EUR":
            leg1 = self._resolve_direct_or_reciprocal(frm, "EUR", eval_date)
            leg2 = self._resolve_direct_or_reciprocal("EUR", to, eval_date)
            if leg1 is not None and leg2 is not None:
                bridge_rate = (leg1.rate * leg2.rate).quantize(Decimal("0.00000001"))
                eff_dt = min(leg1.effective_date, leg2.effective_date)
                is_est = leg1.is_estimated or leg2.is_estimated
                return FXRateMetadata(
                    from_currency=frm,
                    to_currency=to,
                    rate=bridge_rate,
                    effective_date=eff_dt,
                    is_estimated=is_est,
                    source=f"EUR bridge: ({frm}->EUR @ {leg1.rate}) * (EUR->{to} @ {leg2.rate})",
                )

        raise FXRateMissingError(
            f"FX rate missing or unsupported: cannot convert {frm} -> {to} on {eval_date}. "
            f"No verified exchange rate path exists in provider dataset."
        )

    def convert(
        self,
        amount: Decimal,
        from_currency: str,
        to_currency: str,
        settlement_dt: date,
    ) -> Decimal:
        """
        Convert amount from from_currency to to_currency using resolved rate on settlement_dt.
        """
        if from_currency.strip().upper() == to_currency.strip().upper():
            return amount
        meta = self.resolve_rate(from_currency, to_currency, settlement_dt)
        return (amount * meta.rate).quantize(Decimal('0.01'))

    def to_home(
        self,
        amount: Decimal,
        event_currency: str,
        home_currency: str,
        settlement_dt: date,
    ) -> Decimal:
        """
        Convert event amount to home currency.
        """
        return self.convert(amount, event_currency, home_currency, settlement_dt)

