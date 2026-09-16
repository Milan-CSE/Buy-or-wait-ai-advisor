"""
backend/tests/test_currency_support.py

Comprehensive tests verifying multi-currency support:
1. FXEngine direct, reciprocal, and bridged rate resolution
2. Historical rate vs future rate estimation tagging
3. Strict failure on unsupported currencies (zero guessing)
4. DataQualityEvaluator currency validation
5. DecisionService cross-currency evaluation and result scaling
6. Purchases API HTTP endpoint integration with FX metadata
"""
import unittest
import uuid
from datetime import date, timedelta
from decimal import Decimal
from fastapi.testclient import TestClient

from backend.api.dependencies import get_fx_engine
from backend.api.main import app
from backend.auth.jwt import create_access_token
from backend.database.models.account import FinancialAccount
from backend.database.models.profile import FinancialProfile
from backend.database.models.transaction import Transaction
from backend.database.repositories.user_repository import UserRepository
from backend.database.session import Base, SessionFactory, get_engine
from backend.services.data_quality import DataQualityEvaluator
from backend.services.decision_service import DecisionService
from buyorwait_engine.currency.fx import FXEngine, FXRateMissingError
from buyorwait_engine.domain.models import PurchaseProposal


class TestFXEngineMultiCurrency(unittest.TestCase):
    """Verifies core FXEngine resolution, reciprocal rates, bridging, and estimation flags."""

    def test_identity_conversion(self):
        fx = FXEngine()
        meta = fx.resolve_rate("USD", "USD", date(2026, 3, 1))
        self.assertEqual(meta.rate, Decimal("1.0000"))
        self.assertEqual(meta.from_currency, "USD")
        self.assertEqual(meta.to_currency, "USD")
        self.assertFalse(meta.is_estimated)
        self.assertEqual(meta.source, "identity")

    def test_direct_historical_rate(self):
        fx = FXEngine()
        fx.add_rate(date(2024, 1, 15), "USD", "INR", Decimal("83.33"))
        meta = fx.resolve_rate("USD", "INR", date(2024, 1, 15))
        self.assertEqual(meta.rate, Decimal("83.33"))
        self.assertFalse(meta.is_estimated)
        self.assertIn("exact date", meta.source)

    def test_prevailing_historical_rate_for_gap_dates(self):
        fx = FXEngine()
        fx.add_rate(date(2024, 1, 15), "USD", "INR", Decimal("83.33"))
        meta = fx.resolve_rate("USD", "INR", date(2024, 2, 1))
        self.assertEqual(meta.rate, Decimal("83.33"))
        self.assertEqual(meta.effective_date, date(2024, 1, 15))
        self.assertFalse(meta.is_estimated)
        self.assertIn("prevailing", meta.source)

    def test_reciprocal_rate(self):
        fx = FXEngine()
        fx.add_rate(date(2024, 1, 15), "USD", "INR", Decimal("83.33"))
        meta = fx.resolve_rate("INR", "USD", date(2024, 1, 15))
        expected = (Decimal("1") / Decimal("83.33")).quantize(Decimal("0.00000001"))
        self.assertEqual(meta.rate, expected)
        self.assertEqual(meta.from_currency, "INR")
        self.assertEqual(meta.to_currency, "USD")
        self.assertIn("reciprocal", meta.source)

    def test_cross_currency_bridging_via_usd(self):
        fx = FXEngine()
        fx.add_rate(date(2024, 4, 15), "EUR", "USD", Decimal("1.09"))
        fx.add_rate(date(2024, 4, 15), "USD", "INR", Decimal("83.33"))
        meta = fx.resolve_rate("EUR", "INR", date(2024, 4, 15))
        expected = (Decimal("1.09") * Decimal("83.33")).quantize(Decimal("0.00000001"))
        self.assertEqual(meta.rate, expected)
        self.assertIn("USD bridge", meta.source)

    def test_future_date_estimation_tagging(self):
        fx = FXEngine()
        fx.add_rate(date(2024, 1, 15), "USD", "INR", Decimal("83.33"))
        future_dt = date.today() + timedelta(days=90)
        meta = fx.resolve_rate("USD", "INR", future_dt)
        self.assertTrue(meta.is_estimated)
        self.assertTrue("projected" in meta.source or "estimated" in meta.source)

    def test_unsupported_currency_raises_fx_rate_missing(self):
        fx = FXEngine()
        fx.add_rate(date(2024, 1, 15), "USD", "INR", Decimal("83.33"))
        with self.assertRaises(FXRateMissingError) as exc:
            fx.resolve_rate("JPY", "USD", date(2024, 1, 15))
        self.assertIn("JPY", str(exc.exception))

    def test_dataset_exchange_rates_loaded_in_dependency(self):
        fx = get_fx_engine()
        meta_inr = fx.resolve_rate("USD", "INR", date(2024, 6, 15))
        self.assertGreater(meta_inr.rate, Decimal("0"))
        meta_idr = fx.resolve_rate("USD", "IDR", date(2024, 6, 15))
        self.assertGreater(meta_idr.rate, Decimal("0"))
        meta_zar = fx.resolve_rate("EUR", "ZAR", date(2024, 6, 15))
        self.assertGreater(meta_zar.rate, Decimal("0"))


class TestMultiCurrencyIntegration(unittest.TestCase):
    """Integration tests for DataQuality, DecisionService, and API with DB session."""

    @classmethod
    def setUpClass(cls):
        import os
        db_url = os.getenv("TEST_DATABASE_URL", "sqlite:///:memory:")
        cls.engine = get_engine(db_url)
        Base.metadata.create_all(bind=cls.engine)
        cls.SessionLocal = SessionFactory
        cls.SessionLocal.configure(bind=cls.engine)

    def setUp(self):
        self.session = self.SessionLocal()
        email = f"currency_{uuid.uuid4().hex[:8]}@example.com"
        self.user = UserRepository(self.session).create(email, "Currency Tester")
        self.session.commit()
        self.client = TestClient(app)
        self.token = create_access_token(self.user.id, self.user.email)
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def tearDown(self):
        self.session.rollback()
        self.session.close()

    def _add_tx(self, amount, currency, tx_date, category="salary", direction="credit"):
        amt = Decimal(str(amount))
        tx = Transaction(
            user_id=self.user.id,
            dedup_hash=f"tx_{uuid.uuid4().hex[:12]}",
            transaction_date=tx_date,
            amount=amt,
            currency=currency,
            amount_home=amt,
            direction=direction,
            category=category,
            normalized_description=category,
            original_description=category,
            lifecycle_status="settled",
            cash_type="settled_income" if direction == "credit" else "immediate_debit",
            confidence_state="verified",
        )
        self.session.add(tx)
        return tx

    def test_supported_currency_passes_data_quality(self):
        fx = get_fx_engine()
        evaluator = DataQualityEvaluator(fx_engine=fx, min_historical_transactions=1)
        profile = FinancialProfile(
            user_id=self.user.id,
            home_currency="USD",
            current_available_balance=Decimal("5000.00"),
            minimum_balance_to_keep=Decimal("1000.00"),
        )
        acc = FinancialAccount(
            user_id=self.user.id,
            account_type="checking",
            currency="USD",
            current_balance=Decimal("5000.00"),
            status="active",
        )
        tx = self._add_tx("100.00", "USD", date(2026, 3, 1))
        self.session.commit()
        res = evaluator.evaluate(
            profile=profile,
            accounts=[acc],
            transactions=[tx],
            as_of_date=date(2026, 3, 1),
            purchase_currency="EUR",
        )
        self.assertTrue(res.is_sufficient)

    def test_unsupported_purchase_currency_fails_data_quality(self):
        fx = get_fx_engine()
        evaluator = DataQualityEvaluator(fx_engine=fx, min_historical_transactions=1)
        profile = FinancialProfile(
            user_id=self.user.id,
            home_currency="USD",
            current_available_balance=Decimal("5000.00"),
            minimum_balance_to_keep=Decimal("1000.00"),
        )
        acc = FinancialAccount(
            user_id=self.user.id,
            account_type="checking",
            currency="USD",
            current_balance=Decimal("5000.00"),
            status="active",
        )
        tx = self._add_tx("100.00", "USD", date(2026, 3, 1))
        self.session.commit()
        res = evaluator.evaluate(
            profile=profile,
            accounts=[acc],
            transactions=[tx],
            as_of_date=date(2026, 3, 1),
            purchase_currency="XYZ",
        )
        self.assertFalse(res.is_sufficient)
        self.assertEqual(res.code, "DATA_INSUFFICIENT")
        self.assertIn("XYZ", res.reason)

    def test_cross_currency_evaluation_in_eur_with_usd_profile(self):
        fx = get_fx_engine()
        service = DecisionService(session=self.session, fx_engine=fx)

        profile = FinancialProfile(
            user_id=self.user.id,
            home_currency="USD",
            current_available_balance=Decimal("10000.00"),
            minimum_balance_to_keep=Decimal("1000.00"),
        )
        self.session.add(profile)
        acc = FinancialAccount(
            user_id=self.user.id,
            account_type="checking",
            currency="USD",
            current_balance=Decimal("10000.00"),
            status="active",
        )
        self.session.add(acc)
        for i in range(1, 4):
            self._add_tx("50.00", "USD", date(2026, 2, 20) + timedelta(days=i))
        self.session.commit()

        proposal = PurchaseProposal(
            request_id="req_test_fx_1",
            user_id=str(self.user.id),
            requested_amount=Decimal("500.00"),
            currency="EUR",
            request_date=date(2026, 3, 1),
            desired_completion_date=date(2026, 3, 1),
        )

        res = service.evaluate_purchase(
            user_id=self.user.id,
            purchase_data=proposal,
            as_of_date=date(2026, 3, 1),
        )

        self.assertTrue(res.is_sufficient)
        self.assertIsNotNone(res.decision)
        self.assertIsNotNone(res.fx_metadata)
        self.assertEqual(res.fx_metadata["purchase_currency"], "EUR")
        self.assertEqual(res.fx_metadata["home_currency"], "USD")
        self.assertEqual(res.decision.amount_safe_to_pay, Decimal("500.00"))
        self.assertEqual(res.decision.affordability_status, "affordable_now")
        self.assertEqual(res.decision.recommended_payment_method, "full_payment")

    def test_cross_currency_evaluation_in_usd_with_inr_profile(self):
        fx = get_fx_engine()
        service = DecisionService(session=self.session, fx_engine=fx)

        profile = FinancialProfile(
            user_id=self.user.id,
            home_currency="INR",
            current_available_balance=Decimal("1000000.00"),
            minimum_balance_to_keep=Decimal("100000.00"),
        )
        self.session.add(profile)
        acc = FinancialAccount(
            user_id=self.user.id,
            account_type="checking",
            currency="INR",
            current_balance=Decimal("1000000.00"),
            status="active",
        )
        self.session.add(acc)
        for i in range(1, 4):
            self._add_tx("5000.00", "INR", date(2026, 2, 20) + timedelta(days=i))
        self.session.commit()

        # Purchase in USD: $1,000 USD (~83,330 INR, well within 1,000,000 INR)
        proposal = PurchaseProposal(
            request_id="req_test_fx_inr_1",
            user_id=str(self.user.id),
            requested_amount=Decimal("1000.00"),
            currency="USD",
            request_date=date(2026, 3, 1),
            desired_completion_date=date(2026, 3, 1),
        )

        res = service.evaluate_purchase(
            user_id=self.user.id,
            purchase_data=proposal,
            as_of_date=date(2026, 3, 1),
        )

        self.assertTrue(res.is_sufficient)
        self.assertIsNotNone(res.decision)
        self.assertIsNotNone(res.fx_metadata)
        self.assertEqual(res.fx_metadata["purchase_currency"], "USD")
        self.assertEqual(res.fx_metadata["home_currency"], "INR")
        self.assertEqual(res.decision.amount_safe_to_pay, Decimal("1000.00"))
        self.assertEqual(res.decision.affordability_status, "affordable_now")
        self.assertEqual(res.decision.recommended_payment_method, "full_payment")

    def test_api_evaluate_purchase_with_eur(self):
        profile = FinancialProfile(
            user_id=self.user.id,
            home_currency="USD",
            current_available_balance=Decimal("8000.00"),
            minimum_balance_to_keep=Decimal("1000.00"),
        )
        self.session.add(profile)
        acc = FinancialAccount(
            user_id=self.user.id,
            account_type="checking",
            currency="USD",
            current_balance=Decimal("8000.00"),
            status="active",
        )
        self.session.add(acc)
        for i in range(1, 4):
            self._add_tx("50.00", "USD", date(2026, 2, 20) + timedelta(days=i))
        self.session.commit()

        payload = {
            "requested_amount": 250.00,
            "currency": "EUR",
            "request_date": "2026-03-01",
            "desired_completion_date": "2026-03-01",
            "item_description": "Conference ticket",
            "allows_partial_payment": True,
        }

        resp = self.client.post(
            "/api/v1/purchases/evaluate",
            headers=self.headers,
            json=payload,
        )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["verdict"], "BUY")
        self.assertEqual(Decimal(str(data["amount_safe_to_pay"])), Decimal("250.00"))
        self.assertIsNotNone(data.get("fx_metadata"))
        self.assertEqual(data["fx_metadata"]["purchase_currency"], "EUR")
        self.assertEqual(data["fx_metadata"]["home_currency"], "USD")
        self.assertGreater(Decimal(str(data["fx_metadata"]["exchange_rate"])), Decimal("0"))
