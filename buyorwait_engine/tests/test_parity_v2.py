"""
Parity test comparing buyorwait_engine output against frozen V2 benchmark output.
Ensures zero behavioral discrepancy across all 25 sample requests.
"""
import unittest
import sys
import os
from decimal import Decimal

sys.path.insert(0, os.path.abspath("."))
sys.path.insert(0, os.path.abspath("code"))

from data_loader import load_dataset
from currency import FXEngine
from main import process_request
from financial_state import build_financial_state
from buyorwait_engine.adapters.legacy import adapt_request
from buyorwait_engine.engine import evaluate_purchase


class TestV2Parity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = load_dataset()
        cls.fx = FXEngine(cls.dataset.fx_index)

    def test_25_sample_requests_exact_parity(self):
        """Every sample request must produce identical decision fields between V2 and library."""
        mismatches = []
        sample_req_ids = sorted(self.dataset.sample_requests.keys())
        for req_id in sample_req_ids:
            sr = self.dataset.sample_requests[req_id]
            req = sr.request

            # 1. Compute via V2 directly
            v2_dec, diag, errs = process_request(req, self.dataset, self.fx)

            # 2. Compute via buyorwait_engine with V2 state & adapted proposal
            state = build_financial_state(req.user_id, req.request_id, req.request_date, self.dataset, self.fx)
            proposal = adapt_request(req, self.dataset)
            lib_dec = evaluate_purchase(state, proposal)

            # Check core fields
            if lib_dec.amount_safe_to_pay != v2_dec.amount_safe_to_pay:
                mismatches.append(f"{req.request_id}: amount_safe_to_pay {lib_dec.amount_safe_to_pay} != {v2_dec.amount_safe_to_pay}")
            if lib_dec.affordability_status != v2_dec.affordability_status:
                mismatches.append(f"{req.request_id}: affordability_status {lib_dec.affordability_status} != {v2_dec.affordability_status}")
            if lib_dec.recommended_payment_method != v2_dec.recommended_payment_method:
                mismatches.append(f"{req.request_id}: recommended_payment_method {lib_dec.recommended_payment_method} != {v2_dec.recommended_payment_method}")
            if lib_dec.payment_plan != v2_dec.payment_plan:
                mismatches.append(f"{req.request_id}: payment_plan {lib_dec.payment_plan} != {v2_dec.payment_plan}")
            if lib_dec.earliest_date_for_full_payment != v2_dec.earliest_date_for_full_payment:
                mismatches.append(f"{req.request_id}: earliest_date {lib_dec.earliest_date_for_full_payment} != {v2_dec.earliest_date_for_full_payment}")
            if lib_dec.spending_changes_needed != v2_dec.spending_changes_needed:
                mismatches.append(f"{req.request_id}: spending_changes {lib_dec.spending_changes_needed} != {v2_dec.spending_changes_needed}")

        self.assertEqual(len(mismatches), 0, f"Mismatches found: {mismatches}")


if __name__ == '__main__':
    unittest.main()
