# dataset_scope

스냅샷 metadata.json의 기간과 원천 행 수.

| dataset | snapshot_id | period | rows | role | rq |
|---|---|---|---|---|---|
| seoul-apartment-trades | seoul-apartment-trades/20260922-6660c8e25162 | 2020-01~2024-12 | 233,596 | T1·T3 입력, RQ1, R1, perturbation | RQ1·RQ2·RQ3 |
| seoul-apartment-rent | seoul-apartment-rent/20260923-a0ed9577c41a | 2020-01~2024-12 | 1,221,491 | T3 입력, RQ1 | RQ1·RQ2 |
| seoul-bike-rent-month | seoul-bike-rent-month/20260923-637ec21bb5b1 | 2020-01~2023-12 | 4,902,236 | RQ1, R2 통합본(G1+G2+I1+G3) | RQ1·RQ3 |
| seoul-bike-rent-month-g1 | seoul-bike-rent-month-g1/20260923-e91d2c485eaf | 2020-01~2020-05 | 327,231 | R2 세대, perturbation | RQ3 |
| seoul-bike-rent-month-g2 | seoul-bike-rent-month-g2/20260923-ba6abb36ac55 | 2020-06~2022-12 | 3,200,206 | R2 세대 | RQ3 |
| seoul-bike-rent-month-i1 | seoul-bike-rent-month-i1/20260923-073f1cc75897 | 2021-09~2021-09 | 128,413 | R2 세대 | RQ3 |
| seoul-bike-rent-month-g3 | seoul-bike-rent-month-g3/20260923-43082467e187 | 2023-01~2023-12 | 1,246,386 | R2 세대 | RQ3 |
| seoul-bike-rent-month-g4 | seoul-bike-rent-month-g4/20260923-1e55bf10ac1d | 2024-01~2024-12 | 32,786 | R2 세대 (관측 단위 변경) | RQ3 |
