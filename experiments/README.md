# experiments — Medallion pipeline evaluation harness

This directory holds every piece of code that produces a number in the paper
*"An Empirical Evaluation of Medallion Data Pipelines for Korean Public Data"*.

It contains no transformation logic of its own. Bronze, Silver and Gold
artifacts are produced by [`kpubdata-builder`](https://github.com/yeongseon/kpubdata-builder);
this harness consumes them, measures the cost of consuming them, and records the
result.

## Layout

```
experiments/
├── src/kpx/              # the harness package
│   ├── contract.py       # condition-runner contract  ← read this first
│   ├── steps.py          # transformation step recording
│   ├── metrics/          # quality / code_metrics / runtime / reproducibility
│   └── tasks/            # task01_price_analysis … task04_bike
├── tests/
├── datasets/             # built dataset artifacts (git-ignored)
├── snapshots/            # frozen source snapshots + metadata
├── results/              # experiment_results.parquet (committed)
└── figures/              # generated figures (committed)
```

The paper plan sketches `metrics/` and `tasks/` as top-level directories. They
are subpackages of `kpx` instead, so that the harness is importable and
installable rather than a collection of loose scripts — `metrics/quality.py` in
the plan is `src/kpx/metrics/quality.py` here.

`datasets/` is ignored by git because the artifacts are large and republished on
Hugging Face. `results/` and `figures/` are **not** ignored: they are what makes
the benchmark reproducible for a reader who does not rerun the pipeline.

## Conditions

Every task is run under four conditions:

| Condition | Reads | Description |
| :--- | :--- | :--- |
| `bronze` | Bronze | minimally parsed source records; original Korean column names, string types, comma-separated amounts, split year/month/day |
| `silver` | Silver | canonical normalized dataset; typed, renamed, deduplicated, schema-validated |
| `gold` | Gold | task-oriented reusable dataset; pre-aggregated but **not** the analytical answer |
| `monolithic` | Bronze | baseline: one pass from Bronze to the analysis input, persisting no intermediate |

`monolithic` deliberately reads Bronze. It is the baseline that must reproduce
the whole pipeline itself, so it starts from the same minimally parsed source
the Medallion path starts from.

## The runner contract

See [`docs/runner-contract.md`](docs/runner-contract.md) for the full rationale.
The short version:

```python
class ConditionRunner(Protocol):
    TASK: str
    CONDITION: Condition

    def prepare(self, ctx: RunContext) -> AnalysisInput: ...
```

A condition implements `prepare` and nothing else. The analysis is defined once
per task and handed to every condition unchanged.

Two measurement decisions follow from this and are the reason the contract is
shaped this way:

* **`preprocessing_loc` is what `prepare` costs.** The boundary between
  "preparation" and "analysis" is a method boundary, not a judgement call made
  after the numbers are in (Construct Validity).
* **The analysis is held constant.** Conditions differ only in how they reach
  `AnalysisInput`, so a difference in the result is attributable to preparation
  (Internal Validity).

Transformation steps are recorded as they run rather than counted by hand:

```python
def prepare(self, ctx: RunContext) -> AnalysisInput:
    df = ctx.load("trades")
    with ctx.step("parse_price"):
        df["price_krw"] = df["거래금액"].map(parse_price)
    with ctx.step("parse_deal_date"):
        df["deal_date"] = parse_deal_date(df["계약년월"], df["계약일"])
    return AnalysisInput(frame=df)
```

`ctx.step` is a no-op when no recorder is attached, so preparation code can be
exercised in a plain unit test without building a whole run.

## Snapshots

Every run is pinned to a `snapshot_id`, and the id embeds the content digest:

```
seoul-apartment-trades/20260315-4f2a91c0d3b7
                       ^date    ^digest prefix
```

Two snapshots with the same id necessarily hold the same bytes. R1 can therefore
*check* "identical source" rather than assume it, and R2 can say which of
T1/T2/T3 a build consumed. The date prefix keeps ids readable and sortable,
which matters because R2 compares snapshots over time.

The digest is platform-independent. Paths go into the manifest that is hashed,
so they are spelled POSIX-style and NFC-normalized rather than however the local
filesystem spells them — otherwise a reader restoring the published data on
another OS would compute a different id for the same bytes.

```
snapshots/<dataset>/<date>-<digest>/
├── metadata.json     # the Snapshot record; committed
└── source/           # the frozen bytes; git-ignored, republished separately
```

Only `metadata.json` is committed. The data itself is published on Hugging Face;
a reader restores `source/` and `kpx snapshot verify` confirms they restored the
right thing.

```bash
kpx snapshot list                  # registered snapshots, oldest first
kpx snapshot show <snapshot_id>    # the citation block quoted in the paper
kpx snapshot verify                # re-digest stored bytes; exit 1 on drift
```

`verify` runs before every reproducibility build. A snapshot that has drifted
invalidates R1's premise, so it has to break the build rather than be measured
silently.

A snapshot records its data's own `period` separately from `retrieved_at`: a
pull made in March 2026 may cover 2020–2024, and Table 1 needs both.

## Build provenance

RQ4 needs a precise version of "deterministic build", so provenance separates
two things that are easy to conflate:

| | |
| :--- | :--- |
| the **recipe** | snapshot, pipeline version, transformation config, upstream layer — its hash is the `build_id` |
| the **result** | the bytes the recipe produced — its hash is the `output_checksum` |

R1 then reads: *the same `build_id` must give the same `output_checksum`*. R2
holds the recipe constant except `snapshot_id` and asks whether the pipeline's
contract survives — a different `output_checksum` there is expected, a broken
schema is not.

The captured environment (Python version, platform, library versions)
deliberately does **not** feed the `build_id`. If it did, every machine would
compute a different id and R1 could never compare a rebuild across machines —
which is exactly the comparison a reader reproducing the paper makes.
`Environment.differences()` answers the first question a mismatched checksum
raises: did the environment move?

Provenance carries lineage, so a schema breakage found in R2 can be attributed
to the layer that introduced it:

```bash
kpx build list --layer silver
kpx build lineage <build_id>     # bronze → silver → gold
```

```
datasets/<dataset>/<layer>/<build_id>/
├── provenance.json
└── …the artifact files…
```

Keying the directory by `build_id` means two builds of the same recipe land in
the same place, so an R1 repeat is a comparison rather than an accumulation of
directories.

## Development

```bash
make install     # uv sync --extra dev --extra analysis --extra figures
make check       # lint + typecheck + test
```

Individually: `make lint`, `make format`, `make typecheck`, `make test`.

## Reproducing the experiments

The full procedure is fixed by the paper's methodology section and is filled in
as each experiment lands:

1. **Restore a snapshot.** Every run is pinned to a `snapshot_id`; snapshot
   metadata lives in `snapshots/`.
2. **Build the layers.** `kpubdata-builder` produces Bronze, Silver and Gold
   from the snapshot at a recorded `pipeline_version`.
3. **Run the tasks.** Each task runs under all four conditions; model tasks
   repeat over 5 random seeds and runtime measurement uses 1 warm-up plus 5
   measured runs.
4. **Collect results.** Every run appends one row to
   `results/experiment_results.parquet`.
5. **Generate tables and figures.** Tables 1–5 and Figures 1–5 are regenerated
   from that file alone.

A run is fully described by `(task, condition, snapshot_id, pipeline_version,
seed)`. Anything a runner needs comes from `RunContext`, never from module-level
state, so a row in the results file can be replayed.
