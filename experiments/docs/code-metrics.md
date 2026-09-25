# Measuring preparation code

RQ2 compares how much preparation code each condition needs before the shared
analysis can begin. This document fixes how that is measured. The rule was set
before any task was written, so it could not be adjusted once the numbers were
visible. It is the source of the paper's Construct Validity paragraph.

Results: `results/experiment_results.parquet` →
`tables/rq2_preparation.{csv,md}`.

## Why a single LOC number is not enough

Two failure modes make a bare line count worthless:

* **A moving boundary.** If what counts as "preparation" is decided after the
  results are in, `preprocessing_loc` measures the author's judgement.
* **Lines are not effort.** Four lines of dense pandas are not cheaper than
  eight readable ones, and a condition can always be compressed.

So three numbers are reported together, and the boundary is declared in advance.

| Metric | What it is | Role | Paper label |
| :--- | :--- | :--- | :--- |
| `preprocessing_loc` | effective lines of `prepare` and the private helpers it calls | **primary** | Preprocessing LOC |
| `function_count` | distinct named transformations the preparation invokes | **primary** | Transformation functions |
| `transformation_steps` | top-level `ctx.step(...)` blocks recorded at run time | diagnostic | Instrumented preparation stages |

Two kinds of number are reported together and argued from differently.

**Implementation effort** — `preprocessing_loc` and `function_count`. Both are
derived from the source by AST, so the author cannot move them by writing the
same work differently.

**Diagnostic only** — `transformation_steps` is reported but not argued from;
see [Why steps are diagnostic](#why-steps-are-diagnostic).

## Instrumentation is inside the count

The `with ctx.step(...)` statements that produce `transformation_steps` are
lines of `prepare`, so they are counted in `preprocessing_loc` as well. This was
not noticed when the boundary was declared.

It matters because the instrumentation is **not spread evenly**. There is one
line per transformation step, and step count is exactly what differs between
conditions — so the instrumentation inflates whichever condition does more
steps, which is the direction that flatters the layered path.

| task | condition | `preprocessing_loc` | `with ctx.step` lines | net |
| :--- | :--- | ---: | ---: | ---: |
| task01 | bronze | 20 | 7 | 13 |
| task01 | silver | 12 | 3 | 9 |
| task01 | gold | 2 | 0 | 2 |
| task01 | monolithic | 16 | 1 | 15 |
| task03 | bronze | 50 | 7 | 43 |
| task03 | silver | 34 | 4 | 30 |
| task03 | gold | 2 | 0 | 2 |
| task03 | monolithic | 46 | 1 | 45 |

Two consequences, both carried into the paper rather than corrected away:

* **Bronze → Silver still falls, by less.** 40% and 32% raw; 31% and 30% net.
* **Monolithic is not smaller than Bronze.** Raw LOC says it is (16 against 20,
  46 against 50); net of instrumentation it is larger (15 against 13, 45 against
  43). The claim that layering needs less preparation code than a monolithic
  script is therefore **not supported** by this measurement. What survives is
  the Bronze → Silver reduction.

The numbers in `tables/rq2_preparation` are left as measured. Subtracting the
instrumentation there would hide the instrument rather than report it, and the
net column is a subtraction any reader can check against this table.

Counting these lines was the right call for the declared boundary — they are
lines the condition's author wrote inside `prepare`. The error was not counting
them; it was arguing from the total without saying what was in it.

## Gold's two lines are a definition

`gold.prepare` is `return AnalysisInput(frame=ctx.load(...))`. Gold is
materialized in the analysis input's shape, so its preparation collapsing to a
single load is a restatement of that design, not a finding about layering. The
aggregation did not disappear; it moved to build time, which this measurement
does not cover. Read the Bronze → Silver column for the RQ2 claim, and read
Gold as the cost boundary it defines.

Execution cost is not measured here. It comes only from the timing experiment
(`scripts/_timing.py`, `results/timing_*`; see [statistics.md](statistics.md)).

## The preprocessing / analysis boundary

**Preparation is `ConditionRunner.prepare` and the private helpers it calls.
Everything else is analysis.**

The boundary is a method boundary, not a judgement. It was declared in the
runner contract before any condition was written, and it is the same boundary
for all four conditions.

```
task01_price_analysis/
├── transforms.py    # shared helpers — invoked, bodies not charged
├── analysis.py      # the analysis — never measured
├── bronze.py        # prepare() + private helpers  ← measured
├── silver.py        # prepare() + private helpers  ← measured
├── gold.py          # prepare() + private helpers  ← measured
└── monolithic.py    # prepare() + private helpers  ← measured
```

Starting at `prepare`, the **reference** graph is followed through module-private
functions and private methods of the runner class. Everything reachable that way
is counted.

References rather than calls, because the idiomatic way to apply a
transformation here never calls it syntactically:

```python
df["price_krw"] = df["거래금액"].map(parse_price)   # parse_price is passed, not called
```

Following call targets alone would miss most transformations in the codebase.

### What is not followed, and why

**Library access.** `df.groupby(...)`, `pd.to_datetime(...)`. Not code the
condition had to write; following it would measure pandas. Concretely, bare
names (`_normalize`, `parse_price`) and `self._helper` attributes are followed —
attributes of anything else are treated as library access. Names that resolve to
neither a shared transformation nor a private helper — locals, module aliases —
are dropped.

**Shared transformation helpers.** Using one of the task's `transforms` adds one
to `function_count`, but the helper's body is not charged to the condition.

This second rule is what keeps the conditions comparable. Every condition draws
on the same helper module, and the monolithic baseline is *required* to
(see [monolithic-baseline.md](monolithic-baseline.md)) — so charging helper
bodies would bill every condition for the same shared code and compress the
differences the RQ2 comparison is about. What differs between conditions is how much each one
has to *do* with those helpers before the analysis can start, and that is what
`prepare` contains.

The consequence is stated in the Results section rather than hidden: absolute
LOC figures here are smaller than a from-scratch script's would be, for every
condition including the baseline. The comparison is between conditions measured
the same way.

## Counting rules for LOC

Counted from the token stream rather than by matching text, so the rules hold
exactly rather than approximately:

* blank lines — **not counted**
* comment lines — **not counted**
* the function's docstring — **not counted**
* a statement spanning several physical lines — counted once per line it covers
* the `def` line and any decorators — **counted**; a signature is code

## Transformation steps

`transformation_steps` is not read out of the source. It is recorded by the
preparation code as it runs:

```python
with ctx.step("parse_price"):
    df["price_krw"] = df["거래금액"].map(parse_price)
```

Nested steps are not counted. See [runner-contract.md](runner-contract.md).

## Why steps are diagnostic

This metric was declared primary before the tasks were written. It is being
**demoted to diagnostic after the numbers were seen**, which this document's own
rule forbids doing to a measurement. The demotion is recorded here rather than
applied silently, and no recorded number changes: every condition keeps the step
count it produced.

The defect is that the rule does not determine the number. It permits a step to
bracket any amount of sub-work:

> A logical transformation such as `normalize_columns` stays one step however
> many sub-operations it brackets internally.

So the same preparation can be recorded as one step or as seven, and both comply.
Task 1 produced exactly that:

| Condition | `function_count` | `preprocessing_loc` | `transformation_steps` |
| :--- | ---: | ---: | ---: |
| bronze | 6 | 20 | 7 |
| monolithic | 6 | 16 | 1 |

Bronze and monolithic invoke **the same six transformation functions** — the
Baseline Bias convention requires it ([monolithic-baseline.md](monolithic-baseline.md)) —
and their line counts are close. Only the declared step count differs, by a
factor of seven, because the monolithic runner brackets its work in one block.
That is the bracketing the rule allows, not a misapplication of it.

A metric that the author sets by choosing where to put `with` statements cannot
carry a cross-condition claim about effort. The AST-derived metrics can, and they
say these two conditions cost about the same to write — which is the expected
result, since the baseline reuses the same helpers by design.

What the step record is still good for: a readable trace of what each
condition actually did (it also times each step, but those times are not
reported — execution cost comes only from the timing experiment). That is
what it was built for in the runner contract, and it stays.

**Not done, deliberately:** monolithic was not re-annotated into seven steps, and
it was not excluded from the table. Re-annotating would move a number in the
direction that favours our own hypothesis after seeing it; excluding one condition after seeing
its value is post-hoc selection. Reporting the number and declining to argue from
it is the change that does not touch the data.

This paragraph is the source of the corresponding note in Threats to Validity
(#25).

## Usage

```python
from kpx.metrics.code_metrics import measure_preparation, preparation_code_table
from kpx.tasks.task01_price_analysis import silver, transforms

metrics = measure_preparation(silver.Runner(), transforms=transforms, steps=recorder.step_count)
metrics.preprocessing_loc   # 12
metrics.function_count      # 3
metrics.measured            # ('prepare',)
metrics.transformations     # ('aggregate_by_district_month', 'price_per_m2', 'to_year_month')
```

`measured` and `transformations` are returned so that a reviewer can check
*what* was counted, not just how much. A condition whose `measured` list is
missing a helper is a measurement bug, and it should be visible without
re-deriving the call graph by hand.

## Threats to Validity — Construct Validity (draft)

> **Construct validity.** `preprocessing_loc` is intended to capture the cost of
> preparing data for analysis, and a line count can easily capture something
> else. We constrain it in three ways. First, the boundary between preparation
> and analysis is structural rather than retrospective: a condition implements
> `prepare`, the analysis is defined once per task and shared unchanged across
> conditions, and the measurement follows the call graph from `prepare` through
> private helpers only. The boundary was fixed in the runner contract before any
> condition was implemented and is identical for all four. Second, preparation
> is reported as three numbers rather than one — lines and distinct
> transformation functions, both derived from the source, and logical
> transformation steps recorded at run time as a diagnostic only, since their
> count depends on how a condition brackets its work. Third, calls into shared transformation
> helpers count toward the function count but their bodies are not charged to
> any condition, since every condition, the monolithic baseline included, draws
> on the same helpers; absolute line counts are therefore lower than a
> from-scratch implementation's, and only the ratios between conditions are
> interpreted. Lines are counted from the token stream, excluding blanks,
> comments and docstrings, identically for every condition.
