"""
backend/tests/test_services/test_state_adapter.py

Unit tests for FinancialStateAdapter covering multi-account aggregation,
multi-currency conversion, transaction filtering, and internal transfer defense.
"""
from datetime import date
from decimal import Decimal
import unittest
import uuid

from backend.database.models.account import FinancialAccount
from backend.database.models.profile import FinancialProfile
from backend.database.models.transaction import Transaction
from backend.services.state_adapter import FinancialStateAdapter
from buyorwait_engine.currency.fx import FXEngine


class TestFinancialStateAdapter(unittest.TestCase):
    def setUp(self):
        self.fx = FXEngine()
        # Direct rate EUR -> USD: 1 EUR = 1.10 USD
        self.fx.add_rate(date(2026, 3, 1), "EUR", "USD", Decimal("1.1000"))
        self.adapter = FinancialStateAdapter(fx_engine=self.fx)
        self.user_id = uuid.uuid4()
        self.as_of_date = date(2026, 3, 1)

    def test_multi_account_balance_reconciliation(self):
        prof = FinancialProfile(
            user_id=self.user_id,
            home_currency="USD",
            current_available_balance=Decimal("0.0000"),
            minimum_balance_to_keep=Decimal("1000.0000"),
        )
        accounts = [
            FinancialAccount(
                user_id=self.user_id,
                account_type="checking",
                institution_name="Chase",
                account_mask="1111",
                currency="USD",
                current_balance=Decimal("1200.0000"),
                status="active",
            ),
            FinancialAccount(
                user_id=self.user_id,
                account_type="savings",
                institution_name="Ally",
                account_mask="2222",
                currency="USD",
                current_balance=Decimal("2500.0000"),
                status="active",
            ),
            FinancialAccount(
                user_id=self.user_id,
                account_type="cash",
                institution_name="Wallet",
                account_mask="0000",
                currency="USD",
                current_balance=Decimal("300.0000"),
                status="active",
            ),
            # Inactive checking account (must be ignored)
            FinancialAccount(
                user_id=self.user_id,
                account_type="checking",
                institution_name="OldBank",
                account_mask="9999",
                currency="USD",
                current_balance=Decimal("900.0000"),
                status="closed",
            ),
            # Credit card liability/credit line (must not be added to liquid balance)
            FinancialAccount(
                user_id=self.user_id,
                account_type="credit_card",
                institution_name="Amex",
                account_mask="4444",
                currency="USD",
                current_balance=Decimal("-450.0000"),
                status="active",
            ),
        ]
        reconciled = self.adapter.reconcile_available_balance(prof, accounts, self.as_of_date)
        # 1200 + 2500 + 300 = 4000
        self.assertEqual(reconciled, Decimal("4000.0000"))

    def test_multi_currency_reconciliation(self):
        prof = FinancialProfile(
            user_id=self.user_id,
            home_currency="USD",
            current_available_balance=Decimal("0.0000"),
            minimum_balance_to_keep=Decimal("500.0000"),
        )
        accounts = [
            FinancialAccount(
                user_id=self.user_id,
                account_type="checking",
                institution_name="Chase US",
                account_mask="1000",
                currency="USD",
                current_balance=Decimal("1000.0000"),
                status="active",
            ),
            FinancialAccount(
                user_id=self.user_id,
                account_type="savings",
                institution_name="BNP Paris",
                account_mask="2000",
                currency="EUR",
                current_balance=Decimal("2000.0000"),  # 2000 * 1.10 = 2200 USD
                status="active",
            ),
        ]
        reconciled = self.adapter.reconcile_available_balance(prof, accounts, self.as_of_date)
        # 1000 + 2200 = 3200
        self.assertEqual(reconciled, Decimal("3200.0000"))

    def test_internal_transfers_and_unverified_filtered(self):
        accounts = [
            FinancialAccount(
                user_id=self.user_id,
                account_type="checking",
                institution_name="Chase",
                account_mask="1111",
                currency="USD",
                current_balance=Decimal("1000.0000"),
                status="active",
            ),
            FinancialAccount(
                user_id=self.user_id,
                account_type="savings",
                institution_name="Ally",
                account_mask="2222",
                currency="USD",
                current_balance=Decimal("2000.0000"),
                status="active",
            ),
        ]
        transactions = [
            # 1. Normal verified expense -> KEEP
            Transaction(
                user_id=self.user_id,
                dedup_hash="tx_1",
                transaction_date=date(2026, 2, 20),
                amount=Decimal("-80.0000"),
                currency="USD",
                amount_home=Decimal("-80.0000"),
                direction="debit",
                category="groceries",
                normalized_description="Safeway Supermarket",
                lifecycle_status="settled",
                cash_type="immediate_debit",
                confidence_state="verified",
            ),
            # 2. Unverified expense -> EXCLUDE
            Transaction(
                user_id=self.user_id,
                dedup_hash="tx_2",
                transaction_date=date(2026, 2, 21),
                amount=Decimal("-45.0000"),
                currency="USD",
                amount_home=Decimal("-45.0000"),
                direction="debit",
                category="dining",
                normalized_description="Cafe",
                lifecycle_status="settled",
                cash_type="immediate_debit",
                confidence_state="needs_review",
            ),
            # 3. Internal transfer by category -> EXCLUDE
            Transaction(
                user_id=self.user_id,
                dedup_hash="tx_3",
                transaction_date=date(2026, 2, 22),
                amount=Decimal("-500.0000"),
                currency="USD",
                amount_home=Decimal("-500.0000"),
                direction="debit",
                category="transfer",
                normalized_description="Transfer out",
                lifecycle_status="settled",
                cash_type="immediate_debit",
                confidence_state="verified",
            ),
            # 4. Internal transfer by description pattern -> EXCLUDE
            Transaction(
                user_id=self.user_id,
                dedup_hash="tx_4",
                transaction_date=date(2026, 2, 23),
                amount=Decimal("-500.0000"),
                currency="USD",
                amount_home=Decimal("-500.0000"),
                direction="debit",
                category="other",
                normalized_description="Online transfer to savings",
                lifecycle_status="settled",
                cash_type="immediate_debit",
                confidence_state="verified",
            ),
            # 5. Non-cash accounting adjustment -> EXCLUDE
            Transaction(
                user_id=self.user_id,
                dedup_hash="tx_5",
                transaction_date=date(2026, 2, 24),
                amount=Decimal("100.0000"),
                currency="USD",
                amount_home=Decimal("100.0000"),
                direction="non_cash",
                category="adjustment",
                normalized_description="Paper statement adjustment",
                lifecycle_status="settled",
                cash_type="non_cash",
                confidence_state="verified",
            ),
            # 6. Verified confirmed salary -> KEEP
            Transaction(
                user_id=self.user_id,
                dedup_hash="tx_6",
                transaction_date=date(2026, 2, 25),
                amount=Decimal("3500.0000"),
                currency="USD",
                amount_home=Decimal("3500.0000"),
                direction="credit",
                category="salary",
                normalized_description="Acme Corp Payroll",
                lifecycle_status="settled",
                cash_type="settled_income",
                confidence_state="verified",
            ),
        ]
        filtered = self.adapter.filter_and_map_transactions(transactions, accounts)
        # Only tx_1 and tx_6 should remain
        self.assertEqual(len(filtered), 2)
        descriptions = [e.description for e in filtered]
        self.assertIn("Safeway Supermarket", descriptions)
        self.assertIn("Acme Corp Payroll", descriptions)


if __name__ == "__main__":
    unittest.main()
