# Why there is no user study

The initial plan included a small user study — five to eight peers performing
the same task under each condition. It is **excluded from the main experiment**.
This records the decision and, more importantly, what the exclusion costs, so
that the paper states the limitation rather than leaving a reader to infer it.

## The decision

| | |
| :--- | :--- |
| Main evidence | automated engineering metrics only |
| User study | excluded from the main experiment |
| Exploratory study | optional; auxiliary observation only, never a basis for a main conclusion |

## Why

Five reasons, and they compound rather than sit side by side:

* **Sample size.** Five to eight participants across four conditions leaves
  almost nothing per cell, and between-person variation is far larger than the
  variation in the machine measurements.
* **Variation in Python proficiency.** Between-subject skill differences would
  dominate a between-condition effect at this sample size.
* **Variation in analysis experience.** Familiarity with public-data quirks —
  comma-formatted amounts, split date fields, district codes — is exactly what
  the Bronze condition taxes, so prior exposure to this data would confound the
  condition it is meant to measure.
* **Design complexity.** Controlling for learning effects across four conditions
  needs counterbalancing, which multiplies the participants required.
* **Ethics review.** Human-subject measurement may require institutional review,
  and that timeline does not fit the submission.

## What the exclusion costs

This is the part that belongs in the paper rather than in a planning document.

**The study measures the cost of the code, not the cost of the analyst.** RQ2
asks how much preparation a condition takes before analysis can begin and what
recomputation costs, and answers with `preprocessing_loc`, `function_count` and
timed recomputation. Every one of those is a property of a program. None of them is a
measure of human time, comprehension, or the number of attempts a person needs
before the parse is right.

The two are related but not interchangeable, and the relation is not uniform: a
condition needing three extra transformation steps does not obviously cost an
analyst three times more thought, and a condition whose failure mode is a silent
wrong number — the Bronze `"120,000"` read as `120` — may cost far more human
time than its line count suggests while costing a machine nothing.

So the claim the paper can support is narrower than "layering reduces analyst
effort". It is about the *volume of preparation code* each condition needs,
with representation changes (RQ1) and reproducibility (RQ3)
measured separately. The paper does not call this "analytical effort".

## The exploratory study

The policy, if one is ever run: it is presented as auxiliary observation and
never as a basis for a main conclusion. Its sample size does not change with the
label, so neither does what it can support.

**For this submission: not run.** The condition under which that changes is
schedule slack after the main experiments are complete, and it is the authors'
call rather than the harness's; this file records the policy so that the
decision is not re-litigated from scratch if the slack appears.

## Threats to Validity — Construct Validity, human cost (draft)

> **What RQ2 measures.** RQ2 is operationalized entirely through automated
> measurements — the lines and distinct transformation functions of the
> preparation code, and the wall-clock time of recomputation. We deliberately excluded a user study from
> the main experiment: with five to eight available participants spread over
> four conditions, between-subject variation in Python proficiency and in prior
> exposure to Korean public-data conventions would have dominated any
> between-condition effect, the counterbalancing required to control for
> learning across four conditions would have multiplied the sample needed, and
> human-subject measurement carries a review timeline the study could not
> accommodate. The consequence is a limit on what we claim rather than a
> weakness we can argue away: our measurements characterise the program a
> condition requires, not the time or the cognitive load of the person writing
> it. These are related but not proportional, and plausibly least proportional
> where the difference matters most — a Bronze-layer failure in which a
> comma-formatted amount is silently parsed as a smaller number costs a machine
> nothing and an analyst a great deal. Accordingly we claim that higher layers
> reduce the volume of preparation code, with the equivalence of analytical
> results checked as a validity condition, and we do not claim a measured
> reduction in human effort. Any exploratory study conducted later is reported
> as auxiliary observation and is not used to support a main conclusion.
