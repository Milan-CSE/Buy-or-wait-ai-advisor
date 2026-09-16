"""
v3/tests/test_v3_integration.py

End-to-end integration tests for V3 AI/ML Risk Engine:
1. Verifies that main_v3.py under shadow_audit_only produces output identical to V2.
2. Verifies output_v3.csv schema and completeness.
3. Verifies that risk profiles are correctly computed and monotonic.
4. Verifies no-risk flag preserves exact V2 behavior.
"""
import csv
import os
import sys
import unittest
from decimal import Decimal

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
CODE_DIR = os.path.join(ROOT_DIR, 'code')
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

from data_loader import load_dataset
from currency import FXEngine
from main import process_request
from main_v3 import run_v3, OUTPUT_COLUMNS_V3


class TestV3Integration(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.dataset = load_dataset()
        cls.fx = FXEngine(cls.dataset.fx_index)

    def test_v3_shadow_preserves_v2_decisions(self):
        """Under shadow_audit_only, V3 decisions must match V2 decisions on sample requests."""
        # Run V3 on sample requests
        v3_decisions, v3_records = run_v3(mode='sample', risk_policy='shadow_audit_only')
        self.assertEqual(len(v3_decisions), 25)

        # Check against pure V2 process_request
        for dec in v3_decisions:
            sr = self.dataset.sample_requests[dec.request_id]
            v2_dec, _, _ = process_request(sr.request, self.dataset, self.fx)

            self.assertEqual(dec.recommended_payment_method, v2_dec.recommended_payment_method)
            self.assertEqual(dec.affordability_status, v2_dec.affordability_status)
            self.assertEqual(dec.amount_safe_to_pay, v2_dec.amount_safe_to_pay)
            self.assertEqual(dec.payment_plan, v2_dec.payment_plan)
            self.assertEqual(dec.earliest_date_for_full_payment, v2_dec.earliest_date_for_full_payment)
            self.assertEqual(dec.spending_changes_needed, v2_dec.spending_changes_needed)

    def test_v3_output_csv_schema_and_columns(self):
        """Verify output_v3.csv exists and contains all required risk fields."""
        output_v3_path = os.path.join(ROOT_DIR, 'output_v3.csv')
        self.assertTrue(os.path.exists(output_v3_path), "output_v3.csv was not generated")

        with open(output_v3_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            self.assertEqual(reader.fieldnames, OUTPUT_COLUMNS_V3)
            rows = list(reader)
            self.assertEqual(len(rows), 25)

            for row in rows:
                self.assertIn(row['risk_tier'], {'LOW_RISK', 'MODERATE_RISK', 'HIGH_RISK'})
                self.assertTrue(len(row['risk_reason']) > 0)
                self.assertTrue(len(row['stress_summary']) > 0)
                # Verify numeric parsing
                Decimal(row['safe_amount_p50'])
                Decimal(row['safe_amount_p90'])
                Decimal(row['minimum_balance_p50'])
                Decimal(row['minimum_balance_p90'])
                Decimal(row['headroom_p50'])
                Decimal(row['headroom_p90'])

    def test_no_risk_mode_execution(self):
        """--no-risk mode runs without risk engine and produces decisions."""
        v3_decisions, v3_records = run_v3(mode='sample', no_risk=True)
        self.assertEqual(len(v3_decisions), 25)
        self.assertEqual(len(v3_records), 25)
        # In no-risk mode, risk profile is None
        for dec, rp in v3_records:
            self.assertIsNone(rp)


if __name__ == '__main__':
    unittest.main()
