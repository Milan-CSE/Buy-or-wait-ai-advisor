"""
benchmark.py
Runs the engine on all 25 sample requests and compares against ground truth.

Outputs:
  - benchmark_report.md: summary table with match/mismatch analysis
  - failure_cases.csv: rows where any field differs from ground truth
"""
from __future__ import annotations

import csv
import os
import sys
import time
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(__file__))

from data_loader import load_dataset, SampleRequest
from currency import FXEngine
from main import process_request, run
from ranker import Decision

ROOT_DIR = os.path.join(os.path.dirname(__file__), '..')
REPORT_PATH = os.path.join(ROOT_DIR, 'benchmark_report.md')
FAILURES_PATH = os.path.join(ROOT_DIR, 'failure_cases.csv')

# Fields to compare (all output fields)
COMPARE_FIELDS = [
    'amount_safe_to_pay',
    'affordability_status',
    'recommended_payment_method',
    'payment_plan',
    'earliest_date_for_full_payment',
    'spending_changes_needed',
]

# Fields with tolerance for numeric comparison
NUMERIC_FIELDS = {'amount_safe_to_pay'}
NUMERIC_TOLERANCE = Decimal('0.01')


def _format_amt(v) -> str:
    if v is None:
        return ''
    try:
        return f'{Decimal(str(v)):.2f}'
    except Exception:
        return str(v)


def _format_date(v) -> str:
    if v is None or str(v).strip() in ('', 'nan', 'NaN'):
        return ''
    if isinstance(v, date):
        return v.isoformat()
    return str(v).strip()


def _normalize_plan(plan_str: str) -> str:
    """Normalize payment plan for comparison: sort by date, normalize amounts."""
    if not plan_str or plan_str == 'none':
        return 'none'
    parts = plan_str.split('|')
    normalized = []
    for p in parts:
        if ':' in p:
            dt_str, amt_str = p.split(':', 1)
            try:
                amt = Decimal(amt_str)
                normalized.append(f'{dt_str.strip()}:{amt:.2f}')
            except Exception:
                normalized.append(p.strip())
        else:
            normalized.append(p.strip())
    return '|'.join(sorted(normalized))


def _normalize_changes(changes_str: str) -> str:
    """Normalize spending changes for comparison: sort actions."""
    if not changes_str or changes_str == 'none':
        return 'none'
    parts = sorted(changes_str.split('|'))
    return '|'.join(parts)


def extract_decision_values(d: Decision) -> Dict[str, str]:
    """Extract decision values as comparable strings."""
    return {
        'amount_safe_to_pay': _format_amt(d.amount_safe_to_pay),
        'affordability_status': d.affordability_status,
        'recommended_payment_method': d.recommended_payment_method,
        'payment_plan': _normalize_plan(d.payment_plan),
        'earliest_date_for_full_payment': _format_date(d.earliest_date_for_full_payment),
        'spending_changes_needed': _normalize_changes(d.spending_changes_needed),
    }


def extract_ground_truth_values(sr: SampleRequest) -> Dict[str, str]:
    """Extract ground truth values as comparable strings."""
    return {
        'amount_safe_to_pay': _format_amt(sr.amount_safe_to_pay),
        'affordability_status': sr.affordability_status,
        'recommended_payment_method': sr.recommended_payment_method,
        'payment_plan': _normalize_plan(sr.payment_plan),
        'earliest_date_for_full_payment': _format_date(sr.earliest_date_for_full_payment),
        'spending_changes_needed': _normalize_changes(sr.spending_changes_needed),
    }


def compare_fields(pred: Dict[str, str], truth: Dict[str, str]) -> Dict[str, bool]:
    """Compare predicted vs truth for each field. True = match."""
    results = {}
    for field in COMPARE_FIELDS:
        p = pred.get(field, '')
        t = truth.get(field, '')

        if field in NUMERIC_FIELDS:
            try:
                diff = abs(Decimal(p) - Decimal(t))
                results[field] = diff <= NUMERIC_TOLERANCE
            except Exception:
                results[field] = (p == t)
        else:
            results[field] = (p == t)
    return results


def run_benchmark() -> None:
    """Run benchmark on all 25 sample requests."""
    print('Running benchmark on 25 sample requests...\n')
    t0 = time.time()

    dataset = load_dataset()
    fx = FXEngine(dataset.fx_index)

    sample_requests = list(dataset.sample_requests.values())
    sample_requests.sort(key=lambda sr: sr.request.request_id)

    results = []
    all_decisions: Dict[str, Decision] = {}

    for sr in sample_requests:
        req = sr.request
        decision, diag, errors = process_request(req, dataset, fx, debug=False)

        pred = extract_decision_values(decision)
        truth = extract_ground_truth_values(sr)
        matches = compare_fields(pred, truth)

        all_match = all(matches.values())
        results.append({
            'request_id': req.request_id,
            'pred': pred,
            'truth': truth,
            'matches': matches,
            'all_match': all_match,
            'errors': errors,
        })
        all_decisions[req.request_id] = decision

        status = 'PASS' if all_match else 'FAIL'
        failed_fields = [f for f, ok in matches.items() if not ok]
        print(f'  {status} {req.request_id}: '
              f'{decision.recommended_payment_method} | {decision.affordability_status}',
              end='')
        if failed_fields:
            print(f'  MISMATCH: {failed_fields}')
        else:
            print()

    total_time = time.time() - t0
    total = len(results)
    passed = sum(1 for r in results if r['all_match'])

    print(f'\nBenchmark complete: {passed}/{total} exact matches ({100*passed/total:.1f}%)')

    # Per-field accuracy
    field_pass = {f: 0 for f in COMPARE_FIELDS}
    for r in results:
        for f in COMPARE_FIELDS:
            if r['matches'].get(f):
                field_pass[f] += 1

    print('\nPer-field accuracy:')
    for f in COMPARE_FIELDS:
        pct = 100 * field_pass[f] / total
        print(f'  {f}: {field_pass[f]}/{total} ({pct:.1f}%)')

    # Write benchmark_report.md
    _write_report(results, total, passed, field_pass, total_time)

    # Write failure_cases.csv
    _write_failures(results)

    print(f'\nReports written to {REPORT_PATH} and {FAILURES_PATH}')


def _write_report(results, total, passed, field_pass, elapsed):
    lines = [
        '# Benchmark Report — Buy or Wait? Phase 1',
        '',
        f'**Overall accuracy:** {passed}/{total} ({100*passed/total:.1f}%)',
        f'**Runtime:** {elapsed:.1f}s',
        '',
        '## Per-Field Accuracy',
        '',
        '| Field | Pass | Total | % |',
        '|---|---|---|---|',
    ]
    for f in COMPARE_FIELDS:
        pct = 100 * field_pass[f] / total
        lines.append(f'| {f} | {field_pass[f]} | {total} | {pct:.1f}% |')

    lines += ['', '## Per-Request Results', '',
              '| Request | Status | Method (pred) | Method (truth) | Amount (pred) | Amount (truth) | Failed Fields |',
              '|---|---|---|---|---|---|---|']

    for r in results:
        req_id = r['request_id']
        status = 'PASS' if r['all_match'] else 'FAIL'
        failed = [f for f, ok in r['matches'].items() if not ok]
        lines.append(
            f'| {req_id} | {status} | {r["pred"]["recommended_payment_method"]} | '
            f'{r["truth"]["recommended_payment_method"]} | '
            f'{r["pred"]["amount_safe_to_pay"]} | {r["truth"]["amount_safe_to_pay"]} | '
            f'{", ".join(failed) if failed else "—"} |'
        )

    lines += ['', '## Failure Analysis', '']
    failed_results = [r for r in results if not r['all_match']]
    if not failed_results:
        lines.append('All samples passed!')
    else:
        for r in failed_results:
            lines.append(f'### {r["request_id"]}')
            for f in COMPARE_FIELDS:
                if not r['matches'].get(f):
                    lines.append(f'- **{f}**: predicted `{r["pred"][f]}` | truth `{r["truth"][f]}`')
            if r['errors']:
                lines.append(f'- **Errors**: {r["errors"]}')
            lines.append('')

    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def _write_failures(results):
    failed = [r for r in results if not r['all_match']]
    if not failed:
        # Write empty CSV with headers
        with open(FAILURES_PATH, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['request_id', 'field', 'predicted', 'truth'])
            writer.writeheader()
        return

    rows = []
    for r in failed:
        for f in COMPARE_FIELDS:
            if not r['matches'].get(f):
                rows.append({
                    'request_id': r['request_id'],
                    'field': f,
                    'predicted': r['pred'][f],
                    'truth': r['truth'][f],
                })

    with open(FAILURES_PATH, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['request_id', 'field', 'predicted', 'truth'])
        writer.writeheader()
        writer.writerows(rows)


if __name__ == '__main__':
    run_benchmark()
