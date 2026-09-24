"""Downstream analysis tasks.

Each task package holds one shared ``analysis`` module and four condition
modules implementing :class:`kpx.contract.ConditionRunner`:

==========================  ==================================================
``task01_price_analysis``   Seoul apartment price aggregation and trend
``task03_join``             Trade + rent integration, jeonse ratio
==========================  ==================================================

T2 (price prediction) and T4 (bike time series) were planned and dropped; see
``docs/experiment-design-revisions.md``. The bike data stays in the study for
RQ1 and source evolution, not as a downstream task.
"""
