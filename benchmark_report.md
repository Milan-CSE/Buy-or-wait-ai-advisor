# Benchmark Report — Buy or Wait? Phase 1

**Overall accuracy:** 3/25 (12.0%)
**Runtime:** 8.5s

## Per-Field Accuracy

| Field | Pass | Total | % |
|---|---|---|---|
| amount_safe_to_pay | 3 | 25 | 12.0% |
| affordability_status | 23 | 25 | 92.0% |
| recommended_payment_method | 24 | 25 | 96.0% |
| payment_plan | 23 | 25 | 92.0% |
| earliest_date_for_full_payment | 22 | 25 | 88.0% |
| spending_changes_needed | 23 | 25 | 92.0% |

## Per-Request Results

| Request | Status | Method (pred) | Method (truth) | Amount (pred) | Amount (truth) | Failed Fields |
|---|---|---|---|---|---|---|
| request_01 | PASS | full_payment | full_payment | 25256.00 | 25256.00 | — |
| request_02 | FAIL | installments | installments | 17975691.25 | 17229139.20 | amount_safe_to_pay |
| request_03 | FAIL | wait | wait | 953044.59 | 873000.00 | amount_safe_to_pay |
| request_04 | FAIL | wait | wait | 9327783.69 | 8401800.00 | amount_safe_to_pay |
| request_05 | FAIL | not_recommended | not_recommended | 0.00 | 737.00 | amount_safe_to_pay |
| request_06 | FAIL | not_recommended | full_payment | 542.65 | 603.30 | amount_safe_to_pay, affordability_status, recommended_payment_method, payment_plan, spending_changes_needed |
| request_07 | FAIL | installments | installments | 86305.31 | 87170.56 | amount_safe_to_pay |
| request_08 | FAIL | wait | wait | 299.20 | 284.57 | amount_safe_to_pay |
| request_09 | PASS | full_payment | full_payment | 166.61 | 166.61 | — |
| request_10 | FAIL | not_recommended | not_recommended | 0.00 | 12700.00 | amount_safe_to_pay |
| request_11 | FAIL | full_payment | full_payment | 12646212.23 | 12510645.00 | amount_safe_to_pay |
| request_12 | FAIL | installments | installments | 60334.14 | 65164.00 | amount_safe_to_pay, earliest_date_for_full_payment |
| request_13 | FAIL | wait | wait | 543.21 | 433.40 | amount_safe_to_pay |
| request_14 | FAIL | not_recommended | not_recommended | 583.72 | 597.74 | amount_safe_to_pay |
| request_15 | FAIL | not_recommended | not_recommended | 91.73 | 83.05 | amount_safe_to_pay |
| request_16 | PASS | full_payment | full_payment | 122500.00 | 122500.00 | — |
| request_17 | FAIL | installments | installments | 240263.29 | 243849.58 | amount_safe_to_pay, earliest_date_for_full_payment |
| request_18 | FAIL | wait | wait | 550.07 | 462.00 | amount_safe_to_pay |
| request_19 | FAIL | partial_payment | partial_payment | 28585.55 | 28820.00 | amount_safe_to_pay, payment_plan |
| request_20 | FAIL | not_recommended | not_recommended | 9331.96 | 5400.00 | amount_safe_to_pay |
| request_21 | FAIL | full_payment | full_payment | 1574.40 | 1543.35 | amount_safe_to_pay, affordability_status, earliest_date_for_full_payment, spending_changes_needed |
| request_22 | FAIL | installments | installments | 465.42 | 475.46 | amount_safe_to_pay |
| request_23 | FAIL | wait | wait | 9505.10 | 9152.00 | amount_safe_to_pay |
| request_24 | FAIL | not_recommended | not_recommended | 12173.63 | 13420.00 | amount_safe_to_pay |
| request_25 | FAIL | not_recommended | not_recommended | 667117.74 | 1425000.00 | amount_safe_to_pay |

## Failure Analysis

### request_02
- **amount_safe_to_pay**: predicted `17975691.25` | truth `17229139.20`

### request_03
- **amount_safe_to_pay**: predicted `953044.59` | truth `873000.00`

### request_04
- **amount_safe_to_pay**: predicted `9327783.69` | truth `8401800.00`

### request_05
- **amount_safe_to_pay**: predicted `0.00` | truth `737.00`

### request_06
- **amount_safe_to_pay**: predicted `542.65` | truth `603.30`
- **affordability_status**: predicted `not_affordable` | truth `affordable_with_plan`
- **recommended_payment_method**: predicted `not_recommended` | truth `full_payment`
- **payment_plan**: predicted `none` | truth `2026-01-03:620.40`
- **spending_changes_needed**: predicted `none` | truth `stop:event_476`

### request_07
- **amount_safe_to_pay**: predicted `86305.31` | truth `87170.56`

### request_08
- **amount_safe_to_pay**: predicted `299.20` | truth `284.57`

### request_10
- **amount_safe_to_pay**: predicted `0.00` | truth `12700.00`

### request_11
- **amount_safe_to_pay**: predicted `12646212.23` | truth `12510645.00`

### request_12
- **amount_safe_to_pay**: predicted `60334.14` | truth `65164.00`
- **earliest_date_for_full_payment**: predicted `` | truth `2026-04-05`

### request_13
- **amount_safe_to_pay**: predicted `543.21` | truth `433.40`

### request_14
- **amount_safe_to_pay**: predicted `583.72` | truth `597.74`

### request_15
- **amount_safe_to_pay**: predicted `91.73` | truth `83.05`

### request_17
- **amount_safe_to_pay**: predicted `240263.29` | truth `243849.58`
- **earliest_date_for_full_payment**: predicted `2026-04-15` | truth `2026-03-15`

### request_18
- **amount_safe_to_pay**: predicted `550.07` | truth `462.00`

### request_19
- **amount_safe_to_pay**: predicted `28585.55` | truth `28820.00`
- **payment_plan**: predicted `2024-09-04:28585.55|2024-09-15:11074.45` | truth `2024-09-04:28820.00|2024-09-15:10840.00`

### request_20
- **amount_safe_to_pay**: predicted `9331.96` | truth `5400.00`

### request_21
- **amount_safe_to_pay**: predicted `1574.40` | truth `1543.35`
- **affordability_status**: predicted `affordable_now` | truth `affordable_with_plan`
- **earliest_date_for_full_payment**: predicted `2026-04-03` | truth `2026-04-15`
- **spending_changes_needed**: predicted `none` | truth `reduce_to:event_1816:23.50|stop:event_1815`

### request_22
- **amount_safe_to_pay**: predicted `465.42` | truth `475.46`

### request_23
- **amount_safe_to_pay**: predicted `9505.10` | truth `9152.00`

### request_24
- **amount_safe_to_pay**: predicted `12173.63` | truth `13420.00`

### request_25
- **amount_safe_to_pay**: predicted `667117.74` | truth `1425000.00`
