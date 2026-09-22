# Measuring analytical effort

RQ2 asks how much work a condition costs before analysis can begin, and H2
predicts Bronze > Silver > Gold. This document fixes how that is measured,
before any task is written, so the rule cannot be adjusted once the numbers are
visible. It is the source of the paper's Construct Validity paragraph.

## Why a single LOC number is not enough

Two failure modes make a bare line count worthless:

* **A moving boundary.** If what counts as "preparation" is decided after the
  results are in, `preprocessing_loc` measures the author's judgement.
* **Lines are not effort.** Four lines of dense pandas are not cheaper than
  eight readable ones, and a condition can always be compressed.

So four numbers are reported together, and the boundary is declared in advance.

| Metric | What it is | Role |
| :--- | :--- | :--- |
| `preprocessing_loc` | effective lines of `prepare` and the private helpers it calls | primary |
| `function_count` | distinct named transformations the preparation invokes | primary |
| `transformation_steps` | top-level `ctx.step(...)` blocks recorded at run time | primary |
| `cyclomatic_complexity` | summed over the measured functions | secondary |

`cyclomatic_complexity` is reported but not argued from. It is there so a reader
can see that a condition with fewer lines did not buy them with denser control
flow.

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
differences H2 is about. What differs between conditions is how much each one
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

A loop that normalizes twelve columns is one logical transformation however it
is written, and only a runtime record gets that right. Nested steps are not
counted, so the number reflects logical transformations rather than
implementation detail. See [runner-contract.md](runner-contract.md).

## Usage

```python
from kpx.metrics.code_metrics import measure_preparation, table3
from kpx.tasks.task01_price_analysis import silver, transforms

metrics = measure_preparation(silver.Runner(), transforms=transforms, steps=recorder.step_count)
metrics.preprocessing_loc   # 18
metrics.function_count      # 3
metrics.measured            # ('prepare', '_normalize_columns')
metrics.transformations     # ('parse_deal_date', 'parse_price')
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
> condition was implemented and is identical for all four. Second, effort is
> reported as four numbers rather than one — lines, distinct transformation
> functions, logical transformation steps recorded at run time, and cyclomatic
> complexity as a secondary indicator — so that a condition cannot appear
> cheaper merely by being denser. Third, calls into shared transformation
> helpers count toward the function count but their bodies are not charged to
> any condition, since every condition, the monolithic baseline included, draws
> on the same helpers; absolute line counts are therefore lower than a
> from-scratch implementation's, and only the ratios between conditions are
> interpreted. Lines are counted from the token stream, excluding blanks,
> comments and docstrings, identically for every condition.
