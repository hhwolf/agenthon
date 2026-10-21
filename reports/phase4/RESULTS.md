# Phase 4 practice ablation

Decision: **card_notes_l05** (provisional: full model-label replay unavailable).

88 paired practice proxies; 2,000 draws; 0/88 successful cached model labels available.

| arm | mean | median | caps | mean delta 95% year-block CI |
|---|---:|---:|---:|---|
| numeric_v1_1 | 2.415744 | 1.365856 | 9 | [+0.000000, +0.000000] |
| text_l05 | unavailable | unavailable | unavailable | missing validated cache |
| text_l10 | unavailable | unavailable | unavailable | missing validated cache |
| card_notes_l05 | 2.378141 | 1.355453 | 9 | [-0.068127, -0.013183] |

| family | arm | cards | mean | caps |
|---|---|---:|---:|---:|
| T2-F1 | numeric_v1_1 | 19 | 0.841566 | 0 |
| T2-F2 | numeric_v1_1 | 23 | 2.033922 | 0 |
| T2-F3 | numeric_v1_1 | 18 | 1.277705 | 0 |
| T2-F4 | numeric_v1_1 | 28 | 4.529173 | 9 |
| T2-F1 | card_notes_l05 | 19 | 0.842977 | 0 |
| T2-F2 | card_notes_l05 | 23 | 1.974978 | 0 |
| T2-F3 | card_notes_l05 | 18 | 1.276660 | 0 |
| T2-F4 | card_notes_l05 | 28 | 4.459123 | 9 |

No model requests were sent. Per-card deltas and new/removed caps are in the accompanying CSVs.
The B4 v2 rules inherited prior practice exposure; this is a development comparison, not an untouched holdout.
Coefficients and decision gates were frozen in VALIDATION.md before this run. No competition pack/upload.
