"""
End-to-end integration loop test:
Database Records -> Repositories -> Mappers -> buyorwait_engine -> DecisionMapper -> DB Decision Entity.
Verifies complete architectural separation and domain engine independence.
"""
import unittest
import uuid
from decimal import Decimal
from datetime import date
from sqlalchemy.orm import Session

from backend.database.session import get_engine, Base, SessionFactory
from backend.database.repositories import (
    UserRepository,
    ProfileRepository,
    TransactionRepository,
    PurchaseRepository,
    DecisionRepository,
)
from backend.database.mappers import (
    ProfileMapper,
    TransactionMapper,
    PurchaseMapper,
    DecisionMapper,
)
from backend.database.models.transaction import Transaction

import buyorwait_engine as bow


class TestEnginePersistenceLoop(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        db_url = os.getenv("TEST_DATABASE_URL", "sqlite:///:memory:")
        cls.engine = get_engine(db_url)
        Base.metadata.create_all(bind=cls.engine)
        cls.SessionLocal = SessionFactory
        cls.SessionLocal.configure(bind=cls.engine)

    def setUp(self):
        self.session: Session = self.SessionLocal()
        self.user_repo = UserRepository(self.session)
        self.user = self.user_repo.create(f"e2e_{uuid.uuid4().hex[:6]}@example.com", "E2E User")
        self.session.commit()
        self.user_id = self.user.id

        # 1. Persist User Financial Profile in DB
        self.prof_repo = ProfileRepository(self.session, self.user_id)
        self.profile_entity = self.prof_repo.save_or_update(
            home_currency="USD",
            current_available_balance=Decimal("2000.0000"),
            minimum_balance_to_keep=Decimal("500.0000"),
            protected_categories=["rent", "debt_repayment"],
            reducible_categories=["groceries", "dining"],
            stoppable_categories=["streaming"],
            payment_methods=["full_payment", "installments", "partial_payment"],
            max_installment_months=Decimal("3.0"),
        )

        # 2. Persist Transactions in DB
        self.tx_repo = TransactionRepository(self.session, self.user_id)
        salary_tx1 = Transaction(
            user_id=self.user_id,
            dedup_hash="e2e_salary_01",
            transaction_date=date(2026, 8, 1),
            amount=Decimal("3500.0000"),
            currency="USD",
            amount_home=Decimal("3500.0000"),
            direction="credit",
            category="salary",
            normalized_description="Monthly Payroll",
            original_description="Monthly Payroll",
            lifecycle_status="settled",
            cash_type="confirmed_income",
        )
        salary_tx2 = Transaction(
            user_id=self.user_id,
            dedup_hash="e2e_salary_02",
            transaction_date=date(2026, 9, 1),
            amount=Decimal("3500.0000"),
            currency="USD",
            amount_home=Decimal("3500.0000"),
            direction="credit",
            category="salary",
            normalized_description="Monthly Payroll",
            original_description="Monthly Payroll",
            lifecycle_status="settled",
            cash_type="confirmed_income",
        )
        grocery_tx = Transaction(
            user_id=self.user_id,
            dedup_hash="e2e_grocery_01",
            transaction_date=date(2026, 9, 5),
            amount=Decimal("-150.0000"),
            currency="USD",
            amount_home=Decimal("-150.0000"),
            direction="debit",
            category="groceries",
            normalized_description="Supermarket",
            original_description="Supermarket",
            lifecycle_status="settled",
            cash_type="immediate_debit",
        )
        self.tx_repo.add(salary_tx1)
        self.tx_repo.add(salary_tx2)
        self.tx_repo.add(grocery_tx)

        # 3. Persist Purchase Request in DB
        self.purchase_repo = PurchaseRepository(self.session, self.user_id)
        self.purchase_entity = self.purchase_repo.create(
            requested_amount=Decimal("400.0000"),
            currency="USD",
            request_date=date(2026, 9, 15),
            desired_completion_date=date(2026, 9, 30),
            item_description="Noise Cancelling Headphones",
            merchant_name="Audio Store",
            category="electronics",
        )
        self.session.commit()

    def tearDown(self):
        self.session.rollback()
        self.session.close()

    def test_complete_engine_persistence_roundtrip(self):
        """
        Demonstrates the full production pipeline:
        DB Entities -> DTOs -> Domain Engine -> Decision DTO -> DB Entity.
        """
        # Step A: Load Entities via Repositories
        db_profile = self.prof_repo.get_profile()
        db_transactions = self.tx_repo.list_all_for_user()
        db_purchase = self.purchase_repo.get_by_id(self.purchase_entity.id)

        # Step B: Map to Domain DTOs
        profile_dto = ProfileMapper.to_domain_dto(db_profile)
        events_dto = [TransactionMapper.to_domain_dto(t) for t in db_transactions]
        purchase_dto = PurchaseMapper.to_domain_dto(db_purchase)

        # Step C: Evaluate in pure domain engine (Zero DB awareness in engine)
        engine = bow.BuyOrWaitEngine()
        result: bow.DecisionResult = engine.evaluate(profile_dto, events_dto, purchase_dto)

        self.assertEqual(result.verdict, bow.Verdict.BUY.value)
        self.assertEqual(result.recommended_payment_method, bow.PaymentMethod.FULL_PAYMENT.value)
        self.assertIsNotNone(result.risk_assessment)

        # Step D: Map DecisionResult DTO -> Decision ORM Entity
        decision_entity = DecisionMapper.to_entity(
            result=result,
            user_id=self.user_id,
            purchase_request_id=db_purchase.id,
        )

        # Step E: Persist to DB via DecisionRepository
        dec_repo = DecisionRepository(self.session, self.user_id)
        dec_repo.add(decision_entity)
        self.session.commit()

        # Step F: Retrieve and assert database persistence fidelity
        persisted = dec_repo.get_by_purchase_id(db_purchase.id)
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted.verdict, "BUY")
        self.assertEqual(persisted.amount_safe_to_pay, result.amount_safe_to_pay)
        self.assertEqual(persisted.affordability_status, result.affordability_status)
        self.assertEqual(persisted.risk_tier, result.risk_assessment.risk_tier)
        self.assertEqual(persisted.safe_amount_p50, result.risk_assessment.safe_amount_p50)
        self.assertEqual(persisted.calibration_version, bow.CURRENT_CALIBRATION_VERSION)


if __name__ == '__main__':
    unittest.main()
