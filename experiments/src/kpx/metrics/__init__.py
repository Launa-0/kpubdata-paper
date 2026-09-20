"""Measurement modules.

One module per hypothesis, each producing fields of the experiment result
schema:

===================  ====  ==================================================
:mod:`quality`       H1    type consistency, missing, duplicate, schema,
                           code validity, parsing failure
:mod:`code_metrics`  H2    preprocessing LOC, function count, step count
:mod:`runtime`       H2    wall-clock runtime and peak memory
:mod:`reproducibility` H4  output hash, row/schema equality, build success
===================  ====  ==================================================
"""
