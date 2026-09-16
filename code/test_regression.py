import unittest
from datetime import date
from decimal import Decimal
import sys
sys.path.insert(0, 'code')

from data_loader import load_dataset
from currency import FXEngine
from main import process_request

class TestRegressionH1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = load_dataset()
        cls.fx = FXEngine(cls.dataset.fx_index)

    def test_original_pass_cases_preserved(self):
        # request_01, request_09, request_16 must remain PASS
        for req_id in ['request_01', 'request_09', 'request_16']:
            sr = self.dataset.sample_requests[req_id]
            dec, _, errs = process_request(sr.request, self.dataset, self.fx, use_daily_burn=True)
            self.assertEqual(len(errs), 0)
            self.assertEqual(dec.recommended_payment_method, sr.recommended_payment_method)
            self.assertEqual(dec.affordability_status, sr.affordability_status)
            self.assertAlmostEqual(dec.amount_safe_to_pay, sr.amount_safe_to_pay, places=2)

    def test_request_11_improved(self):
        # request_11 should be full_payment and affordable_with_plan under daily_burn
        sr = self.dataset.sample_requests['request_11']
        dec, _, _ = process_request(sr.request, self.dataset, self.fx, use_daily_burn=True)
        self.assertEqual(dec.recommended_payment_method, 'full_payment')
        self.assertEqual(dec.affordability_status, 'affordable_with_plan')
        self.assertEqual(dec.earliest_date_for_full_payment, date(2025, 7, 15))

    def test_reproducibility_legacy_stepped(self):
        # In legacy mode, request_11 is wait and method accuracy is 23/25
        sr = self.dataset.sample_requests['request_11']
        dec, _, _ = process_request(sr.request, self.dataset, self.fx, use_daily_burn=False)
        self.assertEqual(dec.recommended_payment_method, 'wait')
        self.assertEqual(dec.affordability_status, 'affordable_later')


class TestRegressionH2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = load_dataset()
        cls.fx = FXEngine(cls.dataset.fx_index)

    def test_h2_request_10_gig_income_suppressed(self):
        # request_10 safe amount should be 0 (headroom against 90-day expenses)
        # reducing absolute error from 254,000 to 12,700
        sr = self.dataset.sample_requests['request_10']
        dec, _, errs = process_request(sr.request, self.dataset, self.fx, use_daily_burn=True, filter_unreliable_income=True)
        self.assertEqual(len(errs), 0)
        self.assertEqual(dec.recommended_payment_method, 'not_recommended')
        self.assertEqual(dec.affordability_status, 'not_affordable')
        self.assertEqual(dec.amount_safe_to_pay, Decimal('0.00'))

    def test_h2_employer_salaries_preserved(self):
        # Regular salaried employees must retain their salary projections exactly
        for req_id in ['request_01', 'request_02', 'request_03', 'request_04', 'request_07', 'request_11', 'request_14', 'request_15', 'request_16']:
            sr = self.dataset.sample_requests[req_id]
            dec_h2, _, _ = process_request(sr.request, self.dataset, self.fx, use_daily_burn=True, filter_unreliable_income=True)
            dec_base, _, _ = process_request(sr.request, self.dataset, self.fx, use_daily_burn=True, filter_unreliable_income=False)
            self.assertEqual(dec_h2.recommended_payment_method, dec_base.recommended_payment_method)
            self.assertEqual(dec_h2.affordability_status, dec_base.affordability_status)
            self.assertEqual(dec_h2.amount_safe_to_pay, dec_base.amount_safe_to_pay)

    def test_h2_reproducibility_legacy_income(self):
        # When filter_unreliable_income=False, request_10 reproduces 266,700 safe amount
        sr = self.dataset.sample_requests['request_10']
        dec, _, _ = process_request(sr.request, self.dataset, self.fx, use_daily_burn=True, filter_unreliable_income=False)
        self.assertEqual(dec.amount_safe_to_pay, Decimal('266700.00'))


class TestRegressionH4(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = load_dataset()
        cls.fx = FXEngine(cls.dataset.fx_index)

    def test_h4_spending_changes_fixed(self):
        # request_11 must use original minimum_allowed_amount (665950)
        sr11 = self.dataset.sample_requests['request_11']
        dec11, _, _ = process_request(sr11.request, self.dataset, self.fx, use_daily_burn=True, filter_unreliable_income=True)
        self.assertEqual(dec11.spending_changes_needed, 'reduce_to:event_989:665950')
        self.assertEqual(dec11.recommended_payment_method, 'full_payment')

        # request_08 and request_13 (wait recommendations) must have spending_changes_needed == 'none'
        sr08 = self.dataset.sample_requests['request_08']
        dec08, _, _ = process_request(sr08.request, self.dataset, self.fx, use_daily_burn=True, filter_unreliable_income=True)
        self.assertEqual(dec08.spending_changes_needed, 'none')
        self.assertEqual(dec08.recommended_payment_method, 'wait')
        self.assertEqual(dec08.payment_plan, '2025-04-15:996.60')

        sr13 = self.dataset.sample_requests['request_13']
        dec13, _, _ = process_request(sr13.request, self.dataset, self.fx, use_daily_burn=True, filter_unreliable_income=True)
        self.assertEqual(dec13.spending_changes_needed, 'none')
        self.assertEqual(dec13.recommended_payment_method, 'wait')
        self.assertEqual(dec13.payment_plan, '2024-05-15:941.60')

    def test_h4_categorical_metrics_stability(self):
        # Confirm no regressions on key sample cases
        for req_id in ['request_01', 'request_09', 'request_16']:
            sr = self.dataset.sample_requests[req_id]
            dec, _, errs = process_request(sr.request, self.dataset, self.fx, use_daily_burn=True, filter_unreliable_income=True)
            self.assertEqual(len(errs), 0)
            self.assertEqual(dec.recommended_payment_method, sr.recommended_payment_method)
            self.assertEqual(dec.spending_changes_needed, sr.spending_changes_needed)


class TestRegressionH5(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = load_dataset()
        cls.fx = FXEngine(cls.dataset.fx_index)

    def test_h5_request_06_earliest_date_preserved(self):
        # request_06 full payment becomes safe on 2026-01-15 (salary day), independent of deadline
        sr06 = self.dataset.sample_requests['request_06']
        dec06, _, errs = process_request(sr06.request, self.dataset, self.fx, use_daily_burn=True, filter_unreliable_income=True)
        self.assertEqual(len(errs), 0)
        self.assertEqual(dec06.earliest_date_for_full_payment, date(2026, 1, 15))

    def test_h5_not_recommended_none_dates_preserved(self):
        # Requests where full payment is never safe within 90 days must retain None
        for req_id in ['request_05', 'request_10', 'request_14', 'request_15', 'request_20', 'request_24', 'request_25']:
            sr = self.dataset.sample_requests[req_id]
            dec, _, _ = process_request(sr.request, self.dataset, self.fx, use_daily_burn=True, filter_unreliable_income=True)
            self.assertIsNone(dec.earliest_date_for_full_payment)


if __name__ == '__main__':
    unittest.main()


