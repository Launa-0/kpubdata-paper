# experiments — Medallion pipeline evaluation harness

Everything that produces a number in the paper lives here. Bronze and Silver
artifacts are built by [`kpubdata-builder`](https://github.com/yeongseon/kpubdata-builder);
this harness builds them through fixed contracts, measures them and the analyses
that read them, and records the results with their provenance.

## What is evaluated

A Medallion pipeline (Bronze → Silver → Gold) over Korean public data, driven by
an explicit Silver **contract** (`scripts/<dataset>_spec.py`). The paper asks
what that contract does to source representations, what materializing layers
costs and saves, and what a fixed contract reproduces and where it stops. It
does not claim that layering produces better transformations than a monolithic
script, nor that it reduces human effort.

## Data

| dataset | period | source rows | used for |
|---|---|---:|---|
| `seoul-apartment-trades` (data.go.kr) | 2020-01 – 2024-12 | 233,596 | T1, T3, RQ1, R1, perturbation |
| `seoul-apartment-rent` (data.go.kr) | 2020-01 – 2024-12 | 1,221,491 | T3, RQ1 |
| `seoul-bike-rent-month` (data.seoul.go.kr), integrated G1+G2+I1+G3 | 2020-01 – 2023-12 | 4,902,236 | RQ1, R2 |
| bike source generations G1 / G2 / I1 / G3 / G4 | 2020-01 – 2024-12 | 32,786 – 3,200,206 each | R2; G1 also for perturbation |

Full table: [`tables/dataset_scope.md`](tables/dataset_scope.md). Generations
are defined in [`docs/bike-source-generations.md`](docs/bike-source-generations.md).
Two analysis tasks read these layers: **T1** (trades, district × month price
aggregate and trend) and **T3** (trades + rent join, jeonse ratio). There is no
T2 or T4.

## Research questions

| | question | measured by | main table / figure |
|---|---|---|---|
| **RQ1** contract-driven standardization | what the contract changes in source representations, and why | role × transition cause over every cell of the three datasets, Bronze → Silver. Causes follow rules fixed before the results ([`docs/rq1-transition-classification.md`](docs/rq1-transition-classification.md)). Layer comparison metrics are integrity checks only | `tables/rq1_transition_by_dataset` (appendix: `rq1_role_transition`) |
| **RQ2** materialization trade-offs | how materializing layers changes preparation code and recomputation cost | preparation code of T1/T3 under Bronze / Silver / Gold / monolithic (LOC and transformation functions; steps diagnostic); recomputation time of materialized against monolithic under S1–S4 | `tables/rq2_preparation`, `tables/rq2_timing`, `figures/timing_paired_ratio` |
| **RQ3** reproducibility and contract boundary | what a fixed contract reproduces and where it stops | R1: 10 rebuilds of one snapshot; R2: one contract over bike generations G1–G4; perturbation: 51 controlled mutations, the 20 semantics-breaking ones classified as declared / undeclared-but-expressible / not expressible | `tables/rq3_determinism`, `rq3_source_evolution`, `rq3_perturbation` |

- **Equivalence gate.** RQ2 compares costs only because all four conditions
  reach the same analysis result (`output_hash`). This is a validity condition,
  not a finding: Bronze ↔ Silver agree independently (harness parsers against
  builder casts), Silver ↔ Gold and Bronze ↔ monolithic agree by construction.
- **Scenarios.** S1 analysis-level, S2 Gold-level, S3 Silver/contract-level,
  S4 source-level invalidation (post-Bronze; Bronze checkpoint creation
  excluded). Both strategies read the same Bronze Parquet.
- **Storage** is a supplementary trade-off, not an RQ
  ([`docs/storage-tradeoff.md`](docs/storage-tradeoff.md)).
- **Statistics** are descriptive only — no p-values, intervals or effect sizes
  ([`docs/statistics.md`](docs/statistics.md)).
- Not part of the study: downstream prediction or time-series tasks, a
  comparison against external published statistics, a user study.

The overall design is drawn in [`figures/experimental_design.svg`](figures/experimental_design.svg).
How it came to be this way is recorded in
[`docs/experiment-design-revisions.md`](docs/experiment-design-revisions.md).

## Headline results

- **RQ1.** Share of role cells whose representation changed: trades 0.238,
  rent 0.225, bike 0.568, from primitive type normalization, numeric formatting,
  identifier padding, date/year-month normalization, null canonicalization and
  derived fields. Layer comparison metrics are integrity checks, not evidence of
  improvement — and they are not all equal on both sides. `duplicate_rate` in
  particular *rises* under canonicalization, because two rows that mean the same
  thing but spell a missing value differently are distinct in Bronze and
  identical in Silver
  ([`docs/bike-generation-runs.md`](docs/bike-generation-runs.md#duplicate_rate는-비교-지표가-아니다)).
- **RQ2.** Silver and Gold need less preparation code than Bronze and
  monolithic (T1 LOC 12 / 2 against 20 / 16; T3 34 / 2 against 50 / 46), with
  every condition passing the equivalence gate. Materialized recomputation was
  faster when only the analysis or Gold was invalidated (S1, S2), and slower
  than monolithic recomputation when Silver or anything above it was
  invalidated (S3, S4), because it writes and rereads checkpoints — in every
  task × engine cell and in all five same-round pairs.
- **RQ3.** R1: 10/10 builds, one digest, byte-identical to the canonical
  Silver. R2: G1, G2, I1, G3 and the integrated snapshot pass one contract with
  no row loss; G4 stops fail-closed at `silver/coalesce`. Perturbation: of 20
  semantics-breaking mutations, 12 are rejected and 8 pass silently — 5 the
  contract language could express but the contract does not declare, 3 it
  cannot express.
- **Storage.** Under one Parquet codec and writer, Bronze/Silver is 0.929 /
  0.919 / 0.994.

## Artifacts

```
experiments/
├── results/     # canonical measurements (committed) — the only source of every number
├── tables/      # paper tables, .csv (source) + .md (review), generated from results/
├── figures/     # paper figures, .svg (vector) + .png (300 dpi), generated from results/
├── datasets/    # per-build provenance.json (artifact bytes git-ignored)
├── snapshots/   # frozen source snapshots: metadata.json committed, bytes published separately
├── scripts/     # everything that builds, measures and reports — see scripts/README.md
├── src/kpx/     # the harness package
└── docs/        # design notes, one decision each
```

| result file | grain | written by |
|---|---|---|
| `rq1_role_transition.parquet` | dataset × role × transition cause | `quality_spectrum.py` |
| `rq1_coalesce_source.parquet`, `rq1_role_pair.parquet`, `rq1_layer_quality.parquet` | coalesced source rows; role pairs; layer view × metric | `quality_spectrum.py` |
| `experiment_results.parquet` (+ `.csv`) | task × condition | `run_task01.py`, `run_task03.py` |
| `timing_raw_{pandas,polars}.parquet`, `timing_summary.csv`, `timing_comparison.csv`, `timing_environment_*.json` | every repeat; cell summary; paired comparison | `time_pandas.py`, `time_polars.py`, `timing_report.py` |
| `r1_determinism.csv` | one rebuild | `r1_rebuild.py`, `r1_report.py` |
| `source_evolution.csv` | one bike generation | `r2_build.py`, `r2_report.py` |
| `perturbation.parquet`, `perturbation_counterfactual.json` | one mutation; counterfactual quality rules | `perturbation.py` |
| `storage_footprint.csv` | dataset × layer | `storage_footprint.py` |
| `canonical_manifest.json` | sha256 of every non-timing result file | `canonical_manifest.py` |

## Provenance

| what | commit | |
|---|---|---|
| builder | `096d023` | tag `paper-eval-builder-096d023` (kpubdata-builder), version `0.4.0.dev0+096d023f9546` |
| timing measurement | `920e019` | tag `timing-measured-920e019`; the `paper_sha` inside `timing_raw_*` |
| canonical run of every other result | `4fcca24` | `scripts/canonical.sh` on a clean tree |
| results first committed | `99ab145` | `results/canonical_manifest.json` binds file hashes to `4fcca24` / `096d023` |
| tables and figures | `154d83d` | generated from committed results; nothing re-measured |

Every result row names the snapshot, the contract's `config_hash` and the
builder version (`pipeline_version = <builder_version>+<config_hash[:12]>`).
Measurements are bound to a recorded build by snapshot, config, output checksum
and builder identity, so a result cannot silently read a stale artifact.
Snapshot ids embed a content digest, so the same id always means the same bytes
(`kpx snapshot verify`). Stack-merge SHA changes are mapped in
`docs/experiment-design-revisions.md`.

## Reproducing

Two virtual environments, because the builder (polars) and the harness (pandas)
cannot be imported together: `$BUILDER` is the kpubdata-builder environment at
`096d023`, `$KPX` is this one.

```bash
make install                                   # uv sync --extra dev --extra figures
$KPX -m kpx.cli snapshot verify <snapshot_id>  # after restoring snapshot bytes
bash scripts/canonical.sh                      # every non-timing result, 14 steps (~1 h)
$KPX scripts/canonical_manifest.py             # results/canonical_manifest.json
$KPX scripts/paper_tables.py                   # tables/
$KPX scripts/paper_figures.py                  # figures/
```

`canonical.sh` refuses to start on a dirty tree. Tables and figures refuse to
build if a result file no longer matches the manifest. The timing experiment is
frozen and is not part of `canonical.sh`; its procedure is in
[`scripts/README.md`](scripts/README.md).

## Harness design

| doc | fixes |
|---|---|
| [`runner-contract.md`](docs/runner-contract.md) | the `ConditionRunner.prepare` boundary: preparation is measured, the analysis is shared |
| [`monolithic-baseline.md`](docs/monolithic-baseline.md) | the baseline reuses the task's helpers and must reach the same result |
| [`code-metrics.md`](docs/code-metrics.md) | how LOC and transformation functions are counted; why steps are diagnostic |
| [`required-columns.md`](docs/required-columns.md) | which roles are `required` |
| [`rq1-transition-classification.md`](docs/rq1-transition-classification.md) | RQ1 transition-cause rules |
| [`statistics.md`](docs/statistics.md) | descriptive reporting of timing |
| [`storage-tradeoff.md`](docs/storage-tradeoff.md) | the controlled storage comparison |
| [`bike-source-generations.md`](docs/bike-source-generations.md), [`bike-generation-runs.md`](docs/bike-generation-runs.md) | bike generations and their runs |
| [`user-study-exclusion.md`](docs/user-study-exclusion.md) | why there is no user study |
| [`experiment-design-revisions.md`](docs/experiment-design-revisions.md) | every design change and why; final design and provenance |

## Development

```bash
make check       # ruff + mypy + pytest
```

CI also runs every script with `--help` in the harness environment.
