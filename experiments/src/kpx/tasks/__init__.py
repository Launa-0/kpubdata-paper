"""Downstream analysis tasks.

Each task package holds one shared ``analysis`` module and four condition
modules implementing :class:`kpx.contract.ConditionRunner`:

==========================  ==================================================
``task01_price_analysis``   Seoul apartment price aggregation and trend
``task02_prediction``       Apartment price-per-m2 prediction
``task03_join``             Trade + rent integration, jeonse ratio
``task04_bike``             Bike rental monthly time series
==========================  ==================================================
"""
