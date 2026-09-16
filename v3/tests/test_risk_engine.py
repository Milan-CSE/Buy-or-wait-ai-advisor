"""
v3/tests/test_risk_engine.py

Unit tests for Phase 3 risk engine.
"""
import sys, os, unittest
from decimal import Decimal
sys.path.insert(0, os.path.abspath('.'))
sys.path.insert(0, os.path.abspath('code'))

from data_loader import load_dataset
from currency import FXEngine
from financial_state import build_financial_state
from safe_amount import compute_safe_amount
from v3.risk_engine.stress_buffers import build_stressed_state, DEFAULT_P90_STRESS_FACTORS
from v3.risk_engine.risk_classifier import classify_risk


class TestRiskEngine(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.dataset = load_dataset()
        cls.fx = FXEngine(cls.dataset.fx_index)

    def test_state_isolation(self):
        """build_stressed_state must not mutate original state."""
        state = build_financial_state('user_01', 'request_01', self.dataset.requests['request_26'].request_date, self.dataset, self.fx)
        orig_amounts = [item.amount for item in state.recurring_debits]

        stressed = build_stressed_state(state)
        curr_amounts = [item.amount for item in state.recurring_debits]

        self.assertEqual(orig_amounts, curr_amounts, "Original state recurring debits were mutated!")
        self.assertNotEqual(id(state.recurring_debits), id(stressed.recurring_debits))

    def test_safe_amount_monotonicity(self):
        """safe_amount under P90 stress must be <= safe_amount under P50 across all 25 sample requests."""
        for rid, sr in self.dataset.sample_requests.items():
            req = sr.request
            s50 = build_financial_state(req.user_id, req.request_id, req.request_date, self.dataset, self.fx)
            s90 = build_stressed_state(s50)

            safe50 = compute_safe_amount(s50, req.requested_amount)
            safe90 = compute_safe_amount(s90, req.requested_amount)
            self.assertLessEqual(
                safe90, safe50 + Decimal('0.01'),
                f"P90 safe amount {safe90} > P50 {safe50} for {rid}"
            )

    def test_fixed_category_invariance(self):
        """Fixed categories in stressed state must have identical amounts to original state."""
        state = build_financial_state('user_01', 'request_01', self.dataset.requests['request_26'].request_date, self.dataset, self.fx)
        stressed = build_stressed_state(state)

        for item_orig, item_stress in zip(state.recurring_debits, stressed.recurring_debits):
            if item_orig.category == 'rent':
                self.assertEqual(item_orig.amount, item_stress.amount)

    def test_stress_summary_and_risk_profile(self):
        """Verify RiskProfile fields: stress_summary, risk_reason, and valid risk tiers."""
        from v3.risk_engine.risk_policy import apply_risk_policy
        valid_tiers = {'LOW_RISK', 'MODERATE_RISK', 'HIGH_RISK'}

        for rid in ['request_01', 'request_02', 'request_07', 'request_16']:
            sr = self.dataset.sample_requests[rid]
            req = sr.request
            s50 = build_financial_state(req.user_id, req.request_id, req.request_date, self.dataset, self.fx)
            s90 = build_stressed_state(s50)
            rp = classify_risk(s50, s90, req.requested_amount, req.request_id)

            self.assertIn(rp.risk_tier, valid_tiers)
            self.assertTrue(len(rp.risk_reason) > 10)
            self.assertIsNotNone(rp.stress_summary)
            # Headroom calculation invariant
            self.assertEqual(rp.p50_headroom, rp.p50_min_closing - rp.minimum_balance_to_keep)
            self.assertEqual(rp.p90_headroom, rp.p90_min_closing - rp.minimum_balance_to_keep)

    def test_shadow_audit_policy_invariance(self):
        """shadow_audit_only policy must strictly preserve V2 decision without alteration."""
        from v3.risk_engine.shadow_mode import run_shadow_request
        from v3.risk_engine.risk_policy import apply_risk_policy

        for rid in ['request_01', 'request_06', 'request_11']:
            req = self.dataset.sample_requests[rid].request
            res = run_shadow_request(req, self.dataset, self.fx)
            applied = apply_risk_policy(res.v2_decision, res.v3_p90_decision, res.risk_profile, policy='shadow_audit_only')

            self.assertEqual(applied.amount_safe_to_pay, res.v2_decision.amount_safe_to_pay)
            self.assertEqual(applied.affordability_status, res.v2_decision.affordability_status)
            self.assertEqual(applied.recommended_payment_method, res.v2_decision.recommended_payment_method)
            self.assertEqual(applied.payment_plan, res.v2_decision.payment_plan)
            self.assertEqual(applied.spending_changes_needed, res.v2_decision.spending_changes_needed)
            self.assertEqual(applied.decision_explanation, res.v2_decision.decision_explanation)


if __name__ == '__main__':
    unittest.main()
