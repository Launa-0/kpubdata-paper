# Storage footprint (supplementary)

Storage is a supplementary trade-off, not a research question. The paper gives
it one paragraph in the main text and the numbers below in an appendix. Why the
earlier "storage amplification" design was dropped is recorded in
[`experiment-design-revisions.md`](experiment-design-revisions.md) (R-6).

## What is measured

`scripts/storage_footprint.py` → `results/storage_footprint.csv`,
`tables/appendix_storage.{csv,md}`.

As built, Bronze is JSONL and Silver is Parquet, so comparing their bytes
measures the codec rather than layering. The script therefore rewrites every
layer under **one controlled format** — Parquet, zstd level 3, row group 131,072,
the same writer (`parquet-cpp-arrow 25.0.1`) — and checks each file's footer for
exactly that before reporting. It refuses to report if any control is broken or
if the Silver builds come from different builders. The as-built bytes are kept
beside the controlled ones.

## Results (canonical run, paper `4fcca24`, builder `096d023`)

| dataset | rows | Bronze as built (JSONL) | Bronze, controlled | Silver, controlled | Bronze/Silver | (Bronze+Silver)/Silver |
|---|---:|---:|---:|---:|---:|---:|
| seoul-apartment-trades | 233,596 | 147,108,420 | 4,279,538 | 4,605,457 | 0.929 | 1.93 |
| seoul-apartment-rent | 1,221,491 | 631,347,691 | 18,075,117 | 19,669,225 | 0.919 | 1.92 |
| seoul-bike-rent-month | 4,902,236 | 1,514,390,369 | 75,100,718 | 75,588,812 | 0.994 | 1.99 |

Bytes. The ratio is **Bronze/Silver**.

## How it is read

- Under the same format, a Bronze and a Silver of the same data are about the
  same size (Bronze/Silver 0.92–0.99). The as-built gap (Bronze JSONL against
  Silver Parquet as built, 22–30×) is serialization and compression, not
  layering.
- The storage cost of layering is therefore not an oversized Silver. It is
  keeping several materialized representations at once: retaining Bronze and
  Silver together costs about twice Silver alone.
- Absolute sizes depend on codec settings and are not extrapolated beyond these
  datasets.

## Main-text paragraph (draft)

> Under an identical Parquet codec and writer, the Bronze/Silver size ratio was
> 0.929 (trades), 0.919 (rent) and 0.994 (bike), so individual Bronze and Silver
> layers were of similar size. The storage cost of layering therefore comes from
> retaining several materialized representations together rather than from an
> unusual expansion of Silver itself. Details are in the appendix.
