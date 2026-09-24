# Statistical reporting

The paper reports **descriptive statistics only**. No p-value, confidence
interval, effect size (Cohen's d, rank-biserial), normality test or
multiple-comparison correction is computed or reported. Why the earlier
inferential design was dropped is recorded in
[`experiment-design-revisions.md`](experiment-design-revisions.md) (R-2).

## Why no inference

Every measurement except timing is deterministic: rerunning a build or a task
on the same snapshot, contract and builder gives the same bytes (R1 checks this
directly). There is no sampling variation to test against.

Timing repeats are **technical replicates** of one machine, one environment and
one code state, not independent observations of a population. They show how
stable a measurement is on that machine; they do not license a claim beyond it.

## What is reported for timing

The timing protocol is fixed in `scripts/_timing.py`: T1 and T3, pandas and
polars reported separately, scenarios S1–S4, materialized against monolithic,
both reading the same Bronze Parquet, 1 warm-up and 5 measured runs per cell,
the two strategies interleaved within a round, raw repeats stored.

| | source | role |
|---|---|---|
| paired ratio `monolithic ÷ materialized`, median of the 5 same-round pairs | `timing_comparison.csv` | headline |
| paired Δ `monolithic − materialized` in seconds, median of the 5 pairs | `timing_comparison.csv` | reported beside every ratio, so a large ratio over milliseconds is not read as a large absolute cost |
| per-strategy median, IQR, min, max | `timing_summary.csv` | support |
| every repeat | `timing_raw_{pandas,polars}.parquet` | the source of both summaries |

Pairs are formed within a round, because the two strategies ran back to back
there; pairing by position across rounds would compare runs that did not share
conditions.

## How results are read

- The claim is the **direction** of a comparison and whether the five pairs
  agree on it, per task and engine: materialized is faster when only the
  analysis or Gold is invalidated (S1, S2), and slower when Silver or anything
  above it is invalidated (S3, S4), because it writes and rereads checkpoints.
- **Small differences between cells are not interpreted** — S3 against S4, or
  one engine's ratio against the other's. The design does not separate them
  from machine noise.
- Absolute seconds are specific to the measurement machine
  (`timing_environment_*.json`) and are not extrapolated.
