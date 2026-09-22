"""Task 1 — 서울 아파트 가격 집계 및 추세 분석 (#13)."""

from __future__ import annotations

from kpx.runner import Task
from kpx.tasks.task01_price_analysis import analysis, bronze, gold, monolithic, silver
from kpx.tasks.task01_price_analysis import transforms as transforms_module

TASK = Task(
    name="task01",
    dataset="seoul-apartment-trades",
    analyze=analysis.analyze,
    runners={
        "bronze": bronze.Runner(),
        "silver": silver.Runner(),
        "gold": gold.Runner(),
        "monolithic": monolithic.Runner(),
    },
    transforms=transforms_module,
)

__all__ = ["TASK", "analysis", "bronze", "gold", "monolithic", "silver"]
