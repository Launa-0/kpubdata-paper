# The storage trade-off

The paper claims that layering reduces the cost of *analysing* data. It does not
claim that layering is free, and the cost is not hard to name: the same facts
are kept three times, at three levels of refinement.

Measuring that cost is not a concession. A paper that reports only the side of
the ledger its hypothesis is about has not evaluated a trade-off, it has
advertised one.

## What is measured

```
amplification factor = (Bronze + Silver + Gold) / final-only
```

The denominator is what a monolithic pipeline leaves on disk. It persists no
intermediate, so its footprint is its final output — and since the baseline is
*required* to reach the same analysis input as the full Medallion path
([monolithic-baseline.md](monolithic-baseline.md)), that footprint is the Gold
artifact's. So the comparison is between the same data stored once and the same
data stored three times, which is exactly the cost the RQ2 savings are weighed
against.

```python
profile = measure_storage(store, "seoul-apartment-trades")
profile.amplification_factor   # 5.0
profile.overhead_bytes         # what layering costs over final-only
storage_table([profile])       # per-layer bytes beside the factor
```

Sizes come from the build records, not from the filesystem: a reader who never
restores the artifacts still has the numbers, and a size measured at analysis
time could not be attributed to a particular build.

Four things the measurement refuses to do, each because doing them would flatter
the result:

| | |
| :--- | :--- |
| Sum layers from different pipeline versions or snapshots | would attribute a configuration change to layering |
| Report a factor over an incomplete layer set | would understate what keeping three layers costs |
| Count a failed build's bytes | a build that broke produced no stored dataset |
| Pick a baseline when several Golds exist | would halve the factor silently — see below |

`bytes_per_row` is reported per layer because format is the one thing a
provenance record cannot check. If Bronze were JSON and Gold compressed
Parquet, the factor would be measuring the codec; a difference of that kind
shows up here as a ratio nothing else explains.

## Discussion — at what scale does layering pay? (draft)

> **The trade-off is between a one-time multiple and a recurring saving.**
> Storage amplification is paid once per dataset and scales linearly with the
> data; the preparation cost that RQ2 measures is paid *once per analysis*. A
> layered pipeline therefore pays for itself at a break-even that depends on how
> many analyses the Silver and Gold layers go on to serve, not on the size of
> the data. For a dataset analysed once, the amplification is pure loss. For one
> that is analysed repeatedly — which is the case public reference data is
> published for — the same multiple is amortized over every analysis that
> follows, and the comparison to make is between a constant factor of storage
> and a recurring factor of analyst effort. Storage of this kind is also the
> cheaper of the two resources by a wide margin at the scale of the datasets
> studied here (≈234K–1.22M rows), where every layer of every dataset fits on
> commodity storage; that ceases to be true at scales where the Bronze layer
> alone is an infrastructure decision, and we do not extrapolate there.

> **Costs the amplification factor does not capture.** Four are worth stating
> because they fall outside what a byte count can express. *Per-layer dataset
> management*: three artifacts per dataset must each be built, verified and
> republished, and our own harness needed a provenance record per build to keep
> them straight. *Pipeline complexity*: the Medallion path has more moving parts
> than the monolithic baseline by construction, and the effort it saves
> downstream is in part effort relocated into the pipeline — which is a real
> transfer, though to a place where it is paid once rather than per analysis.
> *Schema versioning*: each layer has a contract that can break independently,
> and R2 measures precisely that; a monolithic pipeline has one contract to
> break instead of three. *Gold specificity and proliferation*: a Gold dataset
> is task-oriented, so serving a new question tends to mean a new Gold rather
> than a reuse of an old one, and the layer grows with the number of questions
> asked. Our measurement counts every sibling Gold toward Medallion storage for
> that reason, and refuses to compute an amplification factor when several exist
> until the one the baseline reproduces is named, since choosing silently would
> halve the reported cost.

> **What we do not claim.** We do not claim that the Medallion structure
> dominates the monolithic baseline. We report both sides and the scale at which
> we measured them, and the conclusion is conditional on the number of
> downstream analyses a dataset is expected to serve.

## Pending #7

The numbers themselves need built artifacts. Once the three datasets have a
complete Bronze/Silver/Gold set recorded, `storage_table` produces the row for
each and the Discussion above takes its figures from it. The reasoning does not
depend on how the numbers come out; the claim is conditional either way.
