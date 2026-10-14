# Baselines — 2026-10-14

Historical pseudo-cards: 2,060, seed 20261014, 500 forecast draws. Lower is better.
No forecast failures. Data and interpretation limits are in [BUILD_LOG.md](BUILD_LOG.md).

| Forecaster | Historical mean | Practice proxy mean (88 cards) | Gates |
|---|---:|---:|---|
| M0 | 1.214629 | 2.551735 | 104/104 |
| Reference CLI | 1.394364 | 2.557722 | 104/104 |

M0 Gaussian calibration: one outcome/card **0.951098**; 20 additional outcome replicas/card
**1.002631**, SE **0.003014**. These model checks are separate from historical performance.

## By family

| family | Cards | M0 | Reference |
|---|---:|---:|---:|
| T2-F1 | 460 | 1.497624 | 2.110561 |
| T2-F2 | 540 | 1.087573 | 1.091221 |
| T2-F3 | 440 | 1.219362 | 1.280128 |
| T2-F4 | 620 | 1.111968 | 1.208091 |

## By panel

| panel | Cards | M0 | Reference |
|---|---:|---:|---:|
| factors_daily | 320 | 1.122978 | 1.239347 |
| g10_fx_daily | 700 | 1.131343 | 1.193123 |
| g10_fx_daily+rates_daily | 100 | 1.192919 | 1.298607 |
| macro_monthly | 80 | 1.687447 | 2.095316 |
| rates_daily | 860 | 1.275065 | 1.561775 |

## By target type

| target_type | Cards | M0 | Reference |
|---|---:|---:|---:|
| level | 1740 | 1.231485 | 1.422873 |
| log_return | 320 | 1.122978 | 1.239347 |

## By horizon bucket

| horizon_bucket | Cards | M0 | Reference |
|---|---:|---:|---:|
| 127+ | 460 | 1.497624 | 2.110561 |
| 1–21 | 520 | 1.085013 | 1.194082 |
| 22–63 | 580 | 1.104007 | 1.147564 |
| 64–126 | 500 | 1.217396 | 1.230045 |

## By shape

| shape | Cards | M0 | Reference |
|---|---:|---:|---:|
| joint | 860 | 1.353166 | 1.723316 |
| single | 1200 | 1.115344 | 1.158615 |

