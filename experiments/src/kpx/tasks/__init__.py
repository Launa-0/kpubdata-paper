"""Downstream analysis tasks.

Each task package holds one shared ``analysis`` module and four condition
modules implementing :class:`kpx.contract.ConditionRunner`:

==========================  ==================================================
``task01_price_analysis``   Seoul apartment price aggregation and trend
``task03_join``             Trade + rent integration, jeonse ratio
==========================  ==================================================

These are the only downstream tasks. The bike data serves RQ1 and the source
evolution experiment, not a downstream task.
"""
