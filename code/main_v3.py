"""
code/main_v3.py
V3 AI/ML Risk-Aware Orchestration Layer for Buy or Wait?

Extends the frozen V2 deterministic decision engine with an empirical P90 risk layer:
1. Computes the official V2 baseline decision (P50 expected solvency).
2. Computes the P90 stressed financial state and solvency metrics.
3. Classifies request solvency risk into LOW_RISK, MODERATE_RISK, or HIGH_RISK.
4. Generates additive risk-aware explanation fields.
5. Writes both standard output.csv (identical to V2 in default shadow mode) and output_v3.csv.

Usage:
  python code/main_v3.py [--mode {full|sample}] [--risk-policy {shadow_audit_only|risk_adaptive|conservative_solvency}] [--debug]
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
import traceback
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

# Ensure root and code/ directories are on sys.path
CODE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.abspath(os.path.join(CODE_DIR, '..'))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

from data_loader import load_dataset, Request, Dataset
from currency import FXEngine
from ranker import Decision
from validator import validate_decision, coerce_decision
from main import process_request, write_output, OUTPUT_COLUMNS

from v3.risk_engine.shadow_mode import run_shadow_request, ShadowResult
from v3.risk_engine.risk_classifier import RiskProfile
from v3.risk_engine.risk_policy import apply_risk_policy


OUTPUT_PATH_V2 = os.path.join(ROOT_DIR, 'output.csv')
OUTPUT_PATH_V3 = os.path.join(ROOT_DIR, 'output_v3.csv')

OUTPUT_COLUMNS_V3 = OUTPUT_COLUMNS + [
    'risk_tier',
    'safe_amount_p50',
    'safe_amount_p90',
    'minimum_balance_p50',
    'minimum_balance_p90',
    'headroom_p50',
    'headroom_p90',
    'risk_reason',
    'stress_summary',
]


def write_output_v3(
    records: List[Tuple[Decision, Optional[RiskProfile]]],
    output_path: str,
) -> None:
    """Write augmented decisions and risk diagnostics to output_v3.csv."""
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS_V3)
        writer.writeheader()
        for decision, rp in records:
            row = {
                'request_id': decision.request_id,
                'amount_safe_to_pay': f'{decision.amount_safe_to_pay:.2f}',
                'affordability_status': decision.affordability_status,
                'recommended_payment_method': decision.recommended_payment_method,
                'payment_plan': decision.payment_plan or 'none',
                'earliest_date_for_full_payment': (
                    decision.earliest_date_for_full_payment.isoformat()
                    if decision.earliest_date_for_full_payment else ''
                ),
                'spending_changes_needed': decision.spending_changes_needed or 'none',
                'decision_explanation': decision.decision_explanation,
            }
            if rp is not None:
                row.update({
                    'risk_tier': rp.risk_tier,
                    'safe_amount_p50': f'{rp.p50_safe_amount:.2f}',
                    'safe_amount_p90': f'{rp.p90_safe_amount:.2f}',
                    'minimum_balance_p50': f'{rp.p50_min_closing:.2f}',
                    'minimum_balance_p90': f'{rp.p90_min_closing:.2f}',
                    'headroom_p50': f'{rp.p50_headroom:.2f}',
                    'headroom_p90': f'{rp.p90_headroom:.2f}',
                    'risk_reason': rp.risk_reason,
                    'stress_summary': rp.stress_summary,
                })
            else:
                row.update({
                    'risk_tier': 'UNCLASSIFIED',
                    'safe_amount_p50': f'{decision.amount_safe_to_pay:.2f}',
                    'safe_amount_p90': '0.00',
                    'minimum_balance_p50': '0.00',
                    'minimum_balance_p90': '0.00',
                    'headroom_p50': '0.00',
                    'headroom_p90': '0.00',
                    'risk_reason': 'Risk engine bypassed',
                    'stress_summary': 'none',
                })
            writer.writerow(row)
    print(f'V3 Augmented output written to {output_path}')


def run_v3(
    mode: str = 'full',
    risk_policy: str = 'shadow_audit_only',
    no_risk: bool = False,
    debug: bool = False,
    burn_mode: str = 'daily_burn',
    income_mode: str = 'reliable_only',
) -> Tuple[List[Decision], List[Tuple[Decision, Optional[RiskProfile]]]]:
    """V3 main runner with risk-aware execution."""
    print(f'=== Buy or Wait? V3 Engine Starting ===')
    print(f'Mode: {mode} | Policy: {risk_policy} | Risk Engine: {"Disabled" if no_risk else "Active"}')
    print(f'Burn Mode: {burn_mode} | Income Mode: {income_mode}')

    t0 = time.time()
    dataset = load_dataset()
    fx = FXEngine(dataset.fx_index)

    if mode == 'sample':
        requests_to_process = [sr.request for sr in dataset.sample_requests.values()]
        print(f'Processing {len(requests_to_process)} sample requests...')
    else:
        requests_to_process = list(dataset.requests.values())
        print(f'Processing {len(requests_to_process)} evaluation requests...')

    final_decisions: List[Decision] = []
    v3_records: List[Tuple[Decision, Optional[RiskProfile]]] = []
    diff_count = 0
    tier_counts = {'LOW_RISK': 0, 'MODERATE_RISK': 0, 'HIGH_RISK': 0}

    for i, req in enumerate(requests_to_process, 1):
        t_req = time.time()

        if no_risk:
            # Pure V2 execution
            dec, _, errs = process_request(
                req, dataset, fx, debug=debug,
                use_daily_burn=(burn_mode == 'daily_burn'),
                filter_unreliable_income=(income_mode == 'reliable_only'),
            )
            final_decisions.append(dec)
            v3_records.append((dec, None))
        else:
            # V3 Dual-Track Shadow Execution
            v2_dec, _, _ = process_request(
                req, dataset, fx, debug=debug,
                use_daily_burn=(burn_mode == 'daily_burn'),
                filter_unreliable_income=(income_mode == 'reliable_only'),
            )
            res = run_shadow_request(req, dataset, fx)
            integrated_dec = apply_risk_policy(
                v2_decision=v2_dec,
                v3_p90_decision=res.v3_p90_decision,
                risk=res.risk_profile,
                policy=risk_policy,
            )
            final_decisions.append(integrated_dec)
            v3_records.append((integrated_dec, res.risk_profile))

            tier_counts[res.risk_profile.risk_tier] = tier_counts.get(res.risk_profile.risk_tier, 0) + 1
            if res.differs:
                diff_count += 1

            if debug or i <= 5 or i % 50 == 0 or i == len(requests_to_process):
                elapsed = time.time() - t_req
                print(f'  [{i}/{len(requests_to_process)}] {req.request_id}: '
                      f'{integrated_dec.recommended_payment_method} | {integrated_dec.affordability_status} '
                      f'| Risk: {res.risk_profile.risk_tier} ({elapsed:.2f}s)')

    total_time = time.time() - t0
    print(f'\nExecution complete: {len(final_decisions)} requests processed in {total_time:.1f}s '
          f'({total_time/len(final_decisions):.2f}s/req)')

    if not no_risk:
        print(f'Risk Tier Distribution:')
        for tier, count in tier_counts.items():
            pct = count / len(requests_to_process) * 100
            print(f'  {tier:<15}: {count:>3} ({pct:.1f}%)')
        print(f'Requests where V3 P90 stress diverged from V2: {diff_count} / {len(requests_to_process)}')

    # Write output.csv (strictly adheres to HackerRank challenge format)
    write_output(final_decisions, OUTPUT_PATH_V2)

    # Write output_v3.csv (additive portfolio output with risk fields)
    if not no_risk:
        write_output_v3(v3_records, OUTPUT_PATH_V3)

    return final_decisions, v3_records


def main():
    parser = argparse.ArgumentParser(description='Buy or Wait? V3 Risk-Aware Financial Intelligence Engine')
    parser.add_argument('--mode', choices=['full', 'sample'], default='full',
                        help='full: dataset/requests.csv -> output.csv; sample: dataset/sample_requests.csv')
    parser.add_argument('--risk-policy',
                        choices=['shadow_audit_only', 'risk_adaptive', 'conservative_solvency'],
                        default='shadow_audit_only',
                        help='shadow_audit_only (default): V2 decisions preserved, risk logged; '
                             'risk_adaptive: balances risk and affordability; '
                             'conservative_solvency: strict P90 solvency')
    parser.add_argument('--no-risk', action='store_true',
                        help='Bypass V3 risk engine entirely and run frozen V2')
    parser.add_argument('--burn-mode', choices=['daily_burn', 'v1_stepped'], default='daily_burn',
                        help='daily_burn (default) or v1_stepped')
    parser.add_argument('--income-mode', choices=['reliable_only', 'v1_all'], default='reliable_only',
                        help='reliable_only (default) or v1_all')
    parser.add_argument('--debug', action='store_true',
                        help='Enable detailed per-request logging')

    args = parser.parse_args()
    run_v3(
        mode=args.mode,
        risk_policy=args.risk_policy,
        no_risk=args.no_risk,
        debug=args.debug,
        burn_mode=args.burn_mode,
        income_mode=args.income_mode,
    )


if __name__ == '__main__':
    main()
