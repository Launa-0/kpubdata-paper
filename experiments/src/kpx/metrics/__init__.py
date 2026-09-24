"""Measurement modules.

=======================  =====  ============================================
:mod:`roles`             RQ1    semantic roles and per-layer projection
:mod:`pairing`           RQ1    role × transition-cause counts (primary)
:mod:`quality`           RQ1    per-layer integrity checks and diagnostics
:mod:`code_metrics`      RQ2    preprocessing LOC, function count, steps
:mod:`reproducibility`   RQ3    R1 rebuild determinism
=======================  =====  ============================================

Execution time is measured by the timing protocol in ``scripts/_timing.py``, not
by a module here.
"""
