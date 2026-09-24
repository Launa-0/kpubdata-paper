# rq2_timing

같은 round의 쌍 5개. ratio = monolithic ÷ materialized, Δ = monolithic − materialized (초). 1·0보다 크면 materialized가 빠르다.

| task | engine | scenario | n_pairs | materialized_median | monolithic_median | median_paired_ratio | median_paired_delta_seconds |
|---|---|---|---|---|---|---|---|
| task01 | pandas | S1 | 5 | 0.0223 | 0.9084 | 41.44 | 0.8861 |
| task01 | pandas | S2 | 5 | 0.6749 | 0.9401 | 1.356 | 0.2469 |
| task01 | pandas | S3 | 5 | 1.804 | 0.9438 | 0.5334 | -0.8417 |
| task01 | pandas | S4 | 5 | 1.716 | 0.8923 | 0.5042 | -0.8776 |
| task01 | polars | S1 | 5 | 0.01359 | 0.1159 | 8.67 | 0.1043 |
| task01 | polars | S2 | 5 | 0.1004 | 0.1184 | 1.142 | 0.01427 |
| task01 | polars | S3 | 5 | 0.3021 | 0.1254 | 0.4752 | -0.1641 |
| task01 | polars | S4 | 5 | 0.3124 | 0.1356 | 0.4764 | -0.1636 |
| task03 | pandas | S1 | 5 | 0.01413 | 8.012 | 567.9 | 7.998 |
| task03 | pandas | S2 | 5 | 4.624 | 6.987 | 1.481 | 2.213 |
| task03 | pandas | S3 | 5 | 9.383 | 6.566 | 0.7004 | -3.095 |
| task03 | pandas | S4 | 5 | 10.96 | 7.863 | 0.7171 | -3.136 |
| task03 | polars | S1 | 5 | 0.01077 | 0.9534 | 84.67 | 0.94 |
| task03 | polars | S2 | 5 | 0.7286 | 0.9002 | 1.24 | 0.1717 |
| task03 | polars | S3 | 5 | 1.867 | 0.9876 | 0.5359 | -0.8552 |
| task03 | polars | S4 | 5 | 2.152 | 1.121 | 0.5259 | -1.02 |
