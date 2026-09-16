"""
backend/tests/test_ingestion/test_e2e_engine_integration.py

Full end-to-end integration test proving that real-world normalized statement data
persisted in the database cleanly maps into buyorwait_engine to produce reliable financial decisions.
"""
import unittest
import uuid
from decimal import Decimal
from datetime import date
import os
from sqlalchemy.orm import Session

from backend.database.session import get_engine, Base, SessionFactory
from backend.database.repositories import UserRepository, ProfileRepository, TransactionRepository
from backend.database.mappers import ProfileMapper, TransactionMapper
from backend.ingestion.service import IngestionService
import buyorwait_engine as bow


class TestE2EEngineIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
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

        # Setup user financial profile
        self.prof_repo = ProfileRepository(self.session, self.user_id)
        self.profile = self.prof_repo.save_or_update(
            home_currency="USD",
            current_available_balance=Decimal("4500.0000"),
            minimum_balance_to_keep=Decimal("1000.0000"),
            max_installment_months=Decimal("6"),
            payment_methods=["full_payment", "installments"],
            protected_categories=["rent", "utilities"],
            reducible_categories=["dining", "shopping"],
            stoppable_categories=["entertainment"],
        )
        self.session.commit()
        self.service = IngestionService()

    def tearDown(self):
        self.session.rollback()
        self.session.close()

    def test_e2e_csv_ingestion_to_decision_pipeline(self):
        """
        1. Ingest raw messy CSV bank statement
        2. Stage & Preview through IngestionService
        3. Commit verified transactions to database
        4. Query database and map to buyorwait_engine DTOs
        5. Evaluate purchase proposal through buyorwait_engine
        6. Validate mathematical decision output and risk assessment
        """
        # 1. Raw synthetic statement
        statement_csv = b"""Date,Description,Withdrawal,Deposit,Balance
2026-08-01,Tech Company Monthly Salary,,4500.00,5000.00
2026-08-02,Sunset Apartments Monthly Rent,1200.00,,3800.00
2026-08-05,City Power & Electric Utility,150.00,,3650.00
2026-08-10,Whole Foods Market Groceries,95.50,,3554.50
2026-08-15,Starbucks Coffee,5.25,,3549.25
2026-09-01,Tech Company Monthly Salary,,4500.00,8049.25
2026-09-02,Sunset Apartments Monthly Rent,1200.00,,6849.25
2026-09-05,City Power & Electric Utility,150.00,,6699.25
"""

        # 2. Stage & preview
        preview, txns = self.service.stage_and_preview_statement(
            self.session, self.user_id, "checking_aug_sep.csv", statement_csv
        )
        self.assertEqual(preview.total_rows, 8)
        self.assertEqual(preview.accepted_rows, 8)
        self.assertEqual(preview.rejected_rows, 0)

        # 3. Commit to database
        committed_count = self.service.commit_statement_batch(
            self.session, self.user_id, preview.batch_id, txns
        )
        self.assertEqual(committed_count, 8)

        # 4. Fetch from database and map to domain DTOs
        tx_repo = TransactionRepository(self.session, self.user_id)
        db_transactions = tx_repo.get_events_for_period(
            start_date=date(2026, 8, 1),
            end_date=date(2026, 9, 30),
        )
        self.assertEqual(len(db_transactions), 8)

        domain_profile = ProfileMapper.to_domain(self.profile)
        domain_events = [TransactionMapper.to_domain(tx) for tx in db_transactions]

        # 5. Formulate purchase proposal
        proposal = bow.PurchaseProposal(
            request_id="proposal_e2e_01",
            user_id=str(self.user_id),
            requested_amount=Decimal("350.0000"),
            currency="USD",
            request_date=date(2026, 9, 10),
            desired_completion_date=date(2026, 9, 15),
            category="electronics",
            payment_options=[
                bow.PaymentOptionInput(
                    payment_option_id="opt_full",
                    payment_type="full_payment",
                    number_of_payments=1,
                    first_payment_date=date(2026, 9, 10),
                    installment_amount=Decimal("350.0000"),
                    total_amount=Decimal("350.0000"),
                )
            ],
        )

        # 6. Evaluate purchase through engine facade
        engine = bow.BuyOrWaitEngine()
        decision: bow.DecisionResult = engine.evaluate(
            profile=domain_profile,
            events=domain_events,
            purchase=proposal,
        )

        # 7. Validate results
        self.assertEqual(decision.verdict, "BUY")
        self.assertEqual(decision.recommended_payment_method, "full_payment")
        self.assertEqual(decision.amount_safe_to_pay, Decimal("350.0000"))
        self.assertEqual(decision.earliest_date_for_full_payment, date(2026, 9, 10))
        self.assertIsNotNone(decision.risk_assessment)
        self.assertTrue(len(decision.decision_explanation) > 10)
        self.assertIsNotNone(decision.audit_metrics)


if __name__ == "__main__":
    unittest.main()
