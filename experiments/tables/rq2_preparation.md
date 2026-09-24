# rq2_preparation

equivalence는 Silver 조건의 output_hash와 같은지다. prepared_rows는 원천 레코드 수가 아니라 준비 산출물의 행 수다 — T1/T3은 25개 자치구 × 60개월로 집계되어 1,500행이 된다.

| task | condition | prepared_rows | preprocessing_loc | function_count | transformation_steps | output_hash | equivalence | join_matching_rate |
|---|---|---|---|---|---|---|---|---|
| task01 | bronze | 1,500 | 20 | 6 | 7 | bc8896c454ab | PASS | — |
| task01 | silver | 1,500 | 12 | 3 | 3 | bc8896c454ab | PASS | — |
| task01 | gold | 1,500 | 2 | 0 | 0 | bc8896c454ab | PASS | — |
| task01 | monolithic | 1,500 | 16 | 6 | 1 | bc8896c454ab | PASS | — |
| task03 | bronze | 1,500 | 50 | 13 | 7 | 607132358d10 | PASS | 0.6341 |
| task03 | silver | 1,500 | 34 | 10 | 4 | 607132358d10 | PASS | 0.6341 |
| task03 | gold | 1,500 | 2 | 0 | 0 | 607132358d10 | PASS | — |
| task03 | monolithic | 1,500 | 46 | 13 | 1 | 607132358d10 | PASS | 0.6341 |
