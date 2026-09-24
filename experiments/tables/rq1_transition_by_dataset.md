# rq1_transition_by_dataset

계산 단위는 role × transition cause이며, 이 표는 가독성을 위해 dataset 수준으로 집계한 것이다. 원자료: `rq1_role_transition.parquet`.

| dataset | role_cells | changed_cells | changed_rate | primitive_type_normalization | numeric_formatting | identifier_padding | date_year_month_normalization | null_canonicalization | derived_field | unchanged |
|---|---|---|---|---|---|---|---|---|---|---|
| seoul-apartment-trades | 4,905,516 | 1,168,608 | 0.2382 | 701,416 | 233,596 | 0 | 0 | 0 | 233,596 | 3,736,908 |
| seoul-apartment-rent | 21,986,838 | 4,941,299 | 0.2247 | 2,511,996 | 1,207,812 | 0 | 0 | 0 | 1,221,491 | 17,045,539 |
| seoul-bike-rent-month | 53,924,596 | 30,648,135 | 0.5684 | 24,500,672 | 0 | 2,241,547 | 1,914,327 | 1,991,589 | 0 | 23,276,461 |
