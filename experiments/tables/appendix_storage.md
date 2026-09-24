# appendix_storage

Bronze와 Silver를 같은 조건(Parquet zstd(3), row group 131,072, 같은 writer)으로 다시 쓴 크기.

| dataset | rows | bronze_jsonl_bytes | bronze_parquet_bytes | silver_parquet_bytes | bronze_to_silver | bronze_plus_silver_to_silver |
|---|---|---|---|---|---|---|
| seoul-apartment-trades | 233,596 | 147,108,420 | 4,279,538 | 4,605,457 | 0.9292 | 1.929 |
| seoul-apartment-rent | 1,221,491 | 631,347,691 | 18,075,117 | 19,669,225 | 0.919 | 1.919 |
| seoul-bike-rent-month | 4,902,236 | 1,514,390,369 | 75,100,718 | 75,588,812 | 0.9935 | 1.994 |
