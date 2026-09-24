# The condition-runner contract

## Why there is a contract at all

The paper measures how much preparation work moves out of the analysis when it
reads Bronze, Silver or Gold (RQ2), under the condition that every route reaches
the **same** analysis result — an equivalence gate, not a claim that one layer
is more accurate. Both are easy to fake by accident:

* Report LOC for a script that mixes preparation and analysis, and
  `preprocessing_loc` measures whatever the author felt like calling
  preparation.
* Let each condition write its own analysis, and the Gold condition can quietly
  become a different, easier analysis.

Rather than promise in prose that neither happened, the harness makes both
structurally impossible.

## The interface

```python
Condition = Literal["bronze", "silver", "gold", "monolithic"]

class ConditionRunner(Protocol):
    TASK: str
    CONDITION: Condition

    def prepare(self, ctx: RunContext) -> AnalysisInput: ...
```

A condition module defines exactly one runner and implements exactly one method.

### `prepare` is the measured surface

Everything `prepare` and its module-private helpers do is data preparation.
`kpx.metrics.code_metrics` measures that surface and nothing else. A condition
that computes part of the analytical result inside `prepare` is not a cheaper
condition, it is a broken one — which is why `AnalysisInput.require_columns`
exists: the shared analysis declares the shape it needs, and a condition that
hands over the wrong shape fails loudly rather than producing a different
number.

### The analysis is shared, not per condition

A task package is laid out as:

```
task01_price_analysis/
├── analysis.py      # analyze(ctx, prepared) -> AnalysisOutput   ← one copy
├── bronze.py        # prepare() only
├── silver.py        # prepare() only
├── gold.py          # prepare() only
└── monolithic.py    # prepare() only
```

`analysis.py` is imported by the runner, not reimplemented by it. Four
conditions, one analysis.

## Why `monolithic` is not special-cased

The Baseline Bias threat is that a deliberately clumsy baseline manufactures the
result. The harness removes the opportunity:

* `monolithic` is an ordinary `ConditionRunner`. It gets no different treatment
  from the runner, the timer, or the metrics.
* `condition_layer("monolithic") == "bronze"` — it starts from the same input as
  the Medallion path rather than from a handicapped one.
* It reuses the same transformation helpers as the Silver and Gold
  transformations. It differs in *structure* — one pass, no persisted
  intermediate — not in transformation semantics.

What is being compared is a structured, reusable pipeline against a monolithic
transformation. It is not a comparison of transformation quality.

## Counting transformation steps

`transformation_steps` is recorded by the preparation code as it runs:

```python
with ctx.step("normalize_district"):
    ...
```

This yields a per-step time breakdown and a readable trace of what each condition
actually had to do — the qualitative material for the Results section.

Steps may nest; only top-level steps are counted. A step may bracket any amount
of sub-work: `normalize_columns` stays one step however many sub-operations it
performs internally.

**The count is therefore declared, not derived.** The same preparation can be
recorded as one step or as several, and both follow this rule. That makes the
number useful for reading a single condition's trace and useless for comparing
effort across conditions, so it is a diagnostic rather than a primary metric —
see [code-metrics.md](code-metrics.md#why-steps-are-diagnostic). Cross-condition
effort is argued from `preprocessing_loc` and `function_count`, which are derived
from the source.

Recording survives failure: a step that raises is still recorded, so a condition
that fails partway reports how far it got.

## `RunContext` and replayability

A runner takes every input from `RunContext`:

| Field | Purpose |
| :--- | :--- |
| `task`, `condition`, `run_id` | identity of the run |
| `snapshot_id` | which frozen source this run used |
| `pipeline_version` | which builder version produced the layers |
| `datasets` | a `DatasetResolver`; runners never hard-code a path |
| `seed` | random seed, for the model tasks |
| `params` | task-specific parameters |
| `recorder` | step recorder, or `None` outside a measured run |

No module-level state. A run is fully described by `(task, condition,
snapshot_id, pipeline_version, seed)`, which is exactly the key the result
schema records — so a row in the results file can be replayed.

`DatasetResolver` is a protocol rather than a concrete loader so tests can
substitute fixtures for real snapshots, and so the dataset layer (issue #7) can
change how artifacts are stored without touching task code.
