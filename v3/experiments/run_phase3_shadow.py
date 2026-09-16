"""
v3/experiments/run_phase3_shadow.py

V3 Phase 3 Experiment: Risk-Aware V2 Integration in Shadow Mode.
Evaluates all 25 public sample requests:
1. Computes official frozen V2 decision.
2. Evaluates dual-track solvency: P50 (expected) vs P90 (stressed).
3. Classifies requests into LOW_RISK, MODERATE_RISK, HIGH_RISK.
4. Simulates V3 P90 decision and evaluates differences.
5. Measures false-affordability reduction vs unnecessary conservatism.
6. Tests Controlled Integration Policies (shadow_audit_only, risk_adaptive, conservative_solvency).
"""
import sys, os, time
from decimal import Decimal
from typing import Dict, List

sys.path.insert(0, os.path.abspath('.'))
sys.path.insert(0, os.path.abspath('code'))

from data_loader import load_dataset
from currency import FXEngine
from v3.risk_engine.shadow_mode import run_shadow_request, ShadowResult
from v3.risk_engine.risk_policy import apply_risk_policy


def print_table(headers, rows, title=None):
    if title:
        print(f"\n{'='*len(title)}\n{title}\n{'='*len(title)}")
    col_widths = [max(len(str(r[i])) for r in [headers] + rows) + 2 for i in range(len(headers))]
    header_line = "".join(f"{str(h):<{col_widths[i]}}" for i, h in enumerate(headers))
    sep_line = "".join("-" * (w - 1) + " " for w in col_widths)
    print(header_line)
    print(sep_line)
    for r in rows:
        print("".join(f"{str(val):<{col_widths[i]}}" for i, val in enumerate(r)))


def main():
    print("=" * 95)
    print("V3 PHASE 3: RISK-AWARE V2 SHADOW MODE & INTEGRATION BENCHMARK (25 SAMPLES)")
    print("=" * 95)

    dataset = load_dataset()
    fx = FXEngine(dataset.fx_index)

    sample_reqs = [sr.request for sr in dataset.sample_requests.values()]
    print(f"Running shadow mode on {len(sample_reqs)} public sample requests...")

    shadow_results: List[ShadowResult] = []
    t0 = time.time()
    for req in sample_reqs:
        res = run_shadow_request(req, dataset, fx)
        shadow_results.append(res)
    print(f"Shadow execution completed in {time.time()-t0:.1f}s")

    # 1. Shadow Mode Per-Request Results Table
    headers = [
        'Request', 'User', 'Ccy', 'Requested',
        'V2 Method', 'V2 Status', 'Safe P50', 'Safe P90',
        'Headroom P90', 'Risk Tier', 'V3 P90 Method', 'Differs?'
    ]
    rows = []
    for sr in shadow_results:
        rp = sr.risk_profile
        v2 = sr.v2_decision
        p90 = sr.v3_p90_decision
        diff_str = "YES" if sr.differs else "no"
        rows.append([
            sr.request_id,
            rp.user_id,
            rp.currency,
            f"{rp.requested_amount:.0f}",
            v2.recommended_payment_method,
            v2.affordability_status,
            f"{rp.p50_safe_amount:.1f}",
            f"{rp.p90_safe_amount:.1f}",
            f"{rp.p90_headroom:+.1f}",
            rp.risk_tier,
            p90.recommended_payment_method,
            diff_str,
        ])
    print_table(headers, rows, "SHADOW MODE EVALUATION ACROSS ALL 25 PUBLIC SAMPLES")

    # 2. Risk Tier Distribution
    tier_counts = {}
    for sr in shadow_results:
        t = sr.risk_profile.risk_tier
        tier_counts[t] = tier_counts.get(t, 0) + 1

    print("\n[2/5] Solvency Risk Tier Distribution (25 Samples):")
    for t in ['LOW_RISK', 'MODERATE_RISK', 'HIGH_RISK']:
        cnt = tier_counts.get(t, 0)
        print(f"  {t:<15}: {cnt:>2} / 25 ({cnt/25*100:.1f}%)")

    # 3. Deep Dive into Differences: V2 vs V3 P90
    print("\n[3/5] Requests where V2 and V3 P90 Decisions Differ:")
    diff_requests = [sr for sr in shadow_results if sr.differs]
    diff_headers = ['Request', 'User', 'Ccy', 'Requested', 'V2 Decision', 'V3 P90 Decision', 'Safe P50 vs P90', 'Risk Cause']
    diff_rows = []
    for sr in diff_requests:
        rp = sr.risk_profile
        v2 = sr.v2_decision
        p90 = sr.v3_p90_decision
        diff_rows.append([
            sr.request_id,
            rp.user_id,
            rp.currency,
            f"{rp.requested_amount:.0f}",
            f"{v2.recommended_payment_method} | {v2.affordability_status}",
            f"{p90.recommended_payment_method} | {p90.affordability_status}",
            f"{rp.p50_safe_amount:.0f} -> {rp.p90_safe_amount:.0f}",
            rp.risk_tier,
        ])
    print_table(diff_headers, diff_rows, "V2 VS V3 P90 DECISION DIFFERENCES")

    # 4. Controlled Integration Policies Simulation
    print("\n[4/5] Evaluating Controlled Integration Policies on Ground Truth Benchmark:")
    ground_truth = dataset.sample_requests
    policies = ['shadow_audit_only', 'risk_adaptive', 'conservative_solvency']

    policy_headers = ['Policy', 'Method Acc', 'Afford Acc', 'Plan Acc', 'P90 Stress Solvent', 'Unsafe Recomms', 'Unnecessary Cons']
    policy_rows = []

    for pol in policies:
        method_correct = 0
        afford_correct = 0
        plan_correct = 0
        p90_solvent = 0
        unsafe_recomms = 0
        unnecessary_cons = 0

        for sr in shadow_results:
            gt = ground_truth[sr.request_id]
            rp = sr.risk_profile
            integrated_dec = apply_risk_policy(sr.v2_decision, sr.v3_p90_decision, rp, policy=pol)

            # Check ground truth accuracy against challenge benchmark
            if integrated_dec.recommended_payment_method == gt.recommended_payment_method:
                method_correct += 1
            if integrated_dec.affordability_status == gt.affordability_status:
                afford_correct += 1
            if (integrated_dec.payment_plan or 'none') == (gt.payment_plan or 'none'):
                plan_correct += 1

            # Financial safety checks
            # An unsafe recommendation occurs if policy recommends immediate full payment but P90 breaches minimum balance
            if integrated_dec.recommended_payment_method == 'full_payment' and rp.post_payment_breach_p90:
                unsafe_recomms += 1

            # An unnecessary conservative recommendation occurs if policy downgrades a request that is actually LOW_RISK
            if pol != 'shadow_audit_only' and rp.risk_tier == 'LOW_RISK' and integrated_dec.recommended_payment_method != gt.recommended_payment_method:
                unnecessary_cons += 1

        policy_rows.append([
            pol,
            f"{method_correct}/25 ({method_correct/25*100:.1f}%)",
            f"{afford_correct}/25 ({afford_correct/25*100:.1f}%)",
            f"{plan_correct}/25 ({plan_correct/25*100:.1f}%)",
            f"{25 - unsafe_recomms}/25 ({ (25-unsafe_recomms)/25*100:.1f}%)",
            unsafe_recomms,
            unnecessary_cons,
        ])
    print_table(policy_headers, policy_rows, "INTEGRATION POLICY BENCHMARK COMPARISON")

    # 5. Risk Calibration & Explainability Sample
    print("\n[5/5] Sample Risk-Aware Explainability Diagnostic (request_02 & request_07):")
    for rid in ['request_01', 'request_02', 'request_11']:
        sr = next(s for s in shadow_results if s.request_id == rid)
        rp = sr.risk_profile
        v2 = sr.v2_decision
        dec_adaptive = apply_risk_policy(sr.v2_decision, sr.v3_p90_decision, rp, policy='risk_adaptive')
        print(f"\n--- {rid} ({rp.user_id}, {rp.currency}) ---")
        print(f"  Requested: {rp.requested_amount:.2f}")
        print(f"  P50 Safe:  {rp.p50_safe_amount:.2f} | P90 Safe: {rp.p90_safe_amount:.2f} | Min Bal: {rp.minimum_balance_to_keep:.2f}")
        print(f"  Risk Tier: {rp.risk_tier}")
        print(f"  V2 Decision:          {v2.recommended_payment_method} ({v2.affordability_status})")
        print(f"  V3 Adaptive Decision: {dec_adaptive.recommended_payment_method} ({dec_adaptive.affordability_status})")
        print(f"  Explanation: {dec_adaptive.decision_explanation}")


if __name__ == '__main__':
    main()
