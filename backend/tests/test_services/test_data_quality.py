"""
backend/tests/test_services/test_data_quality.py

Unit tests for DataQualityEvaluator covering missing profiles, empty accounts,
insufficient history, balance staleness, and currency support.
"""
from datetime import date, timedelta
from decimal import Decimal
import unittest
import uuid

from backend.database.models.account import FinancialAccount
from backend.database.models.profile import FinancialProfile
from backend.database.models.transaction import Transaction
from backend.services.data_quality import DataQualityEvaluator, DataQualityResult
from buyorwait_engine.currency.fx import FXEngine


class TestDataQualityEvaluator(unittest.TestCase):
    def setUp(self):
        self.fx = FXEngine()
        self.fx.add_rate(date(2026, 3, 1), "EUR", "USD", Decimal("1.1000"))
        self.evaluator = DataQualityEvaluator(
            min_historical_transactions=3,
            max_staleness_days=90,
            fx_engine=self.fx,
        )
        self.user_id = uuid.uuid4()
        self.as_of_date = date(2026, 3, 1)

    def _create_profile(self, **kwargs) -> FinancialProfile:
        defaults = dict(
            user_id=self.user_id,
            home_currency="USD",
            current_available_balance=Decimal("5000.0000"),
            minimum_balance_to_keep=Decimal("1000.0000"),
        )
        defaults.update(kwargs)
        return FinancialProfile(**defaults)

    def _create_account(self, **kwargs) -> FinancialAccount:
        defaults = dict(
            user_id=self.user_id,
            account_type="checking",
            institution_name="Bank of America",
            account_mask="1234",
            currency="USD",
            current_balance=Decimal("5000.0000"),
            status="active",
        )
        defaults.update(kwargs)
        return FinancialAccount(**defaults)

    def _create_tx(self, tx_date: date, **kwargs) -> Transaction:
        defaults = dict(
            user_id=self.user_id,
            dedup_hash=uuid.uuid4().hex,
            transaction_date=tx_date,
            amount=Decimal("-50.0000"),
            currency="USD",
            amount_home=Decimal("-50.0000"),
            direction="debit",
            category="groceries",
            lifecycle_status="settled",
            confidence_state="verified",
        )
        defaults.update(kwargs)
        return Transaction(**defaults)

    def test_missing_profile(self):
        res = self.evaluator.evaluate(
            profile=None,
            accounts=[self._create_account()],
            transactions=[],
            as_of_date=self.as_of_date,
        )
        self.assertFalse(res.is_sufficient)
        self.assertEqual(res.code, "DATA_INSUFFICIENT")
        self.assertIn("profile does not exist", res.reason)
        self.assertEqual(res.affected_data, "profile")

    def test_negative_minimum_balance(self):
        prof = self._create_profile(minimum_balance_to_keep=Decimal("-500.0000"))
        res = self.evaluator.evaluate(
            profile=prof,
            accounts=[self._create_account()],
            transactions=[],
            as_of_date=self.as_of_date,
        )
        self.assertFalse(res.is_sufficient)
        self.assertEqual(res.code, "DATA_INSUFFICIENT")
        self.assertIn("negative", res.reason)

    def test_no_active_accounts_and_no_balance(self):
        prof = self._create_profile(current_available_balance=Decimal("0.0000"))
        res = self.evaluator.evaluate(
            profile=prof,
            accounts=[],
            transactions=[],
            as_of_date=self.as_of_date,
        )
        self.assertFalse(res.is_sufficient)
        self.assertEqual(res.code, "DATA_INSUFFICIENT")
        self.assertIn("No active liquid bank", res.reason)

    def test_missing_account_balance(self):
        prof = self._create_profile()
        acc = self._create_account(current_balance=None)
        res = self.evaluator.evaluate(
            profile=prof,
            accounts=[acc],
            transactions=[],
            as_of_date=self.as_of_date,
        )
        self.assertFalse(res.is_sufficient)
        self.assertEqual(res.code, "DATA_INSUFFICIENT")
        self.assertIn("missing balance", res.reason)

    def test_unsupported_account_currency(self):
        prof = self._create_profile(home_currency="USD")
        acc = self._create_account(currency="JPY")  # No JPY rate in fx
        txs = [self._create_tx(self.as_of_date - timedelta(days=i)) for i in range(1, 4)]
        res = self.evaluator.evaluate(
            profile=prof,
            accounts=[acc],
            transactions=txs,
            as_of_date=self.as_of_date,
        )
        self.assertFalse(res.is_sufficient)
        self.assertEqual(res.code, "DATA_INSUFFICIENT")
        self.assertIn("cannot be converted", res.reason)

    def test_unsupported_purchase_currency(self):
        prof = self._create_profile(home_currency="USD")
        acc = self._create_account(currency="USD")
        txs = [self._create_tx(self.as_of_date - timedelta(days=i)) for i in range(1, 4)]
        res = self.evaluator.evaluate(
            profile=prof,
            accounts=[acc],
            transactions=txs,
            as_of_date=self.as_of_date,
            purchase_currency="GBP",  # No GBP rate
        )
        self.assertFalse(res.is_sufficient)
        self.assertEqual(res.code, "DATA_INSUFFICIENT")
        self.assertIn("GBP", res.reason)

    def test_insufficient_transaction_history(self):
        prof = self._create_profile()
        acc = self._create_account()
        # Only 2 transactions (minimum is 3)
        txs = [self._create_tx(self.as_of_date - timedelta(days=i)) for i in range(1, 3)]
        res = self.evaluator.evaluate(
            profile=prof,
            accounts=[acc],
            transactions=txs,
            as_of_date=self.as_of_date,
        )
        self.assertFalse(res.is_sufficient)
        self.assertEqual(res.code, "DATA_INSUFFICIENT")
        self.assertIn("Insufficient verified transaction history", res.reason)
        self.assertIn("2 verified transactions found, minimum required: 3", res.reason)

    def test_unverified_transactions_not_counted(self):
        prof = self._create_profile()
        acc = self._create_account()
        # 1 verified, 2 needs_review -> only 1 verified
        txs = [
            self._create_tx(self.as_of_date - timedelta(days=1), confidence_state="verified"),
            self._create_tx(self.as_of_date - timedelta(days=2), confidence_state="needs_review"),
            self._create_tx(self.as_of_date - timedelta(days=3), confidence_state="needs_review"),
        ]
        res = self.evaluator.evaluate(
            profile=prof,
            accounts=[acc],
            transactions=txs,
            as_of_date=self.as_of_date,
        )
        self.assertFalse(res.is_sufficient)
        self.assertIn("1 verified transactions found", res.reason)

    def test_stale_balance_and_transactions(self):
        prof = self._create_profile()
        acc = self._create_account()
        # Transactions are 95 days old (max_staleness is 90)
        old_date = self.as_of_date - timedelta(days=95)
        txs = [
            self._create_tx(old_date - timedelta(days=i)) for i in range(3)
        ]
        res = self.evaluator.evaluate(
            profile=prof,
            accounts=[acc],
            transactions=txs,
            as_of_date=self.as_of_date,
        )
        self.assertFalse(res.is_sufficient)
        self.assertEqual(res.code, "DATA_INSUFFICIENT")
        self.assertIn("Financial data is stale", res.reason)

    def test_sufficient_healthy_data(self):
        prof = self._create_profile()
        acc = self._create_account()
        txs = [
            self._create_tx(self.as_of_date - timedelta(days=i * 5)) for i in range(1, 5)
        ]
        res = self.evaluator.evaluate(
            profile=prof,
            accounts=[acc],
            transactions=txs,
            as_of_date=self.as_of_date,
            purchase_currency="USD",
        )
        self.assertTrue(res.is_sufficient)
        self.assertEqual(res.code, "OK")


if __name__ == "__main__":
    unittest.main()
