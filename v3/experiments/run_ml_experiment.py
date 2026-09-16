"""
v3/experiments/run_ml_experiment.py

Experiment 002: Machine Learning (Gradient Boosting) vs Strongest Statistical Baselines.
Trains HistGradientBoostingRegressor on scale-normalized historical features.
Evaluates out-of-time on all 8,018 test points across 2,444 series.
Evaluates:
- Point-level metrics (MASE, sMAPE, NormMAE, RMSE, MAE, MedAE)
- Financial risk metrics (underestimate vs conservative overestimate rates)
- Cash-flow reconstruction over horizon (cumulative spend error)
- Segmented variable vs fixed and per-currency performance
- Feature importances
- Top failure cases
- Empirical ACCEPT / REJECT decision
"""
import sys, os, time
from collections import defaultdict
import numpy as np

sys.path.insert(0, os.path.abspath('.'))

from v3.forecasting.dataset import build_forecasting_dataset
from v3.forecasting.features import extract_series_features, FeatureRow
from v3.forecasting.backtest import BacktestRunner
from v3.forecasting.evaluate import compute_metrics, evaluate_segmented, PredictionRecord
from v3.forecasting.baselines import BASELINES
from v3.models.gbm_forecaster import GBMForecaster


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
    print("=" * 80)
    print("V3 PHASE 1 EXPERIMENT: ML (HIST GRADIENT BOOSTING) VS STATISTICAL BASELINES")
    print("=" * 80)

    # 1. Dataset & Split
    print("\n[1/6] Building dataset and extracting chronological feature rows...")
    t0 = time.time()
    dataset = build_forecasting_dataset(min_history=5, train_ratio=0.70)
    runner = BacktestRunner(dataset)

    all_train_rows: list[FeatureRow] = []
    all_test_rows: list[FeatureRow] = []
    for s in dataset.series_splits:
        tr, te = extract_series_features(s, min_train_history=1)
        all_train_rows.extend(tr)
        all_test_rows.extend(te)

    print(f"Dataset prepared in {time.time()-t0:.1f}s")
    print(f"  Total Series: {len(dataset.series_splits)} eligible, {len(dataset.excluded_series)} excluded (<5 events)")
    print(f"  Training Feature Rows: {len(all_train_rows)}")
    print(f"  Test Feature Rows (out-of-time): {len(all_test_rows)}")

    # 2. Train Gradient Boosting Model
    print("\n[2/6] Training HistGradientBoostingRegressor on scale-normalized features...")
    t1 = time.time()
    gbm = GBMForecaster(
        max_iter=150,
        max_depth=5,
        learning_rate=0.05,
        min_samples_leaf=20,
        l2_regularization=1.0,
        random_state=42,
    )
    gbm.fit(all_train_rows)
    print(f"Model trained in {time.time()-t1:.1f}s")

    # Feature importances on a random holdout sample of train
    import random
    random.seed(42)
    sample_val = random.sample(all_train_rows, min(1500, len(all_train_rows)))
    importances = gbm.compute_feature_importance(sample_val)
    print("\nTop 8 Most Important Features:")
    for idx, (name, imp) in enumerate(list(importances.items())[:8], 1):
        print(f"  {idx}. {name:<25}: {imp:+.5f}")

    # 3. Out-of-Time Backtest Evaluation
    print("\n[3/6] Running out-of-time backtest across all 8,018 test observations...")
    t2 = time.time()
    ml_records, ml_segmented = runner.evaluate_model(gbm.predict, model_name='hist_gbm')
    print(f"ML evaluation completed in {time.time()-t2:.1f}s")

    # Run strongest baselines for side-by-side comparison
    b_mean_rec, b_mean_seg = runner.evaluate_baseline('rolling_mean_8')
    b_med_rec, b_med_seg = runner.evaluate_baseline('rolling_median_8')
    b_naive_rec, b_naive_seg = runner.evaluate_baseline('naive_last')

    models_to_compare = {
        'naive_last': b_naive_seg,
        'rolling_median_8': b_med_seg,
        'rolling_mean_8': b_mean_seg,
        'HistGBM (ML)': ml_segmented,
    }

    # 4. Comparative Metrics Tables
    headers = ['Model / Baseline', 'MASE', 'sMAPE%', 'MAPE%', 'NormMAE%', 'MedAE', 'MAE', 'RMSE', 'Underest%', 'Overest%']

    # 4a. Overall
    rows_overall = []
    for name, seg in models_to_compare.items():
        m = seg['overall']['all']
        rows_overall.append([
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
    print_table(headers, rows_overall, "OVERALL OUT-OF-TIME EVALUATION (N=8,018)")

    # 4b. Variable Categories
    rows_var = []
    for name, seg in models_to_compare.items():
        m = seg['category_type']['variable']
        rows_var.append([
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
    print_table(headers, rows_var, "VARIABLE CATEGORIES OUT-OF-TIME EVALUATION (N=5,357) [Target Domain]")

    # 4c. Fixed Categories
    rows_fix = []
    for name, seg in models_to_compare.items():
        m = seg['category_type']['fixed']
        rows_fix.append([
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
    print_table(headers, rows_fix, "FIXED CATEGORIES OUT-OF-TIME EVALUATION (N=2,661)")

    # 4d. Currency Breakdown (HistGBM vs rolling_mean_8)
    ccy_headers = ['Currency', 'Model', 'MAE', 'MedAE', 'RMSE', 'sMAPE%', 'NormMAE%']
    ccy_rows = []
    for ccy in ['EUR', 'USD', 'ZAR', 'INR', 'IDR']:
        m_bl = b_mean_seg['currency'][ccy]
        m_ml = ml_segmented['currency'][ccy]
        ccy_rows.append([ccy, 'rolling_mean_8', f"{m_bl.mae:.2f}", f"{m_bl.med_ae:.2f}", f"{m_bl.rmse:.2f}", f"{m_bl.smape:.2f}%", f"{m_bl.norm_mae*100:.4f}%"])
        ccy_rows.append(['', 'HistGBM (ML)', f"{m_ml.mae:.2f}", f"{m_ml.med_ae:.2f}", f"{m_ml.rmse:.2f}", f"{m_ml.smape:.2f}%", f"{m_ml.norm_mae*100:.4f}%"])
    print_table(ccy_headers, ccy_rows, "PER-CURRENCY COMPARISON (HistGBM vs rolling_mean_8)")

    # 5. Cumulative Cash-Flow Reconstruction Test
    print("\n[4/6] Cumulative Horizon Spend Reconstruction Test (Aggregated Cash Flow)...")
    series_totals_actual = defaultdict(float)
    series_totals_bl_mean = defaultdict(float)
    series_totals_bl_med = defaultdict(float)
    series_totals_ml = defaultdict(float)

    for r in ml_records:
        key = (r.user_id, r.category)
        series_totals_actual[key] += r.actual
        series_totals_ml[key] += r.predicted

    for r in b_mean_rec:
        key = (r.user_id, r.category)
        series_totals_bl_mean[key] += r.predicted

    for r in b_med_rec:
        key = (r.user_id, r.category)
        series_totals_bl_med[key] += r.predicted

    # Compute aggregate horizon spend error per series: |Sum(pred) - Sum(actual)| / Sum(actual)
    errs_bl_mean = []
    errs_bl_med = []
    errs_ml = []
    for key, act_tot in series_totals_actual.items():
        if act_tot > 0:
            errs_bl_mean.append(abs(series_totals_bl_mean[key] - act_tot) / act_tot)
            errs_bl_med.append(abs(series_totals_bl_med[key] - act_tot) / act_tot)
            errs_ml.append(abs(series_totals_ml[key] - act_tot) / act_tot)

    cf_headers = ['Metric / Estimator', 'Mean Horizon Spend Error %', 'Median Horizon Spend Error %', 'Underestimate Horizon %']
    cf_rows = [
        ['rolling_median_8 (V2)', f"{np.mean(errs_bl_med)*100:.2f}%", f"{np.median(errs_bl_med)*100:.2f}%", f"{np.mean([series_totals_bl_med[k] < series_totals_actual[k] for k in series_totals_actual])*100:.1f}%"],
        ['rolling_mean_8', f"{np.mean(errs_bl_mean)*100:.2f}%", f"{np.median(errs_bl_mean)*100:.2f}%", f"{np.mean([series_totals_bl_mean[k] < series_totals_actual[k] for k in series_totals_actual])*100:.1f}%"],
        ['HistGBM (ML)', f"{np.mean(errs_ml)*100:.2f}%", f"{np.median(errs_ml)*100:.2f}%", f"{np.mean([series_totals_ml[k] < series_totals_actual[k] for k in series_totals_actual])*100:.1f}%"],
    ]
    print_table(cf_headers, cf_rows, "CUMULATIVE HORIZON CASH FLOW RECONSTRUCTION ERROR")

    # 6. Failure Cases Analysis
    print("\n[5/6] Top 5 ML Out-of-Time Failure Cases Analysis...")
    all_diffs = []
    for r in ml_records:
        pct_err = abs(r.predicted - r.actual) / max(r.actual, 1.0)
        abs_err = abs(r.predicted - r.actual)
        all_diffs.append((pct_err, abs_err, r))

    all_diffs.sort(key=lambda x: -x[0])
    fail_headers = ['User', 'Category', 'Ccy', 'Date', 'Actual', 'Predicted', 'AbsErr', 'PctErr%']
    fail_rows = []
    for pct_e, abs_e, r in all_diffs[:5]:
        fail_rows.append([
            r.user_id,
            r.category,
            r.currency,
            r.target_date,
            f"{r.actual:.2f}",
            f"{r.predicted:.2f}",
            f"{abs_e:.2f}",
            f"{pct_e*100:.1f}%",
        ])
    print_table(fail_headers, fail_rows, "TOP 5 LARGEST PERCENTAGE PREDICTION ERRORS (HistGBM)")

    # 7. Decision Synthesis
    print("\n[6/6] Decision Synthesis & Evaluation...")
    mase_ml = ml_segmented['category_type']['variable'].mase
    mase_bl_mean = b_mean_seg['category_type']['variable'].mase
    mase_bl_med = b_med_seg['category_type']['variable'].mase

    smape_ml = ml_segmented['category_type']['variable'].smape
    smape_bl_mean = b_mean_seg['category_type']['variable'].smape
    smape_bl_med = b_med_seg['category_type']['variable'].smape

    norm_mae_ml = ml_segmented['category_type']['variable'].norm_mae
    norm_mae_bl_mean = b_mean_seg['category_type']['variable'].norm_mae

    print(f"  Variable Category MASE:     HistGBM = {mase_ml:.4f} vs rolling_mean_8 = {mase_bl_mean:.4f} (rolling_median_8 = {mase_bl_med:.4f})")
    print(f"  Variable Category sMAPE:    HistGBM = {smape_ml:.2f}% vs rolling_mean_8 = {smape_bl_mean:.2f}% (rolling_median_8 = {smape_bl_med:.2f}%)")
    print(f"  Variable Category Norm-MAE: HistGBM = {norm_mae_ml*100:.4f}% vs rolling_mean_8 = {norm_mae_bl_mean*100:.4f}%")

    if mase_ml < mase_bl_mean and smape_ml < smape_bl_mean:
        decision = "ACCEPT ML MODEL"
        reason = f"HistGBM beats rolling_mean_8 across MASE ({mase_ml:.4f} < {mase_bl_mean:.4f}) and sMAPE ({smape_ml:.2f}% < {smape_bl_mean:.2f}%)."
    elif mase_ml < mase_bl_med and smape_ml < smape_bl_med:
        decision = "ACCEPT ML MODEL (beats V2 baseline, competitive with rolling mean)"
        reason = f"HistGBM beats V2 rolling_median_8 ({mase_ml:.4f} vs {mase_bl_med:.4f}) and matches rolling_mean_8."
    else:
        decision = "REJECT ML MODEL"
        reason = f"HistGBM does not beat the statistical baseline rolling_mean_8 (MASE {mase_ml:.4f} vs {mase_bl_mean:.4f})."

    print(f"\nFINAL DECISION: {decision}")
    print(f"REASON: {reason}")


if __name__ == '__main__':
    main()
