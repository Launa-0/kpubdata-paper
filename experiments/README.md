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
│   ├── baseline.py       # monolithic baseline equivalence checks
│   ├── snapshot.py       # frozen source snapshots
│   ├── pipeline.py       # pipeline version: the code + the config
│   ├── provenance.py     # build recipe, result digest, lineage
│   ├── results.py        # result schema and store
│   ├── metrics/          # quality / code_metrics / runtime / reproducibility
│   └── tasks/            # task01_price_analysis … task04_bike
├── tests/
├── datasets/             # built dataset artifacts (bytes git-ignored, provenance committed)
├── snapshots/            # frozen source snapshots + metadata
├── results/              # experiment_results.parquet (committed)
└── figures/              # generated figures (committed)
```

The paper plan sketches `metrics/` and `tasks/` as top-level directories. They
are subpackages of `kpx` instead, so that the harness is importable and
installable rather than a collection of loose scripts — `metrics/quality.py` in
the plan is `src/kpx/metrics/quality.py` here.

A built dataset is split the same way a snapshot is: the artifact bytes under
`datasets/<dataset>/<layer>/<build_id>/data/` are ignored by git because they are
large and republished on Hugging Face, while the `provenance.json` beside them is
committed. `results/` and `figures/` are **not** ignored either. All three are what
makes the benchmark reproducible for a reader who does not rerun the pipeline —
without the committed provenance there is no `build_id` or `output_checksum` for
that reader to compare R1 against, and no lineage chain for R2 to walk.

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

## The monolithic baseline

`monolithic` is the control condition, and the claim it supports is narrow: a
structured, reusable pipeline against a single-pass transformation — **not** a
comparison of transformation quality. See
[`docs/monolithic-baseline.md`](docs/monolithic-baseline.md) for the full
convention and the Baseline Bias paragraph it feeds. The rules:

* **No special-casing.** `monolithic` is an ordinary `ConditionRunner`, reads
  Bronze like the Medallion path does, and no code in the harness branches on
  it.
* **It imports the task's transformations, it does not reimplement them.** Each
  task keeps its helpers in `transforms.py`; `monolithic.py` imports from it and
  defines only its own orchestration. Reuse makes the baseline slightly more
  capable than a realistic one-off script — a bias against our own hypothesis,
  which is the safer error.
* **Equivalence is asserted, not claimed.** A baseline that reproduces the whole
  pipeline must reach the same `AnalysisInput` as the full Medallion path.

```python
report = check_baseline_equivalence(
    gold.Runner(), monolithic.Runner(), ctx, key=["district_code", "year_month"]
)
report.raise_for_status()
```

The check is applied to `monolithic` only. `bronze`, `silver` and `gold` are
allowed to disagree with each other — they read layers of differing quality, and
that difference is what RQ3 measures.

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

## Results

Every run appends one row to `results/experiment_results.parquet`, and Tables
1–5 and Figures 1–5 are regenerated from that file alone. A reader who never
runs the pipeline sees only this file, so it has to be trustworthy by itself.

```python
store = default_store()
store.append(ResultRow(
    run_id="task01/silver/seed0/r0",
    task="task01",
    dataset="seoul-apartment-trades",
    condition="silver",
    source_snapshot="seoul-apartment-trades/20260315-4f2a91c0d3b7",
    pipeline_version="0.1.0",
    rows=234_114, runtime_seconds=1.25,
    preprocessing_loc=18, function_count=3, transformation_steps=4,
    output_hash=output_digest(result),
))

store.query(task="task01")                    # rows for one task; failures hidden
store.by_condition("runtime_seconds")         # the task × condition table
```

A CSV mirror is written beside the parquet on every append: parquet is
authoritative, the CSV is what gives a committed result a readable diff.

### Missing-value rules

A metric that does not apply must be **absent, not zero** — `0.0` enters a mean,
missing does not. Validation therefore distinguishes three requirement levels:

| Level | Fields | Rule |
| :--- | :--- | :--- |
| `identity` | `run_id`, `task`, `dataset`, `condition`, `seed`, `source_snapshot`, `pipeline_version`, `status` | always present and non-null |
| `measured` | `rows`, `runtime_seconds`, `preprocessing_loc`, `function_count`, `transformation_steps`, `output_hash` | non-null whenever `status == "ok"` |
| `optional` | `peak_memory_mb`, `missing_rate`, `duplicate_rate`, `schema_validity`, `join_matching_rate`, `mae`, `rmse` | may be missing — not applicable to this task, or not measurable here |

`mae`/`rmse` are task02's, `join_matching_rate` is task03's; `peak_memory_mb` is
optional because not every platform can measure it.

A failed run is still recorded, as `status="failed"` with whatever was measured
before it failed. Dropping failures would make the results file describe a more
successful experiment than the one that was run — and `query` hides them by
default so they cannot reach a figure by accident.

`seed` is in the schema although the plan's field list omits it: a run is keyed
by `(task, condition, snapshot_id, pipeline_version, seed)`, and task02 runs
five seeds per condition, which would otherwise be five indistinguishable rows.

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

### Builds are counted here, runs are counted in the results file

A build is not a run. R1 repeats a build and R2 repeats it against a moving
snapshot; neither has a `task`, a `condition` or a `seed`, and all three are
identity fields in the result schema. So builds are counted in the provenance
store and runs in `experiment_results.parquet`, and everything R1 and R2 measure
is already a provenance field:

| measurement | field |
| :--- | :--- |
| build success rate (R1, R2) | `status` |
| output equality (R1) | `output_checksum` |
| row loss (R1, R2) | `row_count` |
| schema compatibility (R1, R2) | `columns` |
| storage amplification | `output_size_bytes` |
| breakage attribution (R2) | `lineage()` |

The two stores keep separate `status` vocabularies on purpose:

| | values | means |
| :--- | :--- | :--- |
| `Provenance.status` | open; `ok`, `schema_breakage`, … | how the **build** ended |
| result schema `status` | closed; `ok`, `failed`, `skipped` | how the **run** ended |

R2 reports *which* kind of breakage occurred, so collapsing `schema_breakage`
into `failed` would throw away its finding. They never have to be reconciled
because `status` does not cross between them — `Provenance.run_fields` carries
only `source_snapshot` and `pipeline_version`, the two fields that say which
build a run read.

`rows` and `output_hash` do not cross either, and for a sharper reason: the
provenance record and the result schema use those names for different things.
A layer's `row_count` is not the run's `rows` — the result schema means the rows
in the *prepared analysis input*, and filtering rows is part of what preparation
costs, so handing over the layer's count would erase the between-condition
difference Table 4 exists to show. A layer's `output_checksum` is not the run's
`output_hash` either: one is build determinism, the other analysis determinism,
and `results.output_digest()` computes the second.

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
├── provenance.json     # the record; committed
└── data/               # the artifact bytes; git-ignored, republished separately
```

The record sits outside `data/` rather than beside the artifact files, because
git cannot rescue an individual file back out of a directory it ignores. It is
the same shape as `snapshots/`, for the same reason.

Keying the directory by `build_id` means two builds of the same recipe land in
the same place, so an R1 repeat is a comparison rather than an accumulation of
directories.

## Pipeline version

`BuildInputs.pipeline_version` is one citable string, and this is what produces
it:

```
pipeline_version = <builder_version>+<config_hash[:12]>
                   ^ the code           ^ the configuration
```

It moves if either half moves. The component versions are kept beside it,
because a reader debugging a mismatch needs to know *which* half moved.

The config hash is taken over canonical JSON: keys sorted, so a config assembled
in another order hashes the same, and `Path` values written POSIX-style, so a
config naming a directory does not hash differently on Windows — the same defect
that made snapshot ids platform-dependent, reached through another door. `NaN`
is refused rather than hashed.

```python
assert_same_pipeline(builds)   # R2's precondition, checked rather than assumed
```

R2 varies the source across T1/T2/T3 and concludes the pipeline is stable under
that variation. That only follows if the pipeline itself did not move.

**What the builder records today.** `kpubdata-builder`'s `BuildManifest` carries
`build_id`, timings, inputs, outputs, warnings, errors and `row_counts` — and no
version fields at all. The package defines `__version__` but never writes it
into the manifest. So `from_build_manifest` takes the versions from its caller,
else from a `build_environment` object if a future manifest grows one, else
leaves them `unknown`; `PipelineVersion.is_complete` says which happened. A
version column reading `unknown` is honest, and a guessed one would silently
weaken every claim resting on it. Teaching the builder to stamp its own version
belongs with the Bronze export work (issue #2).

The harness never imports `kpubdata_builder`. Manifests are consumed as plain
data, which is what lets a reader verify a published artifact without installing
the builder.

## Measuring analytical effort

RQ2 asks what a condition costs to prepare data with. See
[`docs/code-metrics.md`](docs/code-metrics.md) for the rules and the Construct
Validity draft they feed.

```python
metrics = measure_preparation(silver.Runner(), transforms=transforms, steps=recorder.step_count)
metrics.preprocessing_loc, metrics.function_count, metrics.measured
```

**Preparation is `prepare` and the private helpers it references. Everything
else is analysis.** A method boundary, declared in the contract before any
condition was written and identical for all four, rather than a judgement made
once the numbers are visible.

Four numbers, not one, because lines alone are not effort: `preprocessing_loc`,
`function_count`, `transformation_steps` (recorded at run time), and
`cyclomatic_complexity` as a secondary indicator — reported so a reader can see
that a condition with fewer lines did not buy them with denser control flow.

Two things are deliberately left out of the line count. **Library access**
(`df.groupby`, `pd.to_datetime`) is not code the condition had to write.
**Shared transformation helpers** add to `function_count` when used, but their
bodies are not charged to any condition — every condition draws on the same
`transforms.py`, the monolithic baseline is required to, and billing all of them
for the same shared code would compress exactly the difference H2 is about.

References, not calls: `df["거래금액"].map(parse_price)` never calls
`parse_price` syntactically, and that is how transformations are normally
applied here.

`measured` and `transformations` are returned alongside the totals so a reviewer
can check *what* was counted without re-deriving the graph by hand.
## Measuring runtime and memory

The protocol is fixed for every task, not chosen per task:

| | |
| :--- | :--- |
| warm-up | 1 run, discarded |
| measurement | 5 runs, all kept |
| reported | **median** into `runtime_seconds`, with mean and stdev beside it |

```python
measurement = measure(lambda: runner.prepare(ctx))
measurement.summary()   # 'median 1.243s ± 0.031 over 5 runs, peak +212.4 MiB'
measurement.result      # what the last measured run returned
```

**The warm-up** exists because the first run pays for imports, lazily-built
pandas machinery and a cold page cache. That cost is paid once per session, not
once per analysis, so charging it to whichever condition ran first would rank
conditions by the order they happened to run in.

**The median** is reported because five runs on a shared machine will contain
the occasional outlier from whatever else the OS decided to do. Mean and stdev
are reported beside it so a reader can see how noisy the measurement was rather
than trust that it was not.

**Garbage is collected before each run, but collection stays enabled.** Left
alone, run *n* pays to collect run *n-1*'s garbage. Disabling the collector —
what `timeit` does — would measure something no real run experiences.

**Peak memory** is sampled from the process's RSS in a background thread and
reported as the high-water mark *above the baseline taken just before the run*;
the absolute figure is dominated by the interpreter, not by the condition. It is
a secondary figure: CPython does not reliably return freed memory to the OS, so
a later run in the same process starts from a higher baseline and its delta
under-reports. Conditions are not ranked on it alone.

### The environment

Runtime is comparable only within one environment, so the artifact ships the one
it was measured in:

```bash
kpx env             # the Methodology block
kpx env --json      # results/environment.json
```

A library that is not installed is omitted rather than recorded as unknown —
"scipy: not installed" in an environment table tells a reader nothing.

## Measuring data quality

H1's six metrics, one interface applied unchanged to Bronze and Silver. The hard
part is not computing rates — it is making them compare the same thing, when
Bronze holds `"120,000"` in `거래금액` and Silver holds `1200000000` in
`price_krw`. A `QualitySpec` states, in one layer's vocabulary, which column
plays which role and how a value in it is read; everything else is identical.

```python
spec = QualitySpec(
    columns=(
        ColumnSpec("거래금액", role="price", interpret=parse_price, minimum=0),
        ColumnSpec("전용면적", role="area", minimum=0),
        ColumnSpec("법정동시군구코드", role="district_code", kind="code"),
    ),
    valid_codes=SEOUL_DISTRICT_CODES,
)
report = measure_quality(bronze, spec, layer="bronze")
table2({"bronze": report, "silver": silver_report})
figure3_data({"bronze": report, "silver": silver_report})
```

| Metric | Definition |
| :--- | :--- |
| `type_consistency` | values that read as their declared type / values present |
| `missing_rate` | missing cells / cells, over required columns |
| `duplicate_rate` | duplicate records / records |
| `schema_conformance` | records where every required column is present, readable and in bounds |
| `code_validity` | code values found in the reference code list |
| `parsing_failure_rate` | records with at least one present-but-unreadable required value |

**Missing and unreadable are counted separately** throughout. An absent value
and a corrupt one are different defects, and collapsing them would let a layer
trade one for the other silently.

### Two ways this could manufacture H1

**Reading Bronze naively.** `pd.to_numeric("120,000")` fails, and counting that
as a parsing failure would measure how hostile we chose to be to Bronze rather
than anything about the data. A Bronze spec passes the same interpretation
functions the Silver build uses — the task's `transforms` helpers — so Bronze is
credited with everything the pipeline can actually read.

**Improving a rate by dropping rows.** A Silver build that deletes null rows
reports a better missing rate for a reason unrelated to standardization. So
missing rate is reported **per required column** as well as overall, and Table 2
prints each layer's **row count in the same table** — a rate bought by dropping
rows is visible at the same glance as the rate.

`code_validity` is `None` when no reference code list is given, rather than
falling back to a five-digit regex: that would accept `99999`, so it measures
format, not validity.

Table 2's `Improvement` column is signed so **positive always means better**,
whichever direction the underlying metric runs.
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
