# Statistical analysis

Every hypothesis in the paper compares conditions of the **same** task on the
**same** snapshot, so the comparisons are paired. This document fixes how they
are tested, before any result exists — for the same reason the preprocessing
boundary was fixed before any condition was written. A test chosen after seeing
the numbers is a test chosen to produce them.

## The decision rule

Applied identically to every metric and every pair of conditions:

1. **Pair on `seed`.** Same task, same snapshot, same seed, differing only in
   condition. A seed present for one condition and not the other is dropped and
   counted in `unpaired` — never matched up by position, which would silently
   compare different runs.
2. **Fewer than two pairs → no test.** Report the raw values and stop.
3. **Two pairs, or differences that are constant up to float noise → Wilcoxon.**
   Shapiro–Wilk needs three points, and on a barely-varying sample it returns a
   number scipy itself warns is unreliable.
4. **Otherwise Shapiro–Wilk on the paired differences.** `p >= 0.05` → paired
   t-test; below → Wilcoxon signed-rank.

Which branch each comparison took is recorded on it (`test`, `normality_p`), so
a reader can check the rule was followed rather than take its existence on
faith.

## The sample size the design runs into

4 conditions × 5 seeds. At **n = 5 a two-sided Wilcoxon signed-rank test cannot
return p < 0.05.** There are only 2⁵ sign assignments, so its smallest
attainable p-value is 2/2⁵ = 0.0625.

| n | smallest attainable two-sided p | can reach 0.05 |
| ---: | ---: | :--- |
| 3 | 0.2500 | no |
| 4 | 0.1250 | no |
| **5** | **0.0625** | **no** |
| 6 | 0.0312 | yes |
| 7 | 0.0156 | yes |

The paired t-test has no such floor. The same five pairs that Wilcoxon caps at
0.0625 reach p ≈ 0.013 through it.

So at this sample size **whether a comparison can attain significance at all is
decided by the normality test, not by the size of the effect.** Skewed
differences route to Wilcoxon and are capped; well-behaved ones route to t and
are not. That is a property of the design, not of the pipeline being measured.

Three consequences, all of them acted on rather than noted:

* `Comparison.significance_reachable` is computed, not left to the reader, and
  `summary_table` carries the column. A comparison reporting `p = 0.0625` and
  nothing else reads as a null result when it is the strongest statement that
  test can make.
* Every comparison carries **Cohen's dₙ**, the **rank-biserial correlation**, a
  **confidence interval** on the mean difference, and the **raw paired values**.
  The paper leads with these.
* **Six seeds instead of five** lifts the floor below 0.05. That is the cheapest
  available fix and belongs in the task design (#14), not in the analysis.

## Effect sizes

| | |
| :--- | :--- |
| Cohen's dₙ | mean difference in units of its own spread; `None` when the differences are constant, where it is undefined rather than infinite |
| rank-biserial | share of signed rank mass pointing one way, −1 to 1; the Wilcoxon-appropriate companion |

Both are reported for every comparison regardless of which test ran, so a
reader can compare across comparisons that took different branches.

## Multiple comparisons

Four conditions give three comparisons against the baseline per metric.
`holm(comparisons)` applies the Holm–Bonferroni step-down correction within a
family; the family is the caller's to define and the natural one is a single
metric within a single task. `Comparison.significant` reads the adjusted
p-value when one is present.

## Usage

```python
from kpx.stats import compare_conditions, holm, summary_table

comparisons = holm(compare_conditions(results, "runtime_seconds", task="task02"))
summary_table(comparisons)
```

Requires the `analysis` extra (`scipy`).

## Threats to Validity — Statistical conclusion validity (draft)

> **Statistical conclusion validity.** The design yields four conditions and
> five paired observations per comparison, which is small enough that the
> inferential machinery deserves explicit qualification. The test for each
> comparison is selected by a rule fixed before any result was produced —
> Shapiro–Wilk on the paired differences, routing to a paired t-test above
> α = 0.05 and to a Wilcoxon signed-rank test below it — and the branch taken is
> reported for every comparison, so the choice is auditable rather than
> post hoc. Two limits follow from the sample size and we state them rather than
> work around them. First, at n = 5 a two-sided Wilcoxon signed-rank test cannot
> produce a p-value below 0.05 at all, its minimum attainable value being
> 0.0625; a comparison routed to it is therefore incapable of reaching
> significance regardless of effect magnitude, and we mark such comparisons
> explicitly. Second, and consequently, at this sample size the attainability of
> significance depends on which branch the normality test selects rather than on
> the size of the effect. We therefore report Cohen's dₙ, the rank-biserial
> correlation, confidence intervals on the mean difference, and the raw paired
> measurements for every comparison, and we base our conclusions on effect
> magnitude and consistency of direction across tasks rather than on
> significance thresholds. Holm–Bonferroni correction is applied within each
> metric-and-task family. We do not claim that any single comparison
> establishes an effect; the claims rest on the direction and magnitude of
> differences reproducing across four tasks and three datasets.
