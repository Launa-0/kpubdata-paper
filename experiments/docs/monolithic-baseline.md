# The monolithic baseline

## What is being compared

The `monolithic` condition is the control for RQ2 (analytical effort) and RQ4
(reproducibility). It transforms Bronze into the analysis input in a single
pass, persisting no intermediate dataset:

```
Source → clean → normalize → join → aggregate → analysis
```

The claim it supports is narrow and worth stating precisely:

* ✅ a **structured, reusable** pipeline against a **single-pass**
  transformation
* ❌ **not** a comparison of transformation quality

Medallion is not claimed to clean data better than a monolithic script. It is
claimed to make the *next* analysis cheaper and the rebuild more deterministic.
Every rule below exists to keep the first claim from quietly borrowing evidence
from the second.

## The Baseline Bias threat

A baseline written after the Medallion path, by authors who already know which
direction the result is supposed to point, can manufacture that result without
anyone intending it to. Parse dates with a slower helper, skip an index, drop
the deduplication — and Medallion "wins".

Prose asserting that this did not happen is not evidence. Three things make it
structural instead.

### 1. The baseline is not special-cased

`monolithic` is an ordinary `ConditionRunner`. It implements `prepare` and
nothing else, is handed the same `RunContext`, and is measured by the same
timer and the same code-metrics pass as every other condition. There is no
branch anywhere in the harness that reads `if condition == "monolithic"`.

`condition_layer("monolithic") == "bronze"`: the baseline starts from the same
minimally parsed source the Medallion path starts from, not from a handicapped
input.

### 2. The baseline reuses the shared transformation helpers

**Decision: reuse, do not inline.**

Each task package exposes its transformation helpers in one module:

```
task01_price_analysis/
├── transforms.py    # parse_price, parse_deal_date, normalize_district, …
├── analysis.py      # analyze(ctx, prepared) -> AnalysisOutput
├── bronze.py        # prepare() only
├── silver.py
├── gold.py
└── monolithic.py    # imports transforms.py; no transformation of its own
```

`monolithic.py` imports from `transforms.py`. It may define its own
*orchestration* helpers — sequencing, intermediate frames, its own plumbing —
and those count toward its preparation cost, which is what RQ2 measures. It may
not define its own `parse_price`.

`kpx.baseline.assert_reuses_transforms` enforces this by parsing the baseline
module and failing if it defines a name the shared module already exports.

**Why reuse rather than inlining equivalent logic.** Both options are
defensible and both are biased; they are biased in opposite directions.

| | Inline equivalent logic | Import the shared helpers |
| :--- | :--- | :--- |
| Realism | closer to a real one-off script | more favourable than reality |
| Equal semantics | argued, per function | guaranteed by construction |
| Failure mode | a difference in the numbers is unattributable | the baseline is flattered |

We take the second. A difference that turns out to be an accidental divergence
between two copies of `parse_price` is unfalsifiable after the fact and would
compromise every number in the paper. A baseline that is *slightly better than
realistic* has a known sign: it weakens our own hypothesis. RQ2 measures the
structure of preparation — how many steps, how many functions, how much code a
condition needs before analysis can begin — and importing a tested helper does
not flatter that structure. If H2 holds against a flattered baseline, it holds.

This is reported in the paper rather than left in the repository: the baseline's
`preprocessing_loc` excludes helper bodies it imports, exactly as the Medallion
conditions' does, and the Results section says so.

### 3. Same input, same output — asserted, not asserted-to

A baseline that reproduces the whole pipeline must arrive at the same
`AnalysisInput` as the full Medallion path. Every task is required to assert it:

```python
def test_monolithic_matches_the_medallion_path() -> None:
    report = check_baseline_equivalence(
        gold.Runner(), monolithic.Runner(), ctx, key=["district_code", "year_month"]
    )
    report.raise_for_status()
```

`check_baseline_equivalence` runs both `prepare` methods against one context,
normalizes away column order and row order, and reports every remaining
disagreement — missing columns, row-count drift, dtype changes, differing
values with a sample. Tolerances default to exact.

A task that needs `rtol` has to justify it in the paper. The only defensible
reason is that an aggregation legitimately sums in a different order, and the
tolerance must sit far below the effect being reported.

**This check applies to `monolithic` only**, because it is the one condition
claiming to do the Medallion conditions' work by another route. The other
conditions are not exempt from agreeing: every condition gets the same
transformation semantics, and each task's tests and the runs' `output_hash`
hold all four to the same analysis result. That agreement is a validity gate
for RQ2, not a finding, and the pairs carry different weight:

| Pair | Why they agree |
|---|---|
| Bronze ↔ Silver | **independent** — the harness's parsers against the builder's casts, on the same bytes |
| Silver ↔ Gold | by construction — Gold is built with the same functions |
| Bronze ↔ Monolithic | by construction — same helpers in the same order |

## Checklist for a new task

A task is not finished until all four hold:

- [ ] `monolithic.py` imports its transformations from `transforms.py`
- [ ] `assert_reuses_transforms(monolithic, transforms)` passes
- [ ] `check_baseline_equivalence(gold.Runner(), monolithic.Runner(), ctx)` passes with an explicit `key`
- [ ] any non-zero `rtol`/`atol` is recorded in the task's docstring with its reason

## Threats to Validity — Baseline Bias (draft)

> **Baseline bias.** The monolithic baseline is implemented by the same authors
> as the Medallion pipeline, after it, and with knowledge of the hypothesis. A
> baseline made needlessly slow or verbose would produce the reported effect
> without any property of the Medallion design being responsible for it. We
> constrain this in three ways. First, the baseline is not privileged or
> penalized by the harness: it implements the same `ConditionRunner` interface,
> receives the same `RunContext`, reads the same Bronze input as the Medallion
> path, and is measured by the same instrumentation; no code path in the harness
> distinguishes it. Second, both paths use identical transformation semantics by
> construction — the baseline imports the same transformation helpers the Silver
> and Gold transformations use, and a static check fails the build if it
> redefines one. Third, equivalence of output is asserted rather than claimed:
> for every task, the baseline and the full Medallion path must produce the same
> analysis input, compared column by column at exact tolerance, with any
> relaxation reported. The residual threat is that importing tested helpers
> makes the baseline *more* capable than a one-off script a practitioner would
> realistically write, so the reported effort reduction is, if anything,
> conservative. We consider an optimistic baseline the safer error, since it
> biases against our own hypothesis. We do not claim that Medallion produces
> better transformations than a monolithic pipeline could; the comparison is
> between pipeline *structures* holding transformation semantics fixed.
