"""
v3/experiments/run_baselines.py

Experiment 001: Statistical & Deterministic Baselines Benchmark.
Evaluates 6 baselines on all 8,018 out-of-time test points:
1. naive_last
2. recent_median_3
3. rolling_median_8 (V2 heuristic)
4. rolling_mean_8
5. cadence_normalized
6. seasonal_monthly
"""
import sys, os, time
sys.path.insert(0, os.path.abspath('.'))

from v3.forecasting.dataset import build_forecasting_dataset
from v3.forecasting.backtest import BacktestRunner
from v3.forecasting.baselines import BASELINES


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
    print("Loading dataset and creating temporal splits...")
    t0 = time.time()
    dataset = build_forecasting_dataset(min_history=5, train_ratio=0.70)
    summary = dataset.summary()
    print(f"Dataset ready in {time.time()-t0:.1f}s")
    print(f"  Eligible Series: {summary['eligible_series_count']} (Variable: {summary['variable_series_count']}, Fixed: {summary['fixed_series_count']})")
    print(f"  Excluded Series (<5 obs): {summary['excluded_series_count']}")
    print(f"  Train Samples: {summary['total_train_samples']}")
    print(f"  Test Samples: {summary['total_test_samples']} (Variable: {summary['variable_test_samples']}, Fixed: {summary['fixed_test_samples']})")

    runner = BacktestRunner(dataset)
    print(f"BacktestRunner initialized with {len(runner.naive_mae_map)} in-sample series naive errors.")

    results = {}
    for name in BASELINES.keys():
        t1 = time.time()
        records, segmented = runner.evaluate_baseline(name)
        elapsed = time.time() - t1
        results[name] = (records, segmented)
        overall = segmented['overall']['all']
        print(f"  [Baseline] {name:<20} MASE: {overall.mase:.4f} | sMAPE: {overall.smape:.2f}% | NormMAE: {overall.norm_mae*100:.4f}% | MAE: {overall.mae:.2f} ({elapsed:.1f}s)")

    # 1. Overall Comparison Table
    headers = ['Baseline', 'MASE', 'sMAPE%', 'MAPE%', 'NormMAE%', 'MedAE', 'MAE', 'RMSE', 'Underest%', 'Overest%']
    rows = []
    for name in BASELINES.keys():
        m = results[name][1]['overall']['all']
        rows.append([
            name,
            f"{m.mase:.4f}",
            f"{m.smape:.2f}%",
            f"{m.mape:.2f}%",
            f"{m.norm_mae*100:.4f}%",
            f"{m.med_ae:.2f}",
            f"{m.mae:.2f}",
            f"{m.rmse:.2f}",
            f"{m.underestimate_rate:.1f}%",
            f"{m.overestimate_rate:.1f}%",
        ])
    print_table(headers, rows, "OVERALL OUT-OF-TIME BASELINE BENCHMARK (N=8,018)")

    # 2. Variable Categories Comparison Table
    var_rows = []
    for name in BASELINES.keys():
        m = results[name][1]['category_type']['variable']
        var_rows.append([
            name,
            f"{m.mase:.4f}",
            f"{m.smape:.2f}%",
            f"{m.mape:.2f}%",
            f"{m.norm_mae*100:.4f}%",
            f"{m.med_ae:.2f}",
            f"{m.mae:.2f}",
            f"{m.rmse:.2f}",
            f"{m.underestimate_rate:.1f}%",
            f"{m.overestimate_rate:.1f}%",
        ])
    print_table(headers, var_rows, "VARIABLE CATEGORIES BENCHMARK (N=5,357) [Real Forecasting Challenge]")

    # 3. Fixed Categories Comparison Table
    fix_rows = []
    for name in BASELINES.keys():
        m = results[name][1]['category_type']['fixed']
        fix_rows.append([
            name,
            f"{m.mase:.4f}",
            f"{m.smape:.2f}%",
            f"{m.mape:.2f}%",
            f"{m.norm_mae*100:.4f}%",
            f"{m.med_ae:.2f}",
            f"{m.mae:.2f}",
            f"{m.rmse:.2f}",
            f"{m.underestimate_rate:.1f}%",
            f"{m.overestimate_rate:.1f}%",
        ])
    print_table(headers, fix_rows, "FIXED CATEGORIES BENCHMARK (N=2,661)")

    # 4. Currency Breakdown for Best Baseline (rolling_median_8)
    best_name = 'rolling_median_8'
    ccy_headers = ['Currency', 'Samples', 'MAE', 'MedAE', 'RMSE', 'sMAPE%', 'NormMAE%']
    ccy_rows = []
    for ccy, m in sorted(results[best_name][1]['currency'].items()):
        ccy_rows.append([
            ccy,
            m.sample_count,
            f"{m.mae:.2f}",
            f"{m.med_ae:.2f}",
            f"{m.rmse:.2f}",
            f"{m.smape:.2f}%",
            f"{m.norm_mae*100:.4f}%",
        ])
    print_table(ccy_headers, ccy_rows, f"CURRENCY BREAKDOWN FOR '{best_name}' (Exposes IDR scale disparity)")

    # 5. Top Categories Breakdown for Best Baseline
    cat_headers = ['Category', 'Type', 'Samples', 'MAE', 'sMAPE%', 'NormMAE%', 'Underest%']
    cat_rows = []
    for cat, m in sorted(results[best_name][1]['category'].items(), key=lambda x: -x[1].sample_count)[:10]:
        cat_rows.append([
            cat,
            'Variable' if m.sample_count > 0 and results[best_name][0][0].is_variable else 'Mixed',
            m.sample_count,
            f"{m.mae:.2f}",
            f"{m.smape:.2f}%",
            f"{m.norm_mae*100:.4f}%",
            f"{m.underestimate_rate:.1f}%",
        ])
    print_table(cat_headers, cat_rows, f"TOP CATEGORIES BREAKDOWN FOR '{best_name}'")


if __name__ == '__main__':
    main()
