"""
main.py
Thin orchestration layer for the Buy or Wait? financial decision engine.

Usage:
  python code/main.py [--mode {full|sample}] [--debug]

  --mode full   : Process dataset/requests.csv -> output.csv (root level)
  --mode sample : Process dataset/sample_requests.csv (for benchmark validation)
  --debug       : Print per-request diagnostics to stdout

Output: output.csv (in the repository root directory)
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
from typing import Dict, List, Optional

# Ensure code/ directory is on path
sys.path.insert(0, os.path.dirname(__file__))

from data_loader import load_dataset, Request, Dataset
from currency import FXEngine
from financial_state import build_financial_state, FinancialState
from forecast import build_ledger
from safe_amount import compute_safe_amount
from earliest_full_payment import find_earliest_full_payment_date
from candidates import generate_candidates, Candidate
from spending_optimizer import enumerate_spending_change_combos
from ranker import make_decision, Decision
from validator import validate_decision, coerce_decision
from diagnostics import build_diagnostic, format_diagnostic, RequestDiagnostic


# Root directory (one level up from code/)
ROOT_DIR = os.path.join(os.path.dirname(__file__), '..')
OUTPUT_PATH = os.path.join(ROOT_DIR, 'output.csv')

OUTPUT_COLUMNS = [
    'request_id',
    'amount_safe_to_pay',
    'affordability_status',
    'recommended_payment_method',
    'payment_plan',
    'earliest_date_for_full_payment',
    'spending_changes_needed',
    'decision_explanation',
]


def process_request(
    req: Request,
    dataset: Dataset,
    fx: FXEngine,
    debug: bool = False,
) -> tuple:
    """
    Process a single request and return (Decision, RequestDiagnostic, errors).
    """
    warnings: List[str] = []
    errors: List[str] = []

    try:
        # 1. Build financial state
        state = build_financial_state(
            user_id=req.user_id,
            request_id=req.request_id,
            request_date=req.request_date,
            dataset=dataset,
            fx=fx,
        )

        # 2. Compute baseline safe amount and earliest full payment date
        safe_amount_base = compute_safe_amount(state, req.requested_amount)
        earliest_full_date = find_earliest_full_payment_date(state, req.requested_amount)

        # 3. Enumerate spending change combinations
        spending_combos = enumerate_spending_change_combos(state, max_actions=3)

        # 4. For each spending combo, generate candidates and collect all
        all_candidates: List[Candidate] = []

        for sc in spending_combos:
            # Compute safe amount with this combo
            safe_with_sc = compute_safe_amount(state, req.requested_amount, sc)
            # Earliest full with this combo
            earliest_with_sc = find_earliest_full_payment_date(state, req.requested_amount, sc)

            candidates = generate_candidates(
                state=state,
                req_amount=req.requested_amount,
                req_date=req.request_date,
                completion_date=req.desired_completion_date,
                allows_partial=req.allows_partial_payment,
                dataset=dataset,
                request_id=req.request_id,
                spending_changes=sc,
                earliest_full_date=earliest_with_sc,
                safe_amount=safe_with_sc,
            )
            all_candidates.extend(candidates)

        # 5. Select best candidate and produce decision
        decision = make_decision(
            request_id=req.request_id,
            state=state,
            all_candidates=all_candidates,
            requested_amount=req.requested_amount,
            request_date=req.request_date,
            completion_date=req.desired_completion_date,
            safe_amount_no_changes=safe_amount_base,
            earliest_full_date=earliest_full_date,
        )

        # 6. Validate
        decision = coerce_decision(decision, req.requested_amount)
        val_errors = validate_decision(decision, req.requested_amount)
        if val_errors:
            for ve in val_errors:
                errors.append(f'Validation: {ve.field}: {ve.message}')

        # 7. Build diagnostic
        diag = build_diagnostic(
            state=state,
            requested_amount=req.requested_amount,
            safe_amount=safe_amount_base,
            earliest_full_date=earliest_full_date,
            all_candidates=all_candidates,
            decision=decision,
            warnings=warnings,
            errors=errors,
        )

        if debug:
            print(format_diagnostic(diag))

        return decision, diag, errors

    except Exception as exc:
        error_msg = f'Exception processing {req.request_id}: {exc}'
        errors.append(error_msg)
        if debug:
            traceback.print_exc()

        # Fallback decision
        fallback = Decision(
            request_id=req.request_id,
            amount_safe_to_pay=Decimal('0'),
            affordability_status='not_affordable',
            recommended_payment_method='not_recommended',
            payment_plan='none',
            earliest_date_for_full_payment=None,
            spending_changes_needed='none',
            decision_explanation=f'Processing error: {exc}',
            best_candidate=None,
        )
        return fallback, None, errors


def write_output(decisions: List[Decision], output_path: str) -> None:
    """Write decisions to output.csv."""
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for d in decisions:
            row = {
                'request_id': d.request_id,
                'amount_safe_to_pay': f'{d.amount_safe_to_pay:.2f}',
                'affordability_status': d.affordability_status,
                'recommended_payment_method': d.recommended_payment_method,
                'payment_plan': d.payment_plan or 'none',
                'earliest_date_for_full_payment': d.earliest_date_for_full_payment.isoformat()
                    if d.earliest_date_for_full_payment else '',
                'spending_changes_needed': d.spending_changes_needed or 'none',
                'decision_explanation': d.decision_explanation,
            }
            writer.writerow(row)
    print(f'Output written to {output_path}')


def run(mode: str = 'full', debug: bool = False) -> List[Decision]:
    """Main runner."""
    print(f'Loading dataset... mode={mode}')
    t0 = time.time()

    dataset = load_dataset()
    fx = FXEngine(dataset.fx_index)

    print(f'Dataset loaded in {time.time() - t0:.1f}s')
    print(f'Profiles: {len(dataset.profiles)}, Events: {len(dataset.events)}, '
          f'Requests: {len(dataset.requests)}, Options: {sum(len(v) for v in dataset.payment_options.values())}')

    # Select requests to process
    if mode == 'sample':
        requests_to_process = [sr.request for sr in dataset.sample_requests.values()]
        print(f'Processing {len(requests_to_process)} sample requests')
    else:
        requests_to_process = list(dataset.requests.values())
        print(f'Processing {len(requests_to_process)} evaluation requests')

    decisions: List[Decision] = []
    diagnostics: List[RequestDiagnostic] = []
    error_count = 0

    for i, req in enumerate(requests_to_process, 1):
        t1 = time.time()
        decision, diag, errors = process_request(req, dataset, fx, debug=debug)
        elapsed = time.time() - t1

        if errors:
            error_count += len(errors)
            print(f'  [{i}/{len(requests_to_process)}] {req.request_id}: '
                  f'{decision.recommended_payment_method} | {decision.affordability_status} '
                  f'| ERRORS: {errors[:2]} ({elapsed:.1f}s)')
        else:
            if i % 25 == 0 or i <= 5:
                print(f'  [{i}/{len(requests_to_process)}] {req.request_id}: '
                      f'{decision.recommended_payment_method} | {decision.affordability_status} '
                      f'({elapsed:.1f}s)')

        decisions.append(decision)
        if diag:
            diagnostics.append(diag)

    total_time = time.time() - t0
    print(f'\nCompleted {len(decisions)} requests in {total_time:.1f}s '
          f'({total_time/len(decisions):.2f}s/req)')
    print(f'Errors: {error_count}')

    # Write output
    if mode == 'full':
        write_output(decisions, OUTPUT_PATH)

    return decisions


def main():
    parser = argparse.ArgumentParser(description='Buy or Wait? financial decision engine')
    parser.add_argument('--mode', choices=['full', 'sample'], default='full',
                        help='full: process evaluation requests; sample: process sample requests')
    parser.add_argument('--debug', action='store_true', help='Print per-request diagnostics')
    args = parser.parse_args()
    run(mode=args.mode, debug=args.debug)


if __name__ == '__main__':
    main()
