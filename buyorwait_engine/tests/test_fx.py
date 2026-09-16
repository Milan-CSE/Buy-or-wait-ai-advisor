"""
Tests for FXEngine currency conversions and USD bridge precision.
"""
import unittest
from datetime import date
from decimal import Decimal

from buyorwait_engine.currency.fx import FXEngine, FXRateMissingError


class TestFXEngine(unittest.TestCase):
    def setUp(self):
        self.fx = FXEngine()
        # Direct EUR -> USD
        self.fx.add_rate(date(2026, 9, 15), "EUR", "USD", Decimal("1.1000"))
        # Direct USD -> INR
        self.fx.add_rate(date(2026, 9, 15), "USD", "INR", Decimal("83.5000"))

    def test_direct_conversion(self):
        converted = self.fx.convert(Decimal("100.00"), "EUR", "USD", date(2026, 9, 15))
        self.assertEqual(converted, Decimal("110.00"))

    def test_same_currency_identity(self):
        converted = self.fx.convert(Decimal("100.00"), "USD", "USD", date(2026, 9, 15))
        self.assertEqual(converted, Decimal("100.00"))

    def test_to_home_via_usd_bridge(self):
        # 100 EUR -> USD (110 USD) -> INR (110 * 83.5 = 9185.00 INR)
        inr_amt = self.fx.to_home(Decimal("100.00"), "EUR", "INR", date(2026, 9, 15))
        self.assertEqual(inr_amt, Decimal("9185.00"))

    def test_missing_rate_raises_fx_error(self):
        with self.assertRaises(FXRateMissingError):
            self.fx.convert(Decimal("100.00"), "GBP", "JPY", date(2026, 9, 15))


if __name__ == '__main__':
    unittest.main()
